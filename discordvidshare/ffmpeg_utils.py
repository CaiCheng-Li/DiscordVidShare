"""Locate ffmpeg/ffprobe and probe media files."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .media_info import MediaInfo

# Hide the console window that would otherwise flash when we run ffprobe/ffmpeg
# from a windowed (GUI) app on Windows.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# User-overridable paths (set by the UI via QSettings, wired in main_window).
_ffmpeg_override: str | None = None
_ffprobe_override: str | None = None


class FFmpegNotFound(RuntimeError):
    """Raised when ffmpeg or ffprobe cannot be located."""


def set_overrides(ffmpeg: str | None, ffprobe: str | None) -> None:
    global _ffmpeg_override, _ffprobe_override
    _ffmpeg_override = ffmpeg or None
    _ffprobe_override = ffprobe or None


def _bundled_dirs() -> list[Path]:
    """Directories to search for a bundled ffmpeg/ffprobe.

    Covers PyInstaller layouts: `sys._MEIPASS` (onefile extraction dir / onedir
    _internal) and the executable's own directory, plus the source-tree root.
    """
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
        dirs.append(Path(sys.executable).resolve().parent)
    else:
        dirs.append(Path(__file__).resolve().parent.parent)
    return dirs


def _discover(tool: str, override: str | None) -> str:
    """Resolve a tool path: override -> bundled next to app -> PATH."""
    if override and Path(override).exists():
        return override
    exe = f"{tool}.exe" if sys.platform == "win32" else tool
    for d in _bundled_dirs():
        candidate = d / exe
        if candidate.exists():
            return str(candidate)
    found = shutil.which(tool)
    if found:
        return found
    raise FFmpegNotFound(
        f"Could not find {tool}. Install FFmpeg and add it to PATH, place "
        f"{exe} next to the app, or set its path in the app."
    )


def discover_ffmpeg() -> str:
    return _discover("ffmpeg", _ffmpeg_override)


def discover_ffprobe() -> str:
    return _discover("ffprobe", _ffprobe_override)


def ffmpeg_available() -> bool:
    try:
        discover_ffmpeg()
        discover_ffprobe()
        return True
    except FFmpegNotFound:
        return False


def child_env() -> dict | None:
    """Environment for spawning ffmpeg/ffprobe. None means "inherit unchanged".

    In a PyInstaller build the frozen process has its bundle dirs (which hold Qt's
    own ffmpeg DLLs plus a specific UCRT) prepended to PATH. Handing that PATH to the
    bundled ffmpeg/ffprobe can make them resolve the wrong DLLs and fail. Strip those
    bundle dirs so the child uses normal system library resolution.
    """
    if not getattr(sys, "frozen", False):
        return None
    env = os.environ.copy()
    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(os.path.normcase(os.path.abspath(meipass)))
    roots.append(os.path.normcase(os.path.abspath(os.path.dirname(sys.executable))))

    kept: list[str] = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        norm = os.path.normcase(os.path.abspath(entry))
        if any(norm == r or norm.startswith(r + os.sep) for r in roots):
            continue
        kept.append(entry)
    env["PATH"] = os.pathsep.join(kept)
    return env


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        env=child_env(),
    )


def _parse_fraction(text: str, default: float = 0.0) -> float:
    """Parse ffprobe fractions like '30000/1001' into a float."""
    if not text or text in ("0/0", "N/A"):
        return default
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            num_f, den_f = float(num), float(den)
            return num_f / den_f if den_f else default
        except ValueError:
            return default
    try:
        return float(text)
    except ValueError:
        return default


def probe(path: str) -> MediaInfo:
    """Run ffprobe and return a MediaInfo. Raises on failure."""
    ffprobe = discover_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not proc.stdout.strip():
        detail = proc.stderr.strip() or (
            f"(no stderr; exit code {proc.returncode}, {len(proc.stdout)} bytes stdout)"
        )
        raise RuntimeError(f"ffprobe could not read the file:\n{detail}")

    data = json.loads(proc.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v_stream is None:
        raise RuntimeError("No video stream found in this file.")

    # Duration: prefer container, fall back to the video stream.
    duration = _parse_fraction(str(fmt.get("duration", "")), 0.0)
    if duration <= 0:
        duration = _parse_fraction(str(v_stream.get("duration", "")), 0.0)

    # Frame rate: avg_frame_rate is usually the honest one; r_frame_rate as fallback.
    fps = _parse_fraction(str(v_stream.get("avg_frame_rate", "")), 0.0)
    if fps <= 0:
        fps = _parse_fraction(str(v_stream.get("r_frame_rate", "")), 0.0)
    if fps <= 0:
        fps = 30.0  # last-resort default so the UI still functions

    try:
        file_size = int(fmt.get("size") or os.path.getsize(path))
    except (OSError, ValueError):
        file_size = 0

    try:
        bit_rate = int(fmt.get("bit_rate") or 0)
    except ValueError:
        bit_rate = 0

    return MediaInfo(
        path=path,
        duration=duration,
        fps=fps,
        width=int(v_stream.get("width") or 0),
        height=int(v_stream.get("height") or 0),
        file_size=file_size,
        has_audio=a_stream is not None,
        v_codec=str(v_stream.get("codec_name", "")),
        a_codec=str(a_stream.get("codec_name", "")) if a_stream else "",
        bit_rate=bit_rate,
    )


def extract_frame(input_path: str, time_s: float, out_path: str) -> None:
    """Save a single full-resolution frame at time_s to out_path (PNG/JPG)."""
    ffmpeg = discover_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{time_s:.6f}",
        "-i", input_path,
        "-frames:v", "1",
        "-q:v", "2",
        out_path,
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(f"Frame extraction failed:\n{proc.stderr.strip()}")
