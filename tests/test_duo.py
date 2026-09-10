import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace

from PIL import Image, ImageDraw, PngImagePlugin


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


frames = load_module("frames_duo", ROOT / "frames")
builder = load_module("build_duo", ROOT / "scripts/build_duo_assets.py")


class DuoTests(unittest.TestCase):
    def test_list_shows_installed_duo_views_and_manual_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "NewFrames.json"
            catalog_path.write_text(json.dumps(builder.catalog_entries()), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                frames.cmd_list(Namespace(assets=str(root)))
            listing = output.getvalue()
            for name in (view["name"] for view in builder.VIEWS):
                self.assertIn(name, listing)
            self.assertIn("experimental", listing)
            self.assertIn("select with --device", listing)
            catalog_path.write_text('{"variants": {}}', encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                frames.cmd_list(Namespace(assets=str(root)))
            self.assertNotIn("iPhone Duo", output.getvalue())

    def test_native_resolutions_require_both_dimensions(self):
        catalog = builder.catalog_entries()
        expected = {
            (1398, 2034): "iPhone Duo Outer Portrait",
            (2034, 1398): "iPhone Duo Outer Landscape",
            (1878, 2670): "iPhone Duo Inner Portrait",
            (2670, 1878): "iPhone Duo Inner Landscape",
        }
        for (width, height), name in expected.items():
            with self.subTest(name=name):
                entry, detected = frames.detect_device_size(width, height, catalog)
                self.assertEqual(detected, name)
                self.assertTrue(entry["experimental"])
                self.assertEqual(frames.detect_device_size(width, height + 1, catalog), (None, None))
                self.assertEqual(frames.get_color(name, "star white", strict=True), "Star White")
                self.assertEqual(frames.get_color(name, None), "Night Sky")
        manual = frames.resolve_device_entry(1398, 2034, catalog, force_device="iPhone Duo Outer Open")
        self.assertEqual((manual[0]["x"], manual[0]["y"]), ("1570", "80"))
        self.assertEqual(frames.get_color(manual[1], "2", strict=True), "Star White")

    def test_explicit_inner_resize_matches_image_and_video_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "iPhone Duo Inner Landscape"
            Image.new("RGBA", (15, 11)).save(root / (name + " Night Sky.png"))
            Image.new("L", (11, 7), 255).save(root / (name + "_mask.png"))
            source = root / "native.png"
            Image.new("RGB", (8, 6), "red").save(source)
            entry = {"name": name, "x": "2", "y": "2", "colors": "yes", "mask": "yes",
                     "resizeWidth": "11", "resizeHeight": "7", "experimental": True}
            catalog = {"8": {"overlap": {"6": entry}}}
            image, info = frames.frame_screenshot(source, root, catalog)
            self.assertEqual(image.getchannel("A").getbbox(), (2, 2, 13, 9))
            self.assertEqual(image.getpixel((12, 8)), (255, 0, 0, 255))
            self.assertTrue(info["experimental"])
            self.assertTrue(info["resized"])
            metadata = frames.resolve_frame_metadata(8, 6, root, catalog)
            self.assertEqual((metadata["resize_width"], metadata["resize_height"]), (11, 7))
            self.assertTrue(metadata["experimental"])
            entry.pop("resizeHeight")
            legacy = frames.resolve_frame_metadata(8, 6, root, catalog)
            self.assertEqual(legacy["resize_height"], 8)

    def test_mask_uses_enclosed_opening_and_preserves_partial_bezel_alpha(self):
        image = Image.new("RGBA", (16, 12))
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, 13, 9), fill=(30, 40, 50, 255))
        draw.rectangle((4, 4, 11, 7), fill=(0, 0, 0, 0))
        image.putpixel((4, 4), (30, 40, 50, 128))
        image.putpixel((8, 4), (0, 0, 0, 255))  # Opaque camera.
        mask = builder.screen_mask(image, (4, 4, 12, 8))
        screen = frames.apply_mask(Image.new("RGBA", (8, 4), "white"), mask.convert("RGBA"))
        result = frames.composite(screen, image, 4, 4)
        self.assertEqual(result.getpixel((4, 4))[3], 255)
        self.assertEqual(result.getpixel((8, 4)), (0, 0, 0, 255))
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        with self.assertRaisesRegex(ValueError, "opening changed"):
            builder.screen_mask(image, (3, 4, 12, 8))

    def test_optimization_strips_metadata_without_changing_rgba(self):
        image = Image.new("RGBA", (20, 20), (10, 70, 90, 128))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "unused metadata " * 1000)
        source = io.BytesIO()
        image.save(source, "PNG", pnginfo=metadata, dpi=(300, 300))
        optimized = builder.optimize_png(source.getvalue(), image)
        self.assertLess(len(optimized), len(source.getvalue()))
        with Image.open(io.BytesIO(optimized)) as decoded:
            self.assertEqual(decoded.tobytes(), image.tobytes())
            self.assertNotIn("Comment", decoded.info)
            self.assertNotIn("dpi", decoded.info)


if __name__ == "__main__":
    unittest.main()
