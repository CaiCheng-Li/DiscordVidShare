"""Build a standalone Windows executable for DiscordVidShare using PyInstaller.

Usage:
    python build_exe.py                 # build the .exe (relies on ffmpeg on PATH)
    python build_exe.py --bundle-ffmpeg # also copy ffmpeg.exe/ffprobe.exe into the build

The --bundle-ffmpeg flag makes a fully self-contained app (much larger). It looks for
ffmpeg/ffprobe on PATH and places them next to the executable; ffmpeg_utils.discover_*
checks the app directory first, so the bundled binaries are picked up automatically.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "DiscordVidShare"
ICON_NAME = "DVS_favicon.png"
ICO_NAME = "DVS_favicon.ico"   # multi-size exe icon; regenerate via scripts/make_ico.py
ROOT = Path(__file__).resolve().parent
# Absolute-import launcher: analysing the package's __main__.py directly leaves
# PySide6 out of the bundle (its relative import isn't followed as a script).
ENTRY = ROOT / "pyi_entry.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DiscordVidShare.exe")
    parser.add_argument(
        "--bundle-ffmpeg",
        action="store_true",
        help="Copy ffmpeg.exe/ffprobe.exe from PATH into the build (self-contained).",
    )
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: python -m pip install pyinstaller")
        return 1

    add_binaries: list[str] = []
    if args.bundle_ffmpeg:
        for tool in ("ffmpeg", "ffprobe"):
            path = shutil.which(tool)
            if not path:
                print(f"--bundle-ffmpeg: could not find {tool} on PATH.")
                return 1
            # PyInstaller --add-binary "src;dest" places the file at the app root ('.').
            add_binaries.append(f"{path}{__import__('os').pathsep}.")
            print(f"Bundling {tool}: {path}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT),
        "--collect-submodules",
        "discordvidshare",
        str(ENTRY),
    ]
    # Give the .exe its own Explorer/taskbar icon (needs a real .ico).
    ico = ROOT / ICO_NAME
    if ico.exists():
        cmd += ["--icon", str(ico)]
    else:
        print(f"Warning: {ICO_NAME} not found; run scripts/make_ico.py to create it.")
    # Bundle the PNG at the app root so _resource_path/setWindowIcon finds it at runtime.
    icon = ROOT / ICON_NAME
    if icon.exists():
        cmd += ["--add-data", f"{icon}{os.pathsep}."]
    else:
        print(f"Warning: {ICON_NAME} not found; building without a bundled icon.")
    for binary in add_binaries:
        cmd += ["--add-binary", binary]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode == 0:
        print(f"\nDone. Executable is in: {ROOT / 'dist' / APP_NAME}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
