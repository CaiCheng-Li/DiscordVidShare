"""Target-size compression: bitrate math + a two-pass ffmpeg worker.

The public surface is:
  * compute_video_bitrate_bps(...) / estimate_output_bytes(...)  -- pure, testable.
  * EncodeJob                                                    -- parameters.
  * Encoder(QObject)                                             -- runs the two passes
    via QProcess and emits progress/finished/log signals.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, Signal

from . import ffmpeg_utils

# Container/mux overhead margin: aim a little under target so the final mp4 fits.
DEFAULT_SAFETY = 0.97
# Below this video bitrate the result looks rough; the UI warns the user.
LOW_BITRATE_FLOOR_BPS = 100_000

_LIB = {"h264": "libx264", "h265": "libx265"}


# --- pure bitrate math (no Qt, unit-testable) ---------------------------------

def compute_video_bitrate_bps(
    target_bytes: float,
    duration_s: float,
    audio_bitrate_bps: float = 0.0,
    safety: float = DEFAULT_SAFETY,
) -> int:
    """Video bitrate (bps) so that video+audio fit in target_bytes over duration_s."""
    if duration_s <= 0:
        return 0
    total_bits = target_bytes * 8 * safety
    audio_bits = audio_bitrate_bps * duration_s
    video_bits = total_bits - audio_bits
    return max(1, int(video_bits / duration_s))


def estimate_output_bytes(
    video_bitrate_bps: float,
    duration_s: float,
    audio_bitrate_bps: float = 0.0,
    safety: float = DEFAULT_SAFETY,
) -> int:
    """Inverse of compute_video_bitrate_bps: predicted file size in bytes."""
    total_bits = (video_bitrate_bps + audio_bitrate_bps) * duration_s
    return int(total_bits / (8 * safety))


# --- job parameters -----------------------------------------------------------

@dataclass
class EncodeJob:
    input_path: str
    output_path: str
    start: float                 # in-point, seconds
    duration: float              # length to encode, seconds
    target_bytes: int
    codec: str = "h264"          # 'h264' | 'h265'
    keep_audio: bool = True
    audio_kbps: int = 128
    scale_height: int | None = None   # None = keep source resolution
    preset: str = "medium"
    safety: float = DEFAULT_SAFETY

    @property
    def audio_bitrate_bps(self) -> int:
        return self.audio_kbps * 1000 if self.keep_audio else 0

    def video_bitrate_bps(self) -> int:
        return compute_video_bitrate_bps(
            self.target_bytes, self.duration, self.audio_bitrate_bps, self.safety
        )


# --- two-pass worker ----------------------------------------------------------

def _timecode_arg(seconds: float) -> str:
    return f"{max(0.0, seconds):.6f}"


class Encoder(QObject):
    """Runs a two-pass ffmpeg encode. Reusable for one job at a time."""

    progress = Signal(int, str)          # percent (0-100), stage label
    finished = Signal(bool, str)         # success, message
    log = Signal(str)                    # raw ffmpeg stderr lines

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._job: EncodeJob | None = None
        self._pass = 0
        self._tmpdir: str | None = None
        self._cancelled = False
        self._stderr_tail: list[str] = []

    # -- lifecycle -------------------------------------------------------------

    def start(self, job: EncodeJob) -> None:
        if self._proc is not None:
            raise RuntimeError("An encode is already running.")
        self._job = job
        self._cancelled = False
        self._stderr_tail = []
        self._tmpdir = tempfile.mkdtemp(prefix="dvs_pass_")
        self._run_pass(1)

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None:
            self._proc.kill()

    def is_running(self) -> bool:
        return self._proc is not None

    # -- pass execution --------------------------------------------------------

    def _run_pass(self, pass_no: int) -> None:
        assert self._job is not None and self._tmpdir is not None
        self._pass = pass_no
        args = self._build_args(self._job, pass_no)

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_pass_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc

        stage = "Pass 1 of 2 (analyzing)" if pass_no == 1 else "Pass 2 of 2 (encoding)"
        self.progress.emit(0 if pass_no == 1 else 50, stage)
        proc.start(ffmpeg_utils.discover_ffmpeg(), args)

    def _build_args(self, job: EncodeJob, pass_no: int) -> list[str]:
        lib = _LIB.get(job.codec, "libx264")
        vb = job.video_bitrate_bps()

        args = [
            "-y", "-hide_banner", "-nostdin",
            "-progress", "pipe:1", "-nostats",
            "-ss", _timecode_arg(job.start),
            "-i", job.input_path,
            "-t", _timecode_arg(job.duration),
            "-c:v", lib,
            "-b:v", str(vb),
            "-preset", job.preset,
            "-pix_fmt", "yuv420p",
        ]
        if job.scale_height:
            args += ["-vf", f"scale=-2:{job.scale_height}"]
        args += self._pass_args(pass_no)

        if pass_no == 1:
            args += ["-an", "-f", "null", os.devnull]
        else:
            if job.keep_audio:
                args += ["-c:a", "aac", "-b:a", f"{job.audio_kbps}k"]
            else:
                args += ["-an"]
            args += ["-movflags", "+faststart", job.output_path]
        return args

    def _pass_args(self, pass_no: int) -> list[str]:
        # ffmpeg's generic two-pass mechanism works for both libx264 and libx265;
        # it handles the x265 stats-path escaping internally (doing it by hand breaks
        # on Windows because ':' is the x265-params separator).
        assert self._tmpdir is not None
        log_base = os.path.join(self._tmpdir, "pl")
        return ["-pass", str(pass_no), "-passlogfile", log_base]

    # -- process callbacks -----------------------------------------------------

    def _on_stdout(self) -> None:
        if self._proc is None or self._job is None:
            return
        text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        out_time = None
        for line in text.splitlines():
            key, _, value = line.partition("=")
            if key == "out_time_us" and value.strip().isdigit():
                out_time = int(value) / 1_000_000
            elif key == "out_time_ms" and value.strip().isdigit() and out_time is None:
                out_time = int(value) / 1_000_000  # ffmpeg reports this in microseconds
        if out_time is None or self._job.duration <= 0:
            return
        frac = max(0.0, min(1.0, out_time / self._job.duration))
        base, span = (0, 50) if self._pass == 1 else (50, 50)
        self.progress.emit(int(base + frac * span), self._stage_label())

    def _stage_label(self) -> str:
        return "Pass 1 of 2 (analyzing)" if self._pass == 1 else "Pass 2 of 2 (encoding)"

    def _on_stderr(self) -> None:
        if self._proc is None:
            return
        text = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self._stderr_tail.append(line)
                self.log.emit(line)
        # Keep only the last lines for error reporting.
        if len(self._stderr_tail) > 40:
            self._stderr_tail = self._stderr_tail[-40:]

    def _on_error(self, _err: QProcess.ProcessError) -> None:
        # Handled in _on_pass_finished via exit status; nothing extra needed here.
        pass

    def _on_pass_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            proc.deleteLater()

        if self._cancelled:
            self._cleanup(remove_output=True)
            self.finished.emit(False, "Cancelled.")
            return

        crashed = exit_status == QProcess.ExitStatus.CrashExit
        if crashed or exit_code != 0:
            self._cleanup(remove_output=True)
            tail = "\n".join(self._stderr_tail[-8:]) or "ffmpeg exited unexpectedly."
            self.finished.emit(False, f"Encoding failed:\n{tail}")
            return

        if self._pass == 1:
            self._run_pass(2)
            return

        # Success.
        job = self._job
        self._cleanup(remove_output=False)
        size = None
        if job is not None and os.path.exists(job.output_path):
            size = os.path.getsize(job.output_path)
        self.progress.emit(100, "Done")
        msg = "Export complete."
        if size is not None:
            from .media_info import format_size
            msg = f"Export complete — {format_size(size)}."
        self.finished.emit(True, msg)

    def _cleanup(self, remove_output: bool) -> None:
        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._tmpdir = None
        if remove_output and self._job is not None:
            try:
                if os.path.exists(self._job.output_path):
                    os.remove(self._job.output_path)
            except OSError:
                pass
