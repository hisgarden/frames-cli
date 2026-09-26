"""Optional macOS proof of HEVC auxiliary alpha using Apple's native decoder."""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


FRAMES_PATH = Path(__file__).resolve().parents[1] / "frames"
loader = importlib.machinery.SourceFileLoader("frames_hevc_alpha_native_tests", str(FRAMES_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
frames = importlib.util.module_from_spec(spec)
loader.exec_module(frames)

# Writes the first frame's decoded alpha plane as a PGM. Asking AVFoundation for
# BGRA instead would add Apple's display conversion, which rounds opaque alpha
# down to 254 on macOS 27 even for a perfectly encoded stream.
SWIFT_DECODER = """
import Foundation
import AVFoundation
import CoreVideo

let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let reader = try AVAssetReader(asset: asset)
let output = AVAssetReaderTrackOutput(track: asset.tracks(withMediaType: .video)[0], outputSettings: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8VideoRange_8A_TriPlanar,
])
reader.add(output)
guard reader.startReading(), let sample = output.copyNextSampleBuffer(),
      let buffer = CMSampleBufferGetImageBuffer(sample) else {
    fatalError("Could not decode the first frame: \\(String(describing: reader.error))")
}
CVPixelBufferLockBaseAddress(buffer, .readOnly)
let alphaPlane = 2
let width = CVPixelBufferGetWidthOfPlane(buffer, alphaPlane)
let height = CVPixelBufferGetHeightOfPlane(buffer, alphaPlane)
let stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, alphaPlane)
let base = CVPixelBufferGetBaseAddressOfPlane(buffer, alphaPlane)!.assumingMemoryBound(to: UInt8.self)
var data = Data("P5\\n\\(width) \\(height)\\n255\\n".utf8)
for y in 0..<height { data.append(base + y * stride, count: width) }
try data.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
"""


@unittest.skipUnless(
    sys.platform == "darwin" and all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe", "swiftc")),
    "macOS, ffmpeg, ffprobe, and swiftc are required for native HEVC alpha verification",
)
class NativeHEVCAlphaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            frames.require_ffmpeg_tools()
            frames._require_hevc_alpha_support()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        swift_version = subprocess.run(["swiftc", "--version"], capture_output=True, text=True, timeout=30)
        if swift_version.returncode:
            raise unittest.SkipTest("The installed swiftc command is unavailable")
        cls.tempdir = tempfile.TemporaryDirectory(prefix="frames-native-alpha-test-")
        cls.addClassCleanup(cls.tempdir.cleanup)
        cls.root = Path(cls.tempdir.name)
        decoder_source = cls.root / "decode.swift"
        decoder_source.write_text(SWIFT_DECODER, encoding="utf-8")
        cls.decoder = cls.root / "decode"
        subprocess.run(
            ["swiftc", "-module-cache-path", str(cls.root / "swift-cache"), str(decoder_source), "-o", str(cls.decoder)],
            check=True, capture_output=True, text=True, timeout=60,
        )

    def test_native_decoded_alpha_preserves_masks_geometry_and_background(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "version.txt").write_text("4", encoding="utf-8")
        (assets / "NewFrames.json").write_text(json.dumps({
            "24": {"name": "Test", "x": 2, "y": 2, "mask": "yes", "physicalHeight": 100},
        }), encoding="utf-8")
        frame = Image.new("RGBA", (29, 53), (0, 0, 0, 0))
        frame.putpixel((0, 25), (100, 100, 100, 96))
        frame.putpixel((28, 25), (100, 100, 100, 128))
        frame.save(assets / "Test.png")
        mask = Image.new("L", (24, 48), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 23, 47), radius=5, fill=255)
        for x, alpha in ((5, 64), (6, 128), (7, 192)):
            mask.putpixel((x, 0), alpha)
        mask.save(assets / "Test_mask.png")

        # Compute reference alpha independently of the CLI's ffmpeg filters.
        masked_screen = Image.new("RGBA", mask.size, "white")
        masked_screen.putalpha(mask)
        reference = Image.new("RGBA", frame.size)
        reference.paste(masked_screen, (2, 2))
        frame_alpha = Image.alpha_composite(reference, frame).getchannel("A")
        source = self.root / "source.mov"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=red:s=24x48:r=10:d=0.3", "-c:v", "rawvideo", "-pix_fmt", "uyvy422", str(source),
        ], check=True, capture_output=True, text=True, timeout=30)
        env = dict(os.environ, HOME=str(self.root), FRAMES_ASSETS=str(assets))

        for name, merge, background in (("single", False, None), ("merged", True, None), ("black", True, "black")):
            with self.subTest(export=name):
                output = self.root / (name + ".mov")
                command = [sys.executable, str(FRAMES_PATH), "--json", "--assets", str(assets),
                           "video", "--codec", "hevc-alpha", "--preset", "compact", "--strip-audio",
                           "--output", str(output)]
                if merge:
                    command += ["--merge", "--spacing", "5"]
                if background:
                    command += ["--background", background]
                command += [str(source)] * (2 if merge else 1)
                completed = subprocess.run(command, env=env, check=True, capture_output=True, text=True, timeout=30)
                metadata = json.loads(completed.stdout)
                self.assertEqual(metadata["output_codec"], "hevc-alpha")
                decoded = self.root / (name + ".pgm")
                subprocess.run([str(self.decoder), str(output), str(decoded)],
                               check=True, capture_output=True, text=True, timeout=30)
                size = (64, 54) if merge else (30, 54)
                expected = Image.new("L", size, 255 if background == "black" else 0)
                if background is None:
                    expected.paste(frame_alpha, (0, 0))
                    if merge:
                        expected.paste(frame_alpha, (34, 0))
                with Image.open(decoded) as actual_alpha:
                    self.assertEqual(actual_alpha.size, size)
                    self.assertEqual(ImageChops.difference(actual_alpha, expected).getextrema(), (0, 0),
                                     "Native HEVC alpha differs from the expected mask, frame, spacing, or padding")


if __name__ == "__main__":
    unittest.main()
