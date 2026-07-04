"""Application bootstrap."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__
from .main_window import MainWindow

_ICON_NAME = "DVS_favicon.png"


def _resource_path(name: str) -> str | None:
    """Locate a bundled data file. Mirrors ffmpeg_utils' discovery: `sys._MEIPASS`
    (PyInstaller onefile/onedir) and the exe dir when frozen, else the source-tree
    root. Returns None if the file isn't found."""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
        dirs.append(Path(sys.executable).resolve().parent)
    else:
        dirs.append(Path(__file__).resolve().parent.parent)
    for d in dirs:
        candidate = d / name
        if candidate.exists():
            return str(candidate)
    return None


def _run_selftest(rest: list[str]) -> int:
    """Headless diagnostic: resolve ffmpeg/ffprobe and optionally probe a file.

    Runs without starting the GUI. Writes a report to %TEMP%/dvs_selftest.txt and
    returns 0 on success, 1 on failure. Useful for confirming FFmpeg setup — for a
    frozen build this exercises the exact bundled-binary discovery path.
    """
    from . import ffmpeg_utils

    media = next((a for a in rest if not a.startswith("-")), None)
    lines: list[str] = [f"{__app_name__} self-test", f"frozen={getattr(sys, 'frozen', False)}"]
    ok = True
    try:
        lines.append(f"ffmpeg:  {ffmpeg_utils.discover_ffmpeg()}")
        lines.append(f"ffprobe: {ffmpeg_utils.discover_ffprobe()}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(f"discovery FAILED: {exc}")

    if ok and media:
        # Raw subprocess diagnostic (exposes exit code / stderr the frozen build sees).
        import subprocess
        try:
            raw = subprocess.run(
                [ffmpeg_utils.discover_ffprobe(), "-v", "error", "-print_format", "json",
                 "-show_format", media],
                capture_output=True, text=True,
                creationflags=ffmpeg_utils.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, env=ffmpeg_utils.child_env(),
            )
            lines.append(f"raw ffprobe: rc={raw.returncode} out={len(raw.stdout)}B "
                         f"err={len(raw.stderr)}B err_head={raw.stderr[:200]!r}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"raw ffprobe RAISED: {exc!r}")
        lines.append(f"PATH_head={os.environ.get('PATH', '')[:150]}")

        try:
            info = ffmpeg_utils.probe(media)
            lines.append(f"probe OK: {info.width}x{info.height} @ {info.fps:.3f}fps, "
                         f"{info.duration:.2f}s, audio={info.has_audio}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            lines.append(f"probe FAILED: {exc}")

    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    report = os.path.join(tempfile.gettempdir(), "dvs_selftest.txt")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


def main() -> int:
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return _run_selftest([a for a in argv if a != "--selftest"])

    QApplication.setApplicationName(__app_name__)
    QApplication.setOrganizationName(__app_name__)
    QApplication.setApplicationDisplayName(__app_name__)

    # Give Windows an explicit AppUserModelID so the taskbar shows our own icon
    # (and groups under the app) instead of falling back to the host python.exe.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"{__app_name__}.{__version__}"
            )
        except Exception:  # noqa: BLE001 — cosmetic only; never block startup
            pass

    app = QApplication(sys.argv)
    from . import theme
    theme.apply(app)
    icon_path = _resource_path(_ICON_NAME)
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()

    # If a video path was passed on the command line, open it.
    for arg in argv:
        if arg and not arg.startswith("-"):
            window.load_video(arg)
            break

    # First-launch tutorial (no-op after it's been seen). Deferred so the window
    # is painted behind the modal dialog before it appears.
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, window.run_first_launch)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
