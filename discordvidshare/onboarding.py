"""First-launch tutorial + optional desktop-shortcut creation.

Two user-facing pieces, both GUI-side (no engine imports):

* ``WelcomeDialog`` — a short, themed walkthrough shown once on first launch and
  re-openable from Help. Its final step asks whether to drop a desktop shortcut, and
  skipping the tour still offers one (via a confirm prompt) rather than silently exiting.
* ``create_desktop_shortcut`` — writes a ``.lnk`` with no extra dependencies by
  driving PowerShell's ``WScript.Shell`` COM object. The script is handed over as a
  base64 ``-EncodedCommand`` so paths with spaces/quotes (e.g. "Caicheng Li") can't
  corrupt it.

Whether the tutorial has been seen is kept in ``QSettings`` under
``onboarding/completed_version`` — the same store the rest of the app writes to.
It records the app *version* that completed the tour (not a one-shot flag) so a
fresh install or an update re-runs the walkthrough; see ``should_show_tutorial``.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import __app_name__, __version__, theme

# Records the app version whose tutorial was completed/skipped. Keying to the
# version (rather than a plain bool) is deliberate: the flag lives in the HKCU
# registry, which outlives an uninstall/reinstall, so a one-shot bool would
# suppress the tour on every future install. Comparing against the running
# version instead re-runs it on a fresh install or an update.
_VERSION_KEY = "onboarding/completed_version"
_LEGACY_KEY = "onboarding/completed"  # pre-1.1 one-shot bool; still written for old builds
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# (badge number implied by order, title, body). Body allows a little rich text.
_STEPS: list[tuple[str, str]] = [
    (
        "Compress clips to fit",
        "DiscordVidShare trims a video and re-encodes it to a target file size, so a "
        "clip drops under Discord's 10, 25, 50, or 500&nbsp;MB limits without guesswork.",
    ),
    (
        "Open a video",
        "Click <b>Open Video</b> or drag a file straight onto the window. "
        "MP4, MOV, MKV, WebM and more are all supported.",
    ),
    (
        "Trim to the moment",
        "Drag the <b>In</b> and <b>Out</b> handles on the timeline, or press "
        "<b>Set In</b> / <b>Set Out</b> at the playhead. The frame-step buttons "
        "nudge one frame at a time for a clean cut.",
    ),
    (
        "Hit your target size",
        "Pick a preset or type a size, choose a codec, then <b>Compress&nbsp;&amp;&nbsp;"
        "Export</b>. Two-pass encoding lands the file at — or just under — your limit.",
    ),
    (
        "You're all set",
        "That's the whole flow. Want a quick way back in next time?",
    ),
]


# -- first-run gate ----------------------------------------------------------

def should_show_tutorial(settings: QSettings) -> bool:
    """True until the tutorial has been completed/skipped for the current version.

    Shows on a fresh install (no stored version) and again after an update, but
    stays quiet on ordinary relaunches of the same build."""
    return settings.value(_VERSION_KEY, "", str) != __version__


def mark_tutorial_seen(settings: QSettings) -> None:
    settings.setValue(_VERSION_KEY, __version__)
    settings.setValue(_LEGACY_KEY, True)  # keep the old flag truthy for downgrades


# -- desktop shortcut --------------------------------------------------------

def _launch_target() -> tuple[str, str, str, str]:
    """(target, arguments, working_dir, icon_location) for the shortcut.

    Frozen: point at our own ``.exe`` (the build embeds the icon). From source:
    launch the package with this interpreter's windowed ``pythonw`` and use the
    ``.ico`` if we can find it."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, "", str(Path(exe).parent), f"{exe},0"

    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    launcher = str(pyw if pyw.exists() else py)
    root = Path(__file__).resolve().parent.parent

    icon = launcher
    try:  # reuse the app's resource discovery; imported lazily to dodge a cycle
        from .app import _resource_path

        found = _resource_path("DVS_favicon.ico") or _resource_path("DVS_favicon.png")
        if found:
            icon = f"{found},0"
    except Exception:  # noqa: BLE001 — icon is cosmetic; never block the shortcut
        pass
    return launcher, "-m discordvidshare", str(root), icon


def _ps_quote(value: str) -> str:
    """Quote a string as a PowerShell single-quoted literal ('' escapes a quote)."""
    return "'" + value.replace("'", "''") + "'"


def create_desktop_shortcut() -> tuple[bool, str]:
    """Create/refresh a desktop ``.lnk``. Returns (ok, path-or-error-message)."""
    if os.name != "nt":
        return False, "Desktop shortcuts are only supported on Windows."

    desktop = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DesktopLocation
    )
    if not desktop:
        return False, "Could not locate the Desktop folder."

    lnk = str(Path(desktop) / f"{__app_name__}.lnk")
    target, args, workdir, icon = _launch_target()

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(lnk) + ")\n"
        "$s.TargetPath = " + _ps_quote(target) + "\n"
        "$s.Arguments = " + _ps_quote(args) + "\n"
        "$s.WorkingDirectory = " + _ps_quote(workdir) + "\n"
        "$s.IconLocation = " + _ps_quote(icon) + "\n"
        "$s.Description = 'Trim and compress video clips to fit upload limits'\n"
        "$s.Save()\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=25,
            creationflags=_CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run PowerShell: {exc}"

    if proc.returncode != 0 or not Path(lnk).exists():
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, detail or "PowerShell could not create the shortcut."
    return True, lnk


