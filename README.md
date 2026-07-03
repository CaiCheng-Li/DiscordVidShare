# DiscordVidShare

A small Windows 10/11 desktop app to **trim a video clip and compress it to a target file
size** — built for getting clips under upload limits (e.g. Discord's 10 / 25 / 50 / 500 MB
tiers).

- Load `mp4`, `mov`, `mkv`, `avi`, `webm`, and more (drag-and-drop or **Open**).
- Live preview with a draggable timeline: set **In**/**Out** points, step frame-by-frame,
  down to a **1-frame** minimum selection.
- **Extract Frame** button saves the current frame as a full-resolution PNG/JPG.
- Pick a **target size** (custom or a Discord preset); the app computes the bitrate and uses
  **two-pass FFmpeg** encoding so the result reliably lands near that size.
- H.264 (default, plays inline in Discord) or H.265; optional downscale to 720p/480p to keep
  quality up at small sizes.

## Requirements

- **Windows 10/11**, **Python 3.9+**.
- **FFmpeg + FFprobe** on your `PATH` (or set their location in the **File** menu). Get a
  build from <https://www.gyan.dev/ffmpeg/builds/> or `winget install Gyan.FFmpeg`.

## Run from source

Double-click **`run.bat`** (it creates a local virtual environment, installs PySide6 on first
run, and launches the app). Or manually:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m discordvidshare
```

## Build a standalone .exe

```bat
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python build_exe.py                 REM relies on ffmpeg on PATH
.venv\Scripts\python build_exe.py --bundle-ffmpeg  REM self-contained (larger)
```

The executable is written to `dist\DiscordVidShare\`.

## How the size targeting works

For a selection of length `D` seconds and a target of `S` bytes:

```
video_bitrate ≈ (S · 8 · 0.97 − audio_bitrate · D) / D
```

The `0.97` leaves headroom for container overhead so the file fits. Two-pass encoding lets
FFmpeg distribute that bitrate budget across the whole clip for accurate sizing. If a target
is too small for the clip length, the app warns you and suggests a shorter clip or a lower
resolution.

## Tests

```bat
.venv\Scripts\python tests\test_encoder_math.py
```

## Project layout

```
discordvidshare/
  ffmpeg_utils.py   ffmpeg/ffprobe discovery + probing + frame extraction
  media_info.py     MediaInfo model, frame<->time helpers, timecode formatting
  encoder.py        bitrate math + two-pass QProcess worker (progress/cancel)
  main_window.py    the GUI: open, trim, export
  widgets/
    range_slider.py timeline with draggable In/Out handles + playhead
    video_player.py QMediaPlayer/QVideoWidget preview wrapper
```
