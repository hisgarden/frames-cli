"""Portable HEVC alpha contracts; native auxiliary-alpha decoding is checked separately."""

import importlib.machinery
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from PIL import Image


FRAMES_PATH = Path(__file__).resolve().parents[1] / "frames"
loader = importlib.machinery.SourceFileLoader("frames_hevc_alpha_tests", str(FRAMES_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
frames = importlib.util.module_from_spec(spec)
loader.exec_module(frames)

ENCODER_HELP = """Encoder hevc_videotoolbox [VideoToolbox H.265 Encoder]:
    Supported pixel formats: nv12 yuv420p bgra
hevc_videotoolbox AVOptions:
    -alpha_quality <double> Quality for alpha layer (from 0 to 1) (default 0)
"""


class HEVCAlphaTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.assets / "version.txt").write_text("4", encoding="utf-8")
        (self.assets / "NewFrames.json").write_text(json.dumps({
            "24": {"name": "Test", "x": 2, "y": 2, "mask": "yes", "physicalHeight": 100},
        }), encoding="utf-8")
        Image.new("RGBA", (29, 53), (0, 0, 0, 0)).save(self.assets / "Test.png")
        Image.new("L", (24, 48), 128).save(self.assets / "Test_mask.png")
        self.sources = [self.root / "first.mov", self.root / "second.mov"]
        for source in self.sources:
            source.write_bytes(b"original source")
        self.stack.enter_context(mock.patch.object(frames, "CONFIG_FILE", self.root / "config.json"))
        self.stack.enter_context(mock.patch.object(frames.sys, "platform", "darwin"))
        self.stack.enter_context(mock.patch.object(frames.C, "enabled", False))
        self.stack.enter_context(mock.patch.object(frames, "require_ffmpeg_tools"))
        self.stack.enter_context(mock.patch.object(frames.shutil, "which", return_value="/test/ffmpeg"))
        self.capability = self.stack.enter_context(mock.patch.object(
            frames.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, ENCODER_HELP, ""),
        ))
        self.probe = self.stack.enter_context(mock.patch.object(frames, "probe_video", return_value={
            "width": 24, "height": 48, "duration": 0.5, "fps": 30.0,
            "fps_rate": "30/1", "codec": "source-codec", "audio": False, "audio_codec": None,
        }))
        self.render = self.stack.enter_context(mock.patch.object(frames, "_run_ffmpeg", side_effect=self.fake_render))
        self.stderr = ""

    def fake_render(self, command, **kwargs):
        Path(command[-1]).write_bytes(b"encoded output")
        return subprocess.CompletedProcess(command, 0, "", "")

    def args(self, *options):
        return frames.build_parser().parse_args(["video"] + list(options) + [str(self.sources[0])])

    def run_command(self, options, merge=False, output=None):
        argv = ["frames", "--json", "--assets", str(self.assets), "video"] + list(options)
        if merge:
            argv += ["--merge", "--spacing", "3"]
        if output is not None:
            argv += ["--output", str(output)]
        argv += [str(source) for source in (self.sources if merge else self.sources[:1])]
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                frames.main()
            finally:
                self.stderr = stderr.getvalue()
        return json.loads(stdout.getvalue())

    def assert_hevc_alpha_command(self, command, kwargs):
        for option, value in (("-c:v", "hevc_videotoolbox"), ("-pix_fmt", "bgra"),
                              ("-alpha_quality", "1"), ("-allow_sw", "1"), ("-tag:v", "hvc1")):
            self.assertIn(option, command)
            self.assertEqual(command[command.index(option) + 1], value)
        self.assertIsNone(kwargs.get("fallback_cmd"))
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("alphamerge", graph)
        self.assertIn("format=bgra[out]", graph)
        self.assertNotIn("format=yuv420p", graph)
        self.assertNotIn("prores_ks", command)
        self.assertNotIn("libx265", command)
        self.assertEqual(Path(command[-1]).suffix, ".mov")
        return graph

    def test_defaults_and_explicit_backgrounds_preserve_legacy_alpha_selection(self):
        cases = [
            (("--codec", "hevc-alpha"), "transparent", "hevc_videotoolbox", (30, 54)),
            (("--codec", "hevc-alpha", "--background", "white"), "white", "hevc_videotoolbox", (30, 54)),
            (("--codec", "hevc-alpha", "--background", "#123456"), "#123456", "hevc_videotoolbox", (30, 54)),
            (("--alpha",), "transparent", "prores_ks", (29, 53)),
            (("--alpha", "--codec", "hevc"), "transparent", "prores_ks", (29, 53)),
            (("--codec", "hevc", "--background", "transparent"), "transparent", "prores_ks", (29, 53)),
        ]
        for options, background, encoder, dimensions in cases:
            with self.subTest(options=options):
                args = self.args(*options)
                self.assertEqual(frames._video_background(args), background)
                self.assertTrue(frames._output_uses_alpha(args))
                self.assertEqual(frames._video_output_path(self.sources[0], args).suffix, ".mov")
                self.assertEqual(frames._encoded_video_dimensions(29, 53, args), dimensions)
                encoder_args, _ = frames._encoder_args(args)
                self.assertEqual(encoder_args[encoder_args.index("-c:v") + 1], encoder)

    def test_single_and_merged_filters_keep_alpha_and_pad_with_chosen_background(self):
        for merge in (False, True):
            for background, canvas_color in (("transparent", "black@0.0"), ("white", "white"),
                                             ("black", "black"), ("#123456", "0x123456")):
                with self.subTest(merge=merge, background=background):
                    result = self.run_command(["--codec", "hevc-alpha", "--background", background], merge=merge)
                    command, kwargs = self.render.call_args
                    graph = self.assert_hevc_alpha_command(command[0], kwargs)
                    if merge:
                        # Two 29x53 frames and a 3px gap occupy 61x53 before encoding.
                        self.assertEqual(result["dimensions"], "62x54")
                        self.assertRegex(graph, "pad=62:54:0:0:color=" + re.escape(canvas_color) + r"(?=[,;\[])")
                        self.assertNotIn("pad=30:54", graph)
                        self.assertNotIn(",scale=", graph)
                        self.assertEqual(graph.count("pad="), 1)
                    else:
                        self.assertEqual(result["output_dimensions"], "30x54")
                        self.assertRegex(graph, "pad=30:54:0:0:color=" + re.escape(canvas_color) + r"(?=[,;\[])")
                    self.assertIn("color=c=" + canvas_color, graph)

    def test_ayuv_encoder_input_converts_only_the_final_canvas(self):
        # ffmpeg 8+ lists ayuv; the default help above models older builds that only take bgra.
        self.capability.return_value = subprocess.CompletedProcess([], 0, ENCODER_HELP.replace(" bgra", " bgra ayuv"), "")
        for merge in (False, True):
            with self.subTest(merge=merge):
                self.run_command(["--codec", "hevc-alpha"], merge=merge)
                command = self.render.call_args.args[0]
                self.assertEqual(command[command.index("-pix_fmt") + 1], "ayuv")
                self.assertEqual(command[command.index("-colorspace") + 1], "bt709")
                graph = command[command.index("-filter_complex") + 1]
                self.assertIn("format=gbrap,scale=out_color_matrix=bt709:out_range=tv,format=ayuv[out]", graph)
                self.assertEqual(graph.count("format=ayuv"), 1)

    def test_merge_scales_original_frame_dimensions_by_physical_height(self):
        devices = frames.load_json(self.assets)
        devices["12"] = {"name": "Small", "x": 2, "y": 2, "physicalHeight": 40}
        (self.assets / "NewFrames.json").write_text(json.dumps(devices), encoding="utf-8")
        Image.new("RGBA", (17, 31), (0, 0, 0, 0)).save(self.assets / "Small.png")
        source_metadata = self.probe.return_value.copy()

        def probe_source(source):
            result = source_metadata.copy()
            if source == self.sources[1]:
                result.update(width=12, height=24)
            return result

        self.probe.side_effect = probe_source
        result = self.run_command(["--codec", "hevc-alpha"], merge=True)
        # At 0.53 pixels/mm, the smaller frame becomes 12x21 without padding first.
        self.assertEqual(result["dimensions"], "44x54")
        self.assertEqual([item["output_dimensions"] for item in result["frames"]], ["29x53", "17x31"])
        self.assertEqual([item["padded"] for item in result["frames"]], [False, False])
        self.assertEqual([item["scale_factor"] for item in result["frames"]], [1.0, round(21 / 31, 4)])
        command = self.render.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("scale=12:21", graph)
        self.assertIn("overlay=32:32:format=auto", graph)
        self.assertIn("pad=44:54", graph)
        self.assertEqual(graph.count("pad="), 1)

    def test_presets_use_hevc_bitrates_for_single_and_merged_exports(self):
        for merge in (False, True):
            for preset, bitrate in (("compact", "4M"), ("balanced", "7M"), ("best", "10M")):
                with self.subTest(merge=merge, preset=preset):
                    self.run_command(["--codec", "hevc-alpha", "--preset", preset], merge=merge)
                    command = self.render.call_args.args[0]
                    self.assertEqual(command[command.index("-b:v") + 1], bitrate)

    def test_json_reports_effective_output_codec_without_replacing_source_codec(self):
        cases = [
            (["--codec", "h264"], "h264"), (["--codec", "hevc"], "hevc"),
            (["--codec", "prores"], "prores"), (["--alpha", "--codec", "hevc"], "prores"),
            (["--codec", "hevc-alpha"], "hevc-alpha"),
        ]
        for merge in (False, True):
            for options, output_codec in cases:
                with self.subTest(merge=merge, options=options):
                    result = self.run_command(options, merge=merge)
                    self.assertEqual(result["output_codec"], output_codec)
                    if merge:
                        expected_size = {"h264": "64x54", "hevc": "64x54", "prores": "61x53", "hevc-alpha": "62x54"}
                        self.assertEqual(result["dimensions"], expected_size[output_codec])
                    inputs = result["frames"] if merge else [result]
                    for item in inputs:
                        self.assertEqual(item["output_codec"], output_codec)
                        self.assertEqual(item["codec"], "source-codec")
                    if output_codec == "hevc-alpha":
                        for item in inputs:
                            self.assertTrue(item["alpha"])
                            self.assertEqual(item["padded"], not merge)
                            self.assertEqual(item["output_dimensions"], "29x53" if merge else "30x54")
                            self.assertEqual(item["background"], "transparent")

    def test_unavailable_alpha_support_fails_before_probe_or_output_creation(self):
        cases = [
            ("linux", 0, ENCODER_HELP, "macOS"),
            ("darwin", 0, "Unknown encoder 'hevc_videotoolbox'", "hevc_videotoolbox"),
            ("darwin", 0, ENCODER_HELP.replace("-alpha_quality", "-other_option"), "alpha"),
            ("darwin", 0, ENCODER_HELP.replace(" bgra", ""), "bgra"),
            ("darwin", 1, "", "hevc"),
        ]
        for platform, returncode, help_text, diagnostic in cases:
            with self.subTest(platform=platform, help=help_text):
                self.capability.return_value = subprocess.CompletedProcess([], returncode, help_text, "")
                before = set(self.root.rglob("*"))
                with mock.patch.object(frames.sys, "platform", platform):
                    with self.assertRaises(SystemExit) as caught:
                        self.run_command(["--codec", "hevc-alpha"], output=self.root / "new" / "out.mov")
                self.assertEqual(caught.exception.code, 1)
                self.assertIn(diagnostic.lower(), self.stderr.lower())
                self.assertNotIn("Traceback", self.stderr)
                self.probe.assert_not_called()
                self.render.assert_not_called()
                self.assertEqual(set(self.root.rglob("*")), before)

    def test_invalid_quality_or_mp4_output_fails_before_output_creation(self):
        for options, suffix, diagnostic in (
            (["--quality", "0"], ".mov", "--preset"),
            (["--quality", "51"], ".mov", "--preset"),
            ([], ".mp4", ".mov"),
        ):
            with self.subTest(options=options, suffix=suffix):
                before = set(self.root.rglob("*"))
                with self.assertRaises(SystemExit) as caught:
                    self.run_command(["--codec", "hevc-alpha"] + options,
                                     output=self.root / "new" / ("out" + suffix))
                self.assertEqual(caught.exception.code, 1)
                self.assertIn(diagnostic, self.stderr)
                self.render.assert_not_called()
                self.assertEqual(set(self.root.rglob("*")), before)

    def test_direct_renderers_check_support_before_creating_output_directory(self):
        args = self.args("--codec", "hevc-alpha")
        metadata = frames.resolve_frame_metadata(24, 48, self.assets, frames.load_json(self.assets))
        video = self.probe.return_value
        item = {"src": self.sources[0], "frame_meta": metadata, "video_meta": video, "info": {}}
        output = self.root / "new" / "out.mov"
        with mock.patch.object(frames.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "macOS"):
                frames.render_framed_video(self.sources[0], output, metadata, video, args)
            with self.assertRaisesRegex(RuntimeError, "macOS"):
                frames.render_merged_video([item, item], output, args)
        self.assertFalse(output.parent.exists())
        self.render.assert_not_called()

    def test_legacy_prores_remains_available_without_videotoolbox(self):
        self.capability.side_effect = AssertionError("ProRes must not require VideoToolbox")
        with mock.patch.object(frames.sys, "platform", "linux"):
            result = self.run_command(["--alpha", "--codec", "hevc"])
        self.assertEqual(result["output_codec"], "prores")
        self.assertEqual(result["output_dimensions"], "29x53")
        self.assertIn("prores_ks", self.render.call_args.args[0])

    def test_encoder_failure_has_no_fallback_and_preserves_aliased_source(self):
        for merge in (False, True):
            with self.subTest(merge=merge):
                self.render.reset_mock()
                self.render.side_effect = RuntimeError("HEVC alpha encoder failed")
                originals = {source: source.read_bytes() for source in self.sources}
                with self.assertRaises(SystemExit) as caught:
                    self.run_command(["--codec", "hevc-alpha"], merge=merge, output=self.sources[0])
                self.assertEqual(caught.exception.code, 1)
                self.assertIn("HEVC alpha encoder failed", self.stderr)
                self.render.assert_called_once()
                command, kwargs = self.render.call_args
                self.assert_hevc_alpha_command(command[0], kwargs)
                for source, original in originals.items():
                    self.assertEqual(source.read_bytes(), original)
                self.assertFalse(list(self.root.glob(".frames-video-*")))


if __name__ == "__main__":
    unittest.main()
