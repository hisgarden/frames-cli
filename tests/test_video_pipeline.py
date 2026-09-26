import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from PIL import Image


FRAMES_PATH = Path(__file__).resolve().parents[1] / "frames"
loader = importlib.machinery.SourceFileLoader("frames_video_tests", str(FRAMES_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
frames = importlib.util.module_from_spec(spec)
loader.exec_module(frames)


class VideoPipelineTests(unittest.TestCase):
    def test_metadata_reads_header_without_decoding_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (30, 54)).save(root / "Test.png")
            entry = {"x": 2, "y": 2}
            with mock.patch.object(frames, "resolve_device_entry", return_value=(entry, "Test", "Test", False)):
                with mock.patch.object(Image.Image, "load", side_effect=AssertionError("decoded PNG")):
                    result = frames.resolve_frame_metadata(24, 48, root, {})
            self.assertEqual(result["frame_size"], "30x54")

    def test_sideways_landscape_assets_are_rotated_in_filter_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (30, 54)).save(root / "Phone Landscape.png")
            Image.new("L", (24, 48)).save(root / "Phone Landscape_mask.png")
            devices = {"48": {"name": "Phone Landscape", "x": "3", "y": "3", "mask": "yes"}}
            frame_meta = frames.resolve_frame_metadata(48, 24, root, devices)
            self.assertEqual(frame_meta["frame_size"], "54x30")

            args = Namespace(background=None, alpha=False, codec="h264", rotate="none")
            _, filters, _, _ = frames._framed_video_filters(
                Path("source.mp4"), frame_meta, {"fps_rate": "30/1", "duration": 1.0}, args, prefix="a",
            )
            graph = ";".join(filters)
            self.assertIn("[1:v]format=gray,transpose=2[am0]", graph)
            self.assertIn("[2:v]transpose=2[af0]", graph)
            self.assertIn("[atmp][af0]overlay=0:0", graph)

    def test_progress_drains_large_stderr_and_retains_error(self):
        # Run in a separate process so a pipe regression fails with a timeout.
        worker = """
import contextlib, importlib.machinery, importlib.util, io, json, sys
loader = importlib.machinery.SourceFileLoader('frames_progress_test', sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
frames = importlib.util.module_from_spec(spec)
loader.exec_module(frames)
child = [sys.executable, '-c', "import sys; sys.stderr.write('E' * 1048576); sys.stderr.flush(); print('out_time_ms=500000'); print('progress=end'); sys.exit(7)"]
frames._ffmpeg_progress_cmd = lambda command: command
with contextlib.redirect_stdout(io.StringIO()):
    result = frames._run_ffmpeg_with_progress(child, 'Test', 1)
print(json.dumps({'returncode': result.returncode, 'stderr_length': len(result.stderr)}))
"""
        result = subprocess.run(
            [sys.executable, "-c", worker, str(FRAMES_PATH)],
            capture_output=True, text=True, check=True, timeout=15,
        )
        self.assertEqual(json.loads(result.stdout), {"returncode": 7, "stderr_length": 1048576})

    def test_distinct_sources_cannot_share_an_output_but_repeated_input_can(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for directory in ("first", "second"):
                folder = root / directory
                folder.mkdir()
                source = folder / "same.mp4"
                source.write_bytes(directory.encode())
                sources.append({"src": source})
            args = Namespace(output=str(root / "output"), alpha=False, codec="h264", background=None)
            with self.assertRaisesRegex(ValueError, "Multiple input videos"):
                frames._individual_video_output_paths(sources, args)
            paths = frames._individual_video_output_paths([sources[0], sources[0]], args)
            self.assertEqual(paths[0], paths[1])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class DirectMergeMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        Image.new("RGBA", (29, 53), (0, 0, 0, 0)).save(self.root / "frame.png")
        mask = Image.new("L", (24, 48), 255)
        mask.putpixel((0, 0), 0)
        mask.putpixel((1, 0), 128)
        mask.save(self.root / "mask.png")
        self.items = []
        for idx, color in enumerate(("red", "blue")):
            src = self.root / (color + ".mp4")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                   "color=c=" + color + ":s=24x48:r=30:d=0.3"]
            if idx == 0:
                cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.3"]
            cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "0.3", str(src)]
            subprocess.run(cmd, check=True, capture_output=True)
            self.items.append({
                "src": src,
                "video_meta": {"duration": 0.3, "fps_rate": "30/1", "audio": idx == 0},
                "frame_meta": {"frame_width": 29, "frame_height": 53, "physicalHeight": 100,
                               "frame_path": str(self.root / "frame.png"), "mask_path": str(self.root / "mask.png"),
                               "resize_width": None, "resize_height": None, "x": 2, "y": 2},
                "info": {},
            })

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, **overrides):
        values = dict(spacing=3, no_scale=False, playback_offset=False, strip_audio=False,
                      background=None, alpha=False, codec="h264", preset="best", quality=None, rotate="none")
        values.update(overrides)
        return Namespace(**values)

    def decode_rgba(self, video):
        result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
                                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                                check=True, capture_output=True)
        meta = frames.probe_video(video)
        return Image.frombytes("RGBA", (meta["width"], meta["height"]), result.stdout)

    def test_alpha_merge_preserves_mask_and_transparent_spacing(self):
        output = self.root / "alpha.mov"
        result = frames.render_merged_video(self.items, output, self.args(alpha=True))
        self.assertEqual((result["width"], result["height"]), (61, 53))
        with self.decode_rgba(output) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertEqual(image.getpixel((30, 25))[3], 0)
            self.assertEqual(image.getpixel((2, 2))[3], 0)
            self.assertLessEqual(abs(image.getpixel((3, 2))[3] - 128), 2)
            self.assertEqual(image.getpixel((12, 24))[3], 255)
            self.assertGreater(image.getpixel((12, 24))[0], 240)
            self.assertGreater(image.getpixel((44, 24))[2], 240)

    def test_sequential_merge_preserves_audio_then_silence_and_even_padding(self):
        output = self.root / "sequential.mp4"
        for item in self.items:
            item["info"].update(output_width=30, output_height=54)
        result = frames.render_merged_video(self.items, output, self.args(playback_offset=True))
        self.assertEqual((result["width"], result["height"]), (64, 54))
        meta = frames.probe_video(output)
        self.assertTrue(meta["audio"])
        self.assertAlmostEqual(meta["duration"], 0.6, delta=0.06)
        pcm = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(output),
                              "-vn", "-ac", "1", "-ar", "44100", "-f", "s16le", "-"],
                             check=True, capture_output=True).stdout
        import array
        samples = array.array("h", pcm)
        self.assertGreater(max(abs(value) for value in samples[4410:8820]), 1000)
        self.assertLess(max(abs(value) for value in samples[19845:24255]), 10)
        with self.decode_rgba(output) as image:
            self.assertGreater(image.getpixel((12, 24))[0], 230)
            self.assertGreater(image.getpixel((45, 24))[2], 230)
            self.assertGreater(min(image.getpixel((63, 53))[:3]), 240)

    def test_merge_can_replace_an_input_after_reading_it(self):
        output = self.items[0]["src"]
        for item in self.items:
            item["info"].update(output_width=30, output_height=54)
        frames.render_merged_video(self.items, output, self.args())
        self.assertEqual(frames.probe_video(output)["width"], 64)
        self.assertFalse(list(self.root.glob(".frames-video-*")))

    def test_failed_merge_does_not_replace_an_input(self):
        output = self.items[0]["src"]
        original = output.read_bytes()
        with mock.patch.object(frames, "_run_ffmpeg", side_effect=RuntimeError("encoder failed")):
            with self.assertRaisesRegex(RuntimeError, "encoder failed"):
                frames.render_merged_video(self.items, output, self.args())
        self.assertEqual(output.read_bytes(), original)
        self.assertFalse(list(self.root.glob(".frames-video-*")))

    def test_single_export_preserves_source_behind_output_links(self):
        item = self.items[0]
        original = item["src"].read_bytes()
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                output = self.root / (kind + ".mp4")
                if kind == "symlink":
                    output.symlink_to(item["src"])
                else:
                    os.link(item["src"], output)
                frames.render_framed_video(item["src"], output, item["frame_meta"], item["video_meta"], self.args())
                self.assertEqual(item["src"].read_bytes(), original)
                self.assertEqual(frames.probe_video(output)["width"], 30)
        self.assertFalse(list(self.root.glob(".frames-video-*")))

    def test_directory_input_collision_fails_before_any_render(self):
        for item, name in zip(self.items, ("a.mp4", "a_framed.mp4")):
            item["src"] = item["src"].rename(self.root / name)
        originals = {item["src"]: item["src"].read_bytes() for item in self.items}
        filenames = set(self.root.iterdir())
        metadata = dict(self.items[0]["frame_meta"])
        metadata.update(device="Test", primary_match="Test", color=None, frame_size="29x53",
                        has_mask=True, mask_missing=False)
        args = self.args(files=[str(self.root)], assets=str(self.root), output=None,
                         json=True, verbose=False, device=None, color=None, merge=False)
        with mock.patch.object(frames, "load_json", return_value={}):
            with mock.patch.object(frames, "load_config", return_value={}):
                with mock.patch.object(frames, "resolve_frame_metadata", return_value=metadata):
                    with mock.patch.object(frames, "render_framed_video") as render:
                        with mock.patch("sys.stderr") as errors:
                            with self.assertRaises(SystemExit) as caught:
                                frames.cmd_video(args)
        self.assertEqual(caught.exception.code, 1)
        render.assert_not_called()
        self.assertIn("separate output directory", str(errors.write.call_args_list))
        self.assertEqual(set(self.root.iterdir()), filenames)
        for source, original in originals.items():
            self.assertEqual(source.read_bytes(), original)

    def test_sequential_merge_holds_future_first_and_completed_last_frames(self):
        for item, first, last in zip(self.items, ("red", "blue"), ("yellow", "lime")):
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                "color=c=" + first + ":s=24x48:r=30:d=0.3,drawbox=c=" + last + ":t=fill:enable='gte(t,0.1)'",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(item["src"]),
            ], check=True, capture_output=True)
            item["video_meta"]["audio"] = False
            item["info"].update(output_width=30, output_height=54)
        output = self.root / "holds.mp4"
        frames.render_merged_video(self.items, output, self.args(playback_offset=True, strip_audio=True))
        raw = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(output),
            "-f", "rawvideo", "-pix_fmt", "rgba", "-",
        ], check=True, capture_output=True).stdout
        frame_bytes = 64 * 54 * 4
        self.assertEqual(len(raw) // frame_bytes, 18)
        with Image.frombytes("RGBA", (64, 54), raw[5 * frame_bytes:6 * frame_bytes]) as early:
            self.assertGreater(min(early.getpixel((12, 24))[:2]), 230)  # First video reached yellow.
            self.assertGreater(early.getpixel((45, 24))[2], 230)  # Future video holds blue.
        with Image.frombytes("RGBA", (64, 54), raw[14 * frame_bytes:15 * frame_bytes]) as late:
            self.assertGreater(min(late.getpixel((12, 24))[:2]), 230)  # Completed video holds yellow.
            self.assertGreater(late.getpixel((45, 24))[1], 230)  # Active second video reached green.


if __name__ == "__main__":
    unittest.main()