# -- the dialog --------------------------------------------------------------

class WelcomeDialog(QDialog):
    """A short first-run walkthrough. The last step offers a desktop shortcut.

    When ``first_run`` is set, completing *or* dismissing the dialog records that
    the tutorial has been seen, so it won't reappear on the next launch.
    """

    def __init__(self, parent: QWidget | None, settings: QSettings,
                 first_run: bool) -> None:
        super().__init__(parent)
        self._settings = settings
        self._first_run = first_run
        self._index = 0

        self.setWindowTitle(f"Welcome to {__app_name__}")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._build()
        self._show_step(0)
        if first_run:
            self.finished.connect(lambda _r: mark_tutorial_seen(self._settings))

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(28, 22, 28, 8)
        self._stack = QStackedWidget()
        for i, (title, text) in enumerate(_STEPS):
            self._stack.addWidget(self._build_page(i, title, text))
        self._stack.setCurrentIndex(0)
        body_lay.addWidget(self._stack)
        root.addWidget(body, 1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("WelcomeHeader")
        header.setStyleSheet(
            f"#WelcomeHeader {{ background: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.BORDER}; }}"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(28, 18, 28, 18)
        lay.setSpacing(12)

        icon = QLabel()
        pix = self._app_pixmap()
        if pix is not None:
            icon.setPixmap(pix)
        lay.addWidget(icon)

        title = QLabel(__app_name__)
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 17px; font-weight: 700;"
        )
        lay.addWidget(title)
        lay.addStretch(1)

        tag = QLabel("Getting started")
        tag.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        lay.addWidget(tag)
        return header

    def _build_page(self, index: int, title: str, text: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        badge = QLabel(str(index + 1))
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {theme.BRAND}; color: {theme.WHITE}; "
            f"border-radius: 15px; font-size: 14px; font-weight: 700;"
        )
        head.addWidget(badge)
        heading = QLabel(title)
        heading.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 19px; font-weight: 700;"
        )
        head.addWidget(heading)
        head.addStretch(1)
        lay.addLayout(head)

        body = QLabel(text)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {theme.TEXT_SECOND}; font-size: 14px; line-height: 20px;"
        )
        body.setMinimumHeight(72)
        lay.addWidget(body)

        # The final step carries the shortcut opt-in.
        if index == len(_STEPS) - 1:
            self._shortcut_check = QCheckBox("Create a desktop shortcut")
            self._shortcut_check.setChecked(True)
            lay.addWidget(self._shortcut_check)

        lay.addStretch(1)
        return page

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(28, 8, 24, 18)
        lay.setSpacing(8)

        self._dots = [QLabel("●") for _ in _STEPS]
        for dot in self._dots:
            dot.setStyleSheet(f"color: {theme.BORDER_STRONG}; font-size: 11px;")
            lay.addWidget(dot)
        lay.addStretch(1)

        self._skip_btn = QPushButton("Skip tour")
        self._skip_btn.clicked.connect(self._skip)
        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(lambda: self._show_step(self._index - 1))
        self._next_btn = QPushButton("Next")
        self._next_btn.setObjectName("Primary")
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self._on_next)
        for b in (self._skip_btn, self._back_btn, self._next_btn):
            lay.addWidget(b)
        return footer

    # -- navigation --------------------------------------------------------

    def _show_step(self, index: int) -> None:
        self._index = max(0, min(index, len(_STEPS) - 1))
        self._stack.setCurrentIndex(self._index)
        last = self._index == len(_STEPS) - 1
        for i, dot in enumerate(self._dots):
            color = theme.BRAND if i == self._index else theme.BORDER_STRONG
            dot.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._back_btn.setEnabled(self._index > 0)
        self._skip_btn.setVisible(not last)
        self._next_btn.setText("Finish" if last else "Next")

    def _on_next(self) -> None:
        if self._index < len(_STEPS) - 1:
            self._show_step(self._index + 1)
        else:
            self._finish()

    def _skip(self) -> None:
        # Skipping the tour still offers the shortcut (the checkbox on the final step is
        # never seen otherwise), so ask outright before closing.
        resp = QMessageBox.question(
            self, "Create a desktop shortcut?",
            f"Add a desktop shortcut for {__app_name__} so it's quick to open next time?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._make_shortcut()
        self.accept()

    def _finish(self) -> None:
        # Reached via "Finish" on the final step, where the checkbox opts in.
        if self._index == len(_STEPS) - 1 and self._shortcut_check.isChecked():
            self._make_shortcut()
        self.accept()

    def _make_shortcut(self) -> None:
        ok, detail = create_desktop_shortcut()
        parent = self.parent()
        if ok and parent is not None and hasattr(parent, "statusBar"):
            parent.statusBar().showMessage("Desktop shortcut created.", 5000)
        elif not ok:
            QMessageBox.warning(self, "Shortcut not created", detail)

    # -- helpers -----------------------------------------------------------

    def _app_pixmap(self) -> QPixmap | None:
        try:
            from .app import _resource_path

            path = _resource_path("DVS_favicon.png") or _resource_path("DVS_favicon.ico")
        except Exception:  # noqa: BLE001
            path = None
        if not path:
            return None
        pix = QPixmap(path)
        if pix.isNull():
            return None
        return pix.scaledToHeight(
            30, Qt.TransformationMode.SmoothTransformation
        )
