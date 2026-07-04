"""Media metadata model plus frame/time helpers for frame-accurate trimming."""

from __future__ import annotations

from dataclasses import dataclass

# Container extensions the app will accept (open dialog + drag-and-drop). Lives here,
# in the Qt-free engine, so both the window and the preview widget can share one list.
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv",
              ".mpg", ".mpeg", ".ts"}


@dataclass(frozen=True)
class MediaInfo:
    """Facts about a source video, derived from ffprobe."""

    path: str
    duration: float           # seconds
    fps: float                # frames per second (may be fractional, e.g. 29.97)
    width: int
    height: int
    file_size: int            # bytes
    has_audio: bool
    v_codec: str = ""
    a_codec: str = ""
    bit_rate: int = 0         # source overall bitrate in bps (0 if unknown)

    @property
    def frame_count(self) -> int:
        """Total number of frames (best estimate)."""
        return max(1, round(self.duration * self.fps))

    @property
    def frame_duration(self) -> float:
        """Length of a single frame in seconds."""
        return 1.0 / self.fps if self.fps > 0 else 0.0

    # --- frame <-> time mapping ------------------------------------------------

    def time_to_frame(self, t: float) -> int:
        """Nearest frame index for a time in seconds, clamped to the clip."""
        frame = round(t * self.fps)
        return max(0, min(frame, self.frame_count - 1))

    def frame_to_time(self, frame: int) -> float:
        """Start time (seconds) of a frame index, clamped to the clip."""
        frame = max(0, min(frame, self.frame_count - 1))
        return frame * self.frame_duration


def format_timecode(seconds: float, show_ms: bool = True) -> str:
    """Format seconds as HH:MM:SS.mmm (or HH:MM:SS)."""
    seconds = max(0.0, seconds)
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    if show_ms:
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_timecode(text: str) -> float | None:
    """Parse HH:MM:SS.mmm / MM:SS / SS(.mmm) into seconds. Returns None if invalid."""
    text = text.strip()
    if not text:
        return None
    try:
        parts = text.split(":")
        if len(parts) > 3:
            return None
        parts = [float(p) for p in parts]
        seconds = 0.0
        for value in parts:            # left-to-right: H, M, S (variable length)
            seconds = seconds * 60 + value
        return seconds if seconds >= 0 else None
    except ValueError:
        return None


def format_size(num_bytes: float) -> str:
    """Human-readable byte size using binary units."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"
