import contextlib
import importlib.machinery
import importlib.util
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from PIL import Image


loader = importlib.machinery.SourceFileLoader(
    "frames_images", str(Path(__file__).resolve().parents[1] / "frames")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
frames = importlib.util.module_from_spec(spec)
loader.exec_module(frames)


class ImageTests(unittest.TestCase):
    def test_mask_replaces_alpha_with_red_without_changing_inputs(self):
        screenshot = Image.new("RGBA", (2, 1))
        screenshot.putdata([(20, 40, 60, 0), (80, 100, 120, 255)])
        mask = Image.new("RGBA", (2, 1))
        mask.putdata([(128, 0, 0, 255), (0, 255, 255, 255)])
        before = screenshot.tobytes(), mask.tobytes()

        result = frames.apply_mask(screenshot, mask)

        self.assertEqual(result.getpixel((0, 0)), (20, 40, 60, 128))
        self.assertEqual(result.getpixel((1, 0)), (80, 100, 120, 0))
        self.assertEqual((screenshot.tobytes(), mask.tobytes()), before)

    def test_merge_preserves_translucent_and_opaque_pixels(self):
        first = Image.new("RGBA", (2, 1))
        first.putdata([(200, 100, 50, 128), (10, 20, 30, 255)])
        second = Image.new("RGBA", (1, 3), (40, 80, 120, 64))

        merged = frames.merge_images([first, second], spacing=1)

        self.assertEqual(merged.size, (4, 3))
        self.assertEqual(merged.crop((0, 1, 2, 2)).tobytes(), first.tobytes())
        self.assertEqual(merged.crop((3, 0, 4, 3)).tobytes(), second.tobytes())
        self.assertEqual(merged.getpixel((2, 1)), (0, 0, 0, 0))

    def test_physical_merge_scales_and_bottom_aligns_without_changing_alpha(self):
        phone = Image.new("RGBA", (8, 12), (200, 100, 50, 128))
        tablet = Image.new("RGBA", (10, 18), (10, 20, 30, 255))

        merged = frames.merge_images([phone, tablet], spacing=1, physical_heights=[6, 18])

        self.assertEqual(merged.size, (15, 18))
        self.assertEqual(merged.getpixel((0, 11)), (0, 0, 0, 0))
        self.assertEqual(merged.crop((0, 12, 4, 18)).tobytes(), phone.resize((4, 6), Image.LANCZOS).tobytes())
        self.assertEqual(merged.crop((5, 0, 15, 18)).tobytes(), tablet.tobytes())

    def test_cached_assets_remain_unchanged_across_screenshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = Image.new("RGBA", (4, 4), (80, 40, 20, 128))
            frame.save(root / "Test.png")
            Image.new("RGBA", (2, 2), (128, 10, 20, 255)).save(root / "Test_mask.png")
            source = root / "screen.png"
            Image.new("RGBA", (2, 2), (10, 60, 120, 0)).save(source)
            devices = {"2": {"name": "Test", "x": "1", "y": "1", "mask": "yes"}}
            first, _ = frames.frame_screenshot(source, root, devices)
            Image.new("RGBA", (3, 3), (255, 0, 0, 255)).save(source)
            frames.frame_screenshot(source, root, devices, force_device="Test")
            Image.new("RGBA", (2, 2), (10, 60, 120, 0)).save(source)
            repeated, info = frames.frame_screenshot(source, root, devices)

            self.assertEqual(first.tobytes(), repeated.tobytes())
            self.assertEqual(repeated.getpixel((0, 0)), frame.getpixel((0, 0)))
            self.assertTrue(info["masked"])

    def test_batch_metadata_matches_each_written_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            devices = {
                "4": {"name": "Phone", "x": "2", "y": "2", "physicalHeight": 6},
                "6": {"name": "Tablet", "x": "2", "y": "3", "physicalHeight": 18},
            }
            (root / "NewFrames.json").write_text(json.dumps(devices), encoding="utf-8")
            for name, size in [("Phone", (8, 12)), ("Tablet", (10, 18))]:
                Image.new("RGBA", size, (10, 20, 30, 128)).save(root / (name + ".png"))
            phone, tablet = root / "phone-screen.png", root / "tablet-screen.png"
            Image.new("RGBA", (4, 8), (100, 120, 140, 255)).save(phone)
            Image.new("RGBA", (6, 12), (100, 120, 140, 255)).save(tablet)
            cases = [
                ([phone, phone, tablet, tablet], [(17, 12), (21, 18)], [None, None, None, None]),
                ([phone, tablet, phone, phone], [(15, 18), (17, 12)], [0.5, 1.0, None, None]),
            ]
            for paths, sizes, scales in cases:
                with self.subTest(paths=paths):
                    args = Namespace(
                        assets=str(root), files=[str(p) for p in paths], output=str(root / "out"),
                        batch=2, spacing=1, color=None, colors=None, device=None, verbose=False,
                        json=True, merge=False, no_scale=False, copy=False, subfolder=None,
                    )
                    output = io.StringIO()
                    with mock.patch.object(frames, "load_config", return_value={}):
                        with contextlib.redirect_stdout(output):
                            frames.cmd_frame(args)
                    data = json.loads(output.getvalue())
                    self.assertEqual([info.get("scale_factor") for info in data["frames"]], scales)
                    self.assertEqual([batch["count"] for batch in data["batches"]], [2, 2])
                    for batch, size in zip(data["batches"], sizes):
                        with Image.open(batch["merged"]) as image:
                            self.assertEqual(image.size, size)


if __name__ == "__main__":
    unittest.main()
