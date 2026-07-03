"""Application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import __app_name__
from .main_window import MainWindow


def main() -> int:
    QApplication.setApplicationName(__app_name__)
    QApplication.setOrganizationName(__app_name__)
    QApplication.setApplicationDisplayName(__app_name__)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # If a video path was passed on the command line, open it.
    for arg in sys.argv[1:]:
        if arg and not arg.startswith("-"):
            window.load_video(arg)
            break

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
