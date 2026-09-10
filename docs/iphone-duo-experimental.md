# Experimental iPhone Duo frames

Frames 1.4.1 adds Apple's iPhone Duo bezels for developers testing mock screenshots and screen recordings at the announced display resolutions. Both displays work in portrait and landscape, in Night Sky and Star White. A separate manual choice shows the phone's back beside the outer display.

You need **Frames 1.4.1 or later and the separate Duo asset pack**. Updating the CLI alone does not download the new artwork. Duo remains opt-in: normal `frames setup` downloads the standard AppleFrames401.zip pack.

The source material is Apple's [technical specifications](https://www.apple.com/iphone-duo/specs/), [September 9 announcement](https://www.apple.com/newsroom/2026/09/apple-unveils-iphone-duo/), and [official design resources](https://developer.apple.com/design/resources/). The UI demos are original concepts, not screenshots of shipping iOS or proof of actual device capture dimensions.

## 1. Update Frames

Update using your existing [installation method](../README.md#installation). For an unmodified Git checkout, run `git pull --ff-only` inside the checkout. If you installed the single script directly, replace that script with the [1.4.1 version](https://raw.githubusercontent.com/viticci/frames-cli/1.4.1/frames) and keep it executable.

```bash
frames --version
```

This release prints `frames v1.4.1`. Python 3.8+ and Pillow are required. Video framing also requires ffmpeg 5.1+ and ffprobe 5.1+.

## 2. Download and extract the pack

Download [Frames-Duo-Experimental.zip](https://cdn.macstories.net/images/uploads/2026/09/09/frames-duo-experimental-1788997654596-a33ef863e7.zip) and extract it into a new folder. The ZIP is **95,246,128 bytes (95.2 MB)**. It contains a folder named `Frames-Duo-Experimental`, including all existing frames plus the Duo artwork.

For macOS or Linux, these commands download and extract it into a dedicated folder:

```bash
mkdir -p "$HOME/Downloads/Frames-Duo-1.4.1"
curl --fail --location \
  "https://cdn.macstories.net/images/uploads/2026/09/09/frames-duo-experimental-1788997654596-a33ef863e7.zip" \
  --output "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental.zip"
unzip "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental.zip" \
  -d "$HOME/Downloads/Frames-Duo-1.4.1"
```

You can instead use your browser and archive utility on any supported platform. The CDN URL has a generated filename, but the enclosed folder is always `Frames-Duo-Experimental`.

The expected SHA-256 for this ZIP is:

```text
36f64bcddeb97ae0e00e9abb91d79564aeaac284a2b479f6f6f87a5798ec4b83
```

On macOS, check it with `shasum -a 256 "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental.zip"`; on Linux, use `sha256sum` with the same path.

## 3. Select and verify the extracted folder

Use `--assets` to select the pack for one command. This does not change your saved asset folder:

```bash
frames --assets "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental" --json doctor
frames --assets "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental" list
frames --assets "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental" --json info /path/to/duo.png
frames --assets "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental" /path/to/duo.png
```

The doctor report identifies the selected folder, asset version **4**, and **519 PNGs**. Version 4 describes the asset format; it does not mean Duo is missing. A full `ok: true` report also requires working video tools. `list` shows four detected Duo views marked experimental and `iPhone Duo Outer Open` under manual frames. For a matching input, `info` reports the exact Duo device and `experimental: true`.

Both `--assets` and `frames setup PATH` require the **extracted local folder**, not the ZIP file or its CDN URL. The folder must directly contain `NewFrames.json`, `version.txt`, and the PNG files.

To make the pack your default, first use `frames --json doctor` to note your current `assets_path`, then run:

```bash
frames setup "$HOME/Downloads/Frames-Duo-1.4.1/Frames-Duo-Experimental"
frames --json doctor
```

Setup saves the folder in your Frames configuration. It retains your color and output-folder preferences, and the Duo pack includes the existing frames. You can now omit `--assets` in the examples below. Keep the selected folder available. If you want it elsewhere, move it before setup or run setup again with its new path. An existing `FRAMES_ASSETS` environment variable takes precedence over the saved path; update or unset that override if necessary.

To return to your previous pack, run `frames setup /path/to/your/previous/Frames`. If you used only `--assets`, no restore step is needed: your default never changed.

## 4. Choose a display, view, and finish

Frames detects the display and orientation from both input dimensions. Use screenshots at these exact sizes:

| Input width × height | Automatic frame |
| --- | --- |
| 1398 × 2034 | iPhone Duo Outer Portrait |
| 2034 × 1398 | iPhone Duo Outer Landscape |
| 1878 × 2670 | iPhone Duo Inner Portrait |
| 2670 × 1878 | iPhone Duo Inner Landscape |

The single outer screen is selected automatically. To choose between that view and the one showing the back of the phone, use the same **1398 × 2034** outer portrait screenshot with either device name:

```bash
# Outer screen only; this is also the automatic choice for this input size
frames --device "iPhone Duo Outer Portrait" outer-portrait.png

# Back of the phone on the left, outer screen on the right
frames --device "iPhone Duo Outer Open" outer-portrait.png
```

`--device` (or `-d`) selects a frame for the whole command. To export both views, run separate commands and use different output folders so both results are retained:

```bash
frames -d "iPhone Duo Outer Portrait" -o outer-screen outer-portrait.png
frames -d "iPhone Duo Outer Open" -o outer-and-back outer-portrait.png
```

Night Sky is the default finish unless you have saved another preference. All five views also support Star White:

```bash
frames --color "Star White" inner-landscape.png
frames --device "iPhone Duo Outer Open" --color "Star White" outer-portrait.png
frames --merge --colors "Star White,Night Sky" outer-portrait.png inner-landscape.png
```

Use the four native input sizes above. Frames scales inner screenshots to the larger openings in Apple's artwork automatically; do not enlarge them yourself or draw extra camera cutouts or side controls. Frames adds the bezel and screen mask, not concept interface elements.

## 5. Frame videos

The same pack, dimensions, colors, and device choices apply to `video` and `video-info`. These examples assume you saved the pack as your default; otherwise add `--assets /path/to/Frames-Duo-Experimental`:

```bash
frames --json video-info outer-recording.mp4
frames video --device "iPhone Duo Outer Portrait" -o outer-video outer-recording.mp4
frames video --device "iPhone Duo Outer Open" -o outer-and-back-video outer-recording.mp4
frames video --color "Star White" inner-recording.mp4
frames video --alpha inner-recording.mp4
```

Normal video export uses an opaque white canvas and preserves single-video audio. `--alpha` selects transparent ProRes MOV. See the [video guide](../README.md#video) for other export options, including HEVC-alpha on supported Macs.

## Geometry and provenance

| Exact input size | Device name | Screen offset | Artwork canvas | Rendered screen size |
| --- | --- | --- | --- | --- |
| 1398 × 2034 | iPhone Duo Outer Portrait | 88, 80 | 1574 × 2194 | 1398 × 2034 |
| 2034 × 1398 | iPhone Duo Outer Landscape | 80, 88 | 2194 × 1574 | 2034 × 1398 |
| 1878 × 2670 | iPhone Duo Inner Portrait | 120, 120 | 2247 × 3093 | 2007 × 2853 |
| 2670 × 1878 | iPhone Duo Inner Landscape | 120, 120 | 3093 × 2247 | 2853 × 2007 |
| 1398 × 2034, manual selection | iPhone Duo Outer Open | 1570, 80 | 3056 × 2194 | 1398 × 2034 |

All five views have Night Sky and Star White finishes. The outer open view displays the phone's rear hardware beside the outer screen. It shares the outer portrait resolution, so select it explicitly with `--device "iPhone Duo Outer Open"`.

The inner PNGs are larger than the announced native screen dimensions. The CLI scales the screenshot to the measured opening through `resizeWidth` and `resizeHeight`. Both orientations use transposed dimensions. The bezel pixels themselves remain unchanged. This small scale correction uses the artwork as supplied; it is an experimental mapping, pending actual hardware screenshots.

Masks follow the enclosed transparent openings in Apple's artwork. The outer camera stays in the bezel image. The masks also preserve the asymmetric corners of the closed device; they are not generic rounded rectangles. Image/video metadata includes `experimental: true` for these entries.

## Rebuild the assets

Download and open Apple's [iPhone Duo artwork disk image](https://devimages-cdn.apple.com/design/resources/download/Bezel-iPhone-Duo.dmg). Keep its `PNG` folder and `Apple Design Resources License.rtf` together. Use an existing Apple Frames 4 folder as the base. The output folder and ZIP must not exist.

```bash
python3 scripts/build_duo_assets.py \
  --source /path/to/Apple-Duo/PNG \
  --base-assets /path/to/Frames \
  --output /path/to/Frames-Duo-Experimental \
  --archive /path/to/Frames-Duo-Experimental.zip
```

The builder copies the base PNGs unchanged, adds ten Duo bezel PNGs and five masks, and extends `NewFrames.json` with four exact dimension matches and one manual view. It retains `version.txt`, which identifies the base asset format. `Duo-Experimental.json` records source URLs, hashes, geometry, optimization measurements, and the lack of real-device verification.

Descriptive text, XMP, EXIF, timestamps, and resolution metadata are removed. The builder chooses the smaller lossless encoding and verifies identical decoded RGBA pixels for every bezel. Color management chunks are preserved if present. No Photoshop files, disk image, Finder files, absolute paths, or user settings go into the ZIP. The ZIP uses fixed file order and timestamps.

The published pack uses the CDN download linked above. It does not replace AppleFrames401.zip. Apple's Design Resources License is retained inside the ZIP and governs the artwork; the repository's MIT license does not replace it. The builder can also produce the pack locally from a user's own Apple download.

## Verification

Run `python3 -m unittest discover -s tests -v` for the focused matching, color, resize, mask, and optimization checks, alongside the existing suite. For full artwork verification, build the pack, generate inputs at all four native resolutions, and frame each in both finishes. Also frame the outer portrait input using the manual rear view. Check decoded pixels, camera coverage, corner transparency, and a merged outer-portrait/inner-landscape pair. Those two views have the same stated physical height. Apple's differently padded canvases already align their device bodies when centered, so the image merger preserves their original sizes.

Test an inner portrait and landscape video when changing resize handling, because image and video paths both consume the explicit screen sizes. Keep published-resolution tests separate from actual device evidence. Real screenshots, Display Zoom modes, capture orientation metadata, and UI placement remain unverified until the device is available.
