# Changelog

## 1.4.0 — 2026-09-08

Frames adds Apple device bezels to screenshots and screen recordings from the command line. Version 1.4.0 adds compressed video with transparency through an optional HEVC-alpha export mode on macOS. It also improves video merging, image transparency, output file handling, and scripting reliability.

### Compressed transparent video

- Added `frames video --codec hevc-alpha` for transparent HEVC-with-alpha MOV exports. This provides a smaller delivery format for compatible Apple apps and devices.
- Supports single videos, simultaneous merges, and sequential merges with `--playback-offset`, including device masks, rotation, per-input colors, and scaling by physical size.
- Defaults to a transparent canvas. An explicit `--background white`, `--background black`, or `--background "#RRGGBB"` overrides the whole canvas, including padding.
- Uses `.mov` filenames automatically. Explicit output files must also use `.mov`.
- Supports the existing size/quality presets with these HEVC-alpha bitrate targets:

| Preset | Target bitrate |
| --- | --- |
| `compact` | 4 Mbps |
| `balanced` | 7 Mbps |
| `best` (default) | 10 Mbps |

These are encoder bitrate targets, not file-size guarantees. Lower presets trade image detail for smaller files. HEVC-alpha rejects `--quality`; use `--preset` instead.

```bash
# Transparent HEVC MOV at the default best preset
frames video --codec hevc-alpha recording.mp4

# Smaller transparent export
frames video --codec hevc-alpha --preset compact recording.mp4

# Transparent side-by-side merge
frames video -m --codec hevc-alpha first.mp4 second.mp4

# Transparent merge with sequential playback
frames video -m --playback-offset --codec hevc-alpha first.mp4 second.mp4
```

HEVC-alpha requires macOS and an FFmpeg build with HEVC alpha support through VideoToolbox, Apple's video encoding framework. Frames checks alpha-encoder support before rendering. Unsupported configurations produce an error; Frames does not silently substitute opaque HEVC or ProRes. The receiving app must support HEVC with alpha.

HEVC-alpha output uses even encoded dimensions. Individual exports pad the device frame when necessary. Merges keep each device's original frame geometry for physical scaling and pad only the final canvas. Padding uses the selected background.

### File size example

Before release, a 20.27-second iPhone recording was framed at 1350 × 2760 pixels with its original audio:

| Export | File size |
| --- | --- |
| ProRes 4444 with transparency | 3.70 GB |
| HEVC-alpha, `best` | 30.3 MB |
| HEVC-alpha, `balanced` | 22.8 MB |
| HEVC-alpha, `compact` | 15.8 MB |

Sizes use decimal units and describe this recording, not a guaranteed compression ratio. Apple's native decoder verified that sampled transparency matched exactly for every HEVC-alpha preset. Copied audio packets matched the source.

### Existing export behavior

- The default H.264 MP4 still has a white canvas outside the device bezel. Use `--background` to choose another color.
- `--alpha` and `--background transparent` still select ProRes 4444 MOV unless `--codec hevc-alpha` is explicitly selected. `--alpha --codec hevc` also remains ProRes.
- ProRes is an editing and compositing format that can produce much larger files than the source recording. Its large size is expected, and `--preset compact` does not change ProRes encoding settings.
- Plain `--codec hevc` still creates opaque HEVC MP4. Select `--codec hevc-alpha` for compressed transparency.
- Single-video exports preserve audio unless `--strip-audio` is passed. Sequential merges concatenate audio and provide silence for inputs without audio. Simultaneous merges continue to omit mixed audio.

### Video rendering and output files

- Video merges now frame and combine their sources in one FFmpeg operation. This removes the temporary encoded video for each input and the extra encoding pass.
- Direct merges retain device masks, transparent spacing, bottom alignment, and sequential playback holds for future and completed videos.
- Video metadata inspection reads frame-image headers without decoding and caching full frame images.
- Fixed a progress-reporting stall that could occur when FFmpeg produced enough diagnostic output to fill its error pipe. Error details remain available, and interrupted renders stop the child process.
- When an output refers to an input file, including through a symbolic or hard link, rendering uses a temporary destination and replaces the output only after success. Failed renders preserve the original input.
- Multiple individual exports reject paths that would overwrite another input or send distinct inputs to the same output filename before any rendering begins.
- Source-size and savings reports use the original input sizes, including when an export replaces an input.

### Image framing

- Fixed merged images applying transparency twice. Partly transparent bezel pixels now retain their original alpha and color values.
- Reduced retained frame/mask images and avoided unnecessary image copies to limit memory use during repeated framing.
- Corrected batch-merge JSON so each frame's `scale_factor` describes the batch that was actually written.

### Command-line and configuration fixes

- Global `--json`, `--assets`, `--verbose`/`-v`, and `--no-color` options now work before or after every command without discarding earlier values.
- Verbose device, resize, and mask diagnostics go to standard error, keeping JSON on standard output parseable.
- Invalid configuration produces an actionable error that identifies the configuration file. Saved settings are no longer silently ignored. `frames doctor` remains usable to diagnose the problem.
- `frames setup --subfolder` and `frames setup --no-subfolder`, when used without an asset path, update only the saved output preference. They no longer enter interactive setup or check video dependencies.
- Asset checks handle unreadable version files and malformed metadata more reliably.

### JSON, documentation, and validation

- Added `output_codec` to rendered-video JSON for individual exports, merged output, and each merged input. Values are `h264`, `hevc`, `prores`, or `hevc-alpha`; the existing per-input `codec` field still describes the source.
- Documented HEVC-alpha merge geometry: per-input `output_dimensions` describes the original framed tile with `padded: false`; top-level `dimensions` describes the final encoded canvas.
- Updated the README, agent skill, CLI help, and splash with export recipes, format tradeoffs, configuration behavior, and JSON guidance.
- Documented native alpha verification. `ffprobe` and software HEVC decoders can expose only the opaque base layer; that alone does not show whether an HEVC-alpha file contains transparency.
- All 82 tests passed on Python 3.8 and 3.14, with no skipped tests on the verification Mac. The complete CLI and all six test modules compiled under CPython 3.8 through 3.14.
- Added an optional macOS regression test that decodes real HEVC-alpha exports with AVFoundation and checks masks, partly transparent pixels, merged geometry, and opaque padding. It requires FFmpeg, ffprobe, and a working Swift compiler, and skips when those prerequisites are unavailable.
- Verified all ten help pages, the splash, real screenshot and video exports, native transparency, audio preservation, rotation, both merge playback modes, and the installed CLI and skill.

Thanks to @iTwenty for the report and use case in [issue #5](https://github.com/viticci/frames-cli/issues/5).

[Full comparison with 1.3.2](https://github.com/viticci/frames-cli/compare/1.3.2...1.4.0)
