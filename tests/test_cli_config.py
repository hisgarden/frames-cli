import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock

from PIL import Image


FRAMES_PATH = Path(__file__).resolve().parents[1] / "frames"
loader = importlib.machinery.SourceFileLoader("frames_cli_config", str(FRAMES_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
frames = importlib.util.module_from_spec(spec)
loader.exec_module(frames)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.config_file = self.root / "config.json"
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.assets / "NewFrames.json").write_text('{"variants": {}}', encoding="utf-8")
        (self.assets / "version.txt").write_text("4", encoding="utf-8")
        (self.assets / "frame.png").touch()
        self.stack.enter_context(mock.patch.object(frames, "CONFIG_FILE", self.config_file))
        self.stack.enter_context(mock.patch.object(frames, "CONFIG_DIR", self.root))
        self.stack.enter_context(mock.patch.object(frames, "DEFAULT_ASSETS", self.assets))
        self.stack.enter_context(mock.patch.object(frames, "APPDATA_ASSETS", self.assets))
        self.stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(mock.patch.object(frames, "_video_tools_error", return_value=None))

    def test_invalid_config_fails_cleanly_and_doctor_reports_problem(self):
        invalid_configs = [
            b"null", b"[]", b"123", b'"text"', b"{", b"\xff",
            b'{"assets_path": 12}', b'{"assets_path": ""}',
            b'{"default_colors": ["iPhone 17 Pro"]}',
            b'{"use_subfolder": 12}', b'{"use_subfolder": "../outside"}',
        ]
        for content in invalid_configs:
            with self.subTest(config=content):
                self.config_file.write_bytes(content)
                with self.assertRaisesRegex(ValueError, "Invalid config at"):
                    frames.load_config()
                with self.assertRaises(ValueError):
                    frames.get_assets_dir()
                with self.assertRaises(ValueError):
                    frames.get_subfolder_setting(Namespace())
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    frames.cmd_doctor(Namespace(assets=None, json=True))
                result = json.loads(stdout.getvalue())
                self.assertFalse(result["ok"])
                self.assertTrue(result["config_present"])
                self.assertTrue(any("Config file is unreadable:" in issue for issue in result["issues"]))
                self.assertEqual(self.config_file.read_bytes(), content)

    def test_invalid_config_commands_do_not_write_outputs_or_settings(self):
        config_dir = self.root / ".config" / "frames"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        source = self.root / "shot.png"
        Image.new("RGB", (8, 12), "red").save(source)
        env = dict(os.environ, HOME=str(self.root), FRAMES_ASSETS=str(self.assets))
        for content in ('null', '{"default_colors": []}', '{"use_subfolder": "../outside"}'):
            for command in (
                ["frame", str(source)], ["setup", str(self.assets)],
                ["setup", "--subfolder"], ["setup", "--no-subfolder"],
            ):
                with self.subTest(config=content, command=command):
                    config_file.write_text(content, encoding="utf-8")
                    before = set(self.root.rglob("*"))
                    process = subprocess.run(
                        [sys.executable, str(FRAMES_PATH), "--json"] + command,
                        env=env, capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(process.returncode, 1)
                    result = json.loads(process.stdout)
                    self.assertIn(str(config_file), result["error"])
                    self.assertIn("frames doctor", result["error"])
                    self.assertNotIn("Traceback", process.stderr)
                    self.assertEqual(config_file.read_text(encoding="utf-8"), content)
                    self.assertEqual(set(self.root.rglob("*")), before)

    def test_setup_subfolder_flags_only_update_saved_preference(self):
        config = {
            "assets_path": str(self.root / "unavailable-assets"),
            "default_colors": {"iPhone 17 Pro": "Silver"},
            "future_setting": {"preserve": [1, 2]},
        }
        frames.save_config(config)
        for flag, enabled in (("--subfolder", True), ("--no-subfolder", False)):
            with self.subTest(flag=flag):
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(sys, "argv", ["frames", "setup", flag]))
                    stack.enter_context(mock.patch.object(sys.stdin, "isatty", return_value=False))
                    stack.enter_context(mock.patch.object(frames.C, "enabled", False))
                    unexpected = [
                        stack.enter_context(mock.patch.object(frames, name))
                        for name in ("guided_setup", "download_assets", "offer_video_tools_setup", "check_assets_version", "require_ffmpeg_tools")
                    ]
                    stdout = stack.enter_context(redirect_stdout(io.StringIO()))
                    frames.main()
                    for operation in unexpected:
                        operation.assert_not_called()
                expected = dict(config, use_subfolder=enabled)
                self.assertEqual(frames.load_config(), expected)
                self.assertIn("framed subfolder" if enabled else "next to originals", stdout.getvalue())

    def test_bare_setup_still_runs_guided_setup(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", ["frames", "setup"]))
            stack.enter_context(mock.patch.object(sys.stdin, "isatty", return_value=True))
            stack.enter_context(mock.patch.object(frames.C, "enabled", False))
            guided = stack.enter_context(mock.patch.object(frames, "guided_setup", return_value=True))
            frames.main()
        guided.assert_called_once_with()
        self.assertFalse(self.config_file.exists())

    def test_bare_command_reports_invalid_config_without_traceback(self):
        config_file = self.root / ".config" / "frames" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("null", encoding="utf-8")
        env = dict(os.environ, HOME=str(self.root))
        process = subprocess.run(
            [sys.executable, str(FRAMES_PATH)],
            env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(process.returncode, 1)
        self.assertIn(str(config_file), process.stderr)
        self.assertIn("frames doctor", process.stderr)
        self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(config_file.read_text(encoding="utf-8"), "null")
        json_process = subprocess.run(
            [sys.executable, str(FRAMES_PATH), "--json"],
            env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(json_process.returncode, 0)
        self.assertEqual(json_process.stdout, "")
        self.assertEqual(json_process.stderr, "")

    def test_valid_config_round_trip_preserves_settings_and_extra_keys(self):
        config = {
            "assets_path": str(self.assets),
            "default_colors": {"iPhone 17 Pro": "Silver"},
            "use_subfolder": "mockups",
            "future_setting": [1, 2],
        }
        frames.save_config(config)
        self.assertEqual(frames.read_config_file(), (config, None))
        self.assertEqual(frames.resolve_assets_dir(), (self.assets, "config"))
        self.assertEqual(frames.get_subfolder_setting(Namespace()), "mockups")
        self.assertEqual(frames.get_color("iPhone 17 Pro Portrait", None, frames.load_config()["default_colors"]), "Silver")

    def test_missing_config_is_not_reported_as_an_error(self):
        self.assertEqual(frames.read_config_file(), (None, None))
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            frames.cmd_doctor(Namespace(assets=None, json=True))
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertFalse(result["config_present"])

    def test_doctor_reports_malformed_asset_metadata_without_crashing(self):
        version_file = self.assets / "version.txt"
        version_file.unlink()
        for content in (b"null", b"123", b"[]", b"\xff", b"{"):
            with self.subTest(metadata=content):
                (self.assets / "NewFrames.json").write_bytes(content)
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    frames.cmd_doctor(Namespace(assets=str(self.assets), json=True))
                result = json.loads(stdout.getvalue())
                self.assertFalse(result["ok"])
                self.assertTrue(any("do not look like Apple Frames 4" in issue for issue in result["issues"]))
        version_file.mkdir()
        (self.assets / "NewFrames.json").write_text("{}", encoding="utf-8")
        self.assertEqual(frames.check_assets_version(self.assets), (False, None))
        (self.assets / "NewFrames.json").unlink()
        (self.assets / "NewFrames.json").mkdir()
        self.assertEqual(frames.check_assets_version(self.assets), (False, None))

    def test_explicit_assets_override_invalid_config(self):
        self.config_file.write_text('{"assets_path": null}', encoding="utf-8")
        explicit = self.root / "explicit"
        self.assertEqual(frames.resolve_assets_dir(str(explicit)), (explicit, "--assets"))
        with mock.patch.dict(os.environ, {"FRAMES_ASSETS": str(explicit)}):
            self.assertEqual(frames.resolve_assets_dir(), (explicit, "FRAMES_ASSETS"))


class GlobalOptionTests(unittest.TestCase):
    def test_json_verbose_frame_keeps_diagnostics_off_stdout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = root / "assets"
            assets.mkdir()
            primary = "iPhone 17 Portrait"
            variant = "iPhone 17 Pro Portrait"
            dictionary = {
                "8": {"name": primary, "x": 1, "y": 1},
                "variants": {
                    variant: {"name": variant, "x": 1, "y": 1, "resizeWidth": 4, "mask": "yes"},
                },
            }
            (assets / "NewFrames.json").write_text(json.dumps(dictionary), encoding="utf-8")
            (assets / "version.txt").write_text("4", encoding="utf-8")
            Image.new("RGBA", (6, 8), (0, 0, 0, 0)).save(assets / (variant + ".png"))
            Image.new("RGBA", (4, 6), (255, 255, 255, 255)).save(assets / (variant + "_mask.png"))
            source = root / "shot.png"
            Image.new("RGB", (8, 12), "red").save(source)
            env = dict(os.environ, HOME=str(root), FRAMES_ASSETS=str(assets))
            process = subprocess.run(
                [sys.executable, str(FRAMES_PATH), "frame", "--json", "--verbose", str(source)],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["device"], variant)
            self.assertTrue(result["resized"])
            self.assertTrue(result["masked"])
            self.assertTrue(Path(result["output"]).is_file())
            for message in ("Variant resolved:", "Resized:", "Mask applied"):
                self.assertIn(message, process.stderr)

    def test_global_options_work_before_and_after_every_command(self):
        commands = {
            "frame": ["shot.png"], "video": ["clip.mov"],
            "video-info": ["clip.mov"], "list": [],
            "list-colors": ["iPhone"], "colors": [],
            "info": ["shot.png"], "setup": ["/tmp/assets"], "doctor": [],
        }
        options = ["--json", "--no-color", "-v", "--assets=/tmp/assets"]
        for command, operands in commands.items():
            for argv in (options + [command] + operands, [command] + options + operands):
                with self.subTest(argv=argv):
                    args = frames.build_parser().parse_args(argv)
                    self.assertTrue(args.json)
                    self.assertTrue(args.no_color)
                    self.assertTrue(args.verbose)
                    self.assertEqual(args.assets, "/tmp/assets")

    def test_mixed_global_options_keep_earlier_values_and_last_assets(self):
        args = frames.build_parser().parse_args([
            "--json", "--assets", "/tmp/first", "info", "--verbose",
            "--assets=/tmp/last", "--no-color", "shot.png",
        ])
        self.assertTrue(args.json)
        self.assertTrue(args.no_color)
        self.assertTrue(args.verbose)
        self.assertEqual(args.assets, "/tmp/last")
        self.assertEqual(args.files, ["shot.png"])

    def test_main_routes_default_frame_and_preserves_global_flags(self):
        invocations = [
            ["--json", "--assets=/tmp/assets", "--verbose", "shot.png"],
            ["--assets", "/tmp/assets", "-m", "--json", "--verbose", "shot.png"],
            ["shot.png", "--assets=/tmp/assets", "--json", "--verbose"],
            ["frame", "--assets", "/tmp/assets", "--json", "--verbose", "shot.png"],
        ]
        for argv in invocations:
            with self.subTest(argv=argv):
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(sys, "argv", ["frames"] + argv))
                    stack.enter_context(mock.patch.object(frames, "check_assets_version", return_value=(True, 4)))
                    stack.enter_context(mock.patch.object(frames.C, "enabled", False))
                    handler = stack.enter_context(mock.patch.object(frames, "cmd_frame"))
                    frames.main()
                args = handler.call_args[0][0]
                self.assertEqual(args.cmd, "frame")
                self.assertEqual(args.files, ["shot.png"])
                self.assertEqual(args.assets, "/tmp/assets")
                self.assertTrue(args.json)
                self.assertTrue(args.verbose)


if __name__ == "__main__":
    unittest.main()
