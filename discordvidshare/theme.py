"""Dark 'Discord blurple' theme — Fusion palette + Qt stylesheet.

The whole look is pulled from ``DVS_favicon.ico``: a blurple→indigo gradient tile
with a white film-strip 'D' + play triangle, periwinkle scissors, and a light 'S'.
Since the app exists to get clips under Discord's upload limits, it wears Discord's
own dark, blurple-accented look. One hue (indigo-tinted neutral) across every
surface — only lightness shifts — and blurple is the single accent, spent sparingly
on the export CTA and the timeline selection.

Presentation only: no engine imports, so the media/encoder code stays Qt-free.
"""

from __future__ import annotations

import os
import tempfile
from string import Template

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# -- tokens ------------------------------------------------------------------
# Surfaces: single hue, lightness-only steps (base → panel → elevated). Inputs
# sit *below* their panel (darker) so they read as inset "type here" wells.
CANVAS = "#1E1F22"          # window base — the darkest night
SURFACE = "#2B2D31"         # panels / cards
ELEVATED = "#313338"        # menus, tooltips, hovered rows, combo popups
INPUT_BG = "#1A1B1E"        # inputs — inset, a hair darker than canvas
TRACK = "#4E5058"           # empty timeline groove / neutral fill

BTN = "#383A40"             # secondary button — gently raised on any surface
BTN_HOVER = "#41434A"

BORDER = "#3A3C42"          # whisper edge — visible on canvas and panel alike
BORDER_STRONG = "#4A4D55"   # hovered input / emphasis

BRAND = "#5865F2"           # Discord blurple — the icon's gradient
BRAND_HOVER = "#4752C4"
BRAND_ACTIVE = "#3C45A5"
BRAND_DISABLED = "#363A5E"
PERIWINKLE = "#9BA0F7"      # the icon's scissors + 'S'

TEXT = "#F2F3F5"            # primary
TEXT_SECOND = "#C7CBD1"     # secondary
TEXT_MUTED = "#949BA4"      # tertiary / metadata
TEXT_DISABLED = "#5C6067"

SUCCESS = "#23A55A"         # Discord green
WARNING = "#F0B232"         # Discord yellow — low-bitrate caution
DANGER = "#F23F43"          # Discord red — playhead + destructive

WHITE = "#FFFFFF"

_TOKENS = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str)}

# A white tick, drawn on top of the checked indicator's blurple fill. QSS can't
# take a `data:` URI, so it has to live as a real file referenced by url(); we
# write it to a temp path at stylesheet-build time. viewBox is inset inside the
# 16px indicator so the check keeps a hair of margin.
_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
    'viewBox="0 0 14 14">'
    '<path d="M3 7.3 L5.7 10 L11 4.3" fill="none" stroke="#FFFFFF" '
    'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def _checkmark_url() -> str:
    """Write the tick SVG to a temp file and return a QSS-friendly (forward-slash)
    path. Returns '' if the write fails — the checkbox then falls back to a plain
    blurple fill, so a read-only temp dir is a cosmetic loss, not a crash."""
    try:
        path = os.path.join(tempfile.gettempdir(), "dvs_check.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_CHECK_SVG)
        return path.replace("\\", "/")
    except OSError:
        return ""


def build_palette() -> QPalette:
    """A dark Fusion palette. The custom-painted timeline reads these roles
    directly (Highlight → blurple selection, Mid → track), so the palette and
    the stylesheet have to agree."""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(CANVAS))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(INPUT_BG))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(BTN))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.BrightText, QColor(WHITE))
    p.setColor(QPalette.ColorRole.Highlight, QColor(BRAND))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(WHITE))
    p.setColor(QPalette.ColorRole.Mid, QColor(TRACK))
    p.setColor(QPalette.ColorRole.Dark, QColor("#141517"))
    p.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(ELEVATED))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    p.setColor(QPalette.ColorRole.Link, QColor(PERIWINKLE))

    for role, col in (
        (QPalette.ColorRole.WindowText, TEXT_DISABLED),
        (QPalette.ColorRole.Text, TEXT_DISABLED),
        (QPalette.ColorRole.ButtonText, TEXT_DISABLED),
        (QPalette.ColorRole.Highlight, "#33353B"),
        (QPalette.ColorRole.HighlightedText, TEXT_DISABLED),
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(col))
    return p


_QSS = Template(
    """
* { outline: 0; }

QWidget { color: $TEXT_SECOND; font-size: 13px; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QLabel:disabled, QCheckBox:disabled { color: $TEXT_DISABLED; }

QMainWindow, #CentralWidget, QDialog, QMessageBox { background: $CANVAS; }

QToolTip {
    background: $ELEVATED; color: $TEXT;
    border: 1px solid $BORDER; border-radius: 6px; padding: 5px 8px;
}

/* --- identity labels ------------------------------------------------- */
#InfoLabel   { color: $TEXT_MUTED; }
#SelLabel    { color: $TEXT_MUTED; }
#ExtLabel    { color: $TEXT_MUTED; padding: 0 4px; }
#TimeLabel   { color: $TEXT_SECOND; font-family: "Cascadia Mono","Consolas",monospace; font-size: 13px; }

/* --- panels ---------------------------------------------------------- */
QGroupBox {
    background: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 8px;
    margin-top: 16px;
    color: $TEXT_MUTED;
    font-size: 11px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 8px; top: 0px; padding: 0 2px 6px 2px; background: transparent;
}

/* --- video frame ----------------------------------------------------- */
#VideoPanel { background: #000000; border: 1px solid $BORDER; border-radius: 8px; }

/* --- buttons --------------------------------------------------------- */
QPushButton {
    background: $BTN; color: $TEXT;
    border: 1px solid $BORDER; border-radius: 6px;
    padding: 7px 14px; font-weight: 500;
}
QPushButton:hover  { background: $BTN_HOVER; border-color: $BORDER_STRONG; }
QPushButton:pressed{ background: $CANVAS; }
QPushButton:disabled { background: $SURFACE; color: $TEXT_DISABLED; border-color: $BORDER; }
QPushButton#Transport { padding: 6px; }

QPushButton#Primary {
    background: $BRAND; color: $WHITE; border: 0;
    border-radius: 6px; padding: 10px 18px; font-size: 14px; font-weight: 600;
}
QPushButton#Primary:hover   { background: $BRAND_HOVER; }
QPushButton#Primary:pressed { background: $BRAND_ACTIVE; }
QPushButton#Primary:disabled{ background: $BRAND_DISABLED; color: #A9ADD6; }

/* --- inputs ---------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $INPUT_BG; color: $TEXT;
    border: 1px solid $BORDER; border-radius: 6px;
    padding: 6px 8px; min-height: 18px;
    selection-background-color: $BRAND; selection-color: $WHITE;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: $BORDER_STRONG; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $BRAND; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background: $CANVAS; color: $TEXT_DISABLED; border-color: $BORDER;
}
#Timecode { font-family: "Cascadia Mono","Consolas",monospace; }

QComboBox::drop-down { border: 0; width: 22px; }
QComboBox::down-arrow {
    image: none; width: 0; height: 0; margin-right: 9px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid $TEXT_MUTED;
}
QComboBox:hover::down-arrow { border-top-color: $TEXT; }
QComboBox QAbstractItemView {
    background: $ELEVATED; color: $TEXT;
    border: 1px solid $BORDER; border-radius: 6px; padding: 4px; outline: 0;
    selection-background-color: $BRAND; selection-color: $WHITE;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: 0; border-top-right-radius: 6px; background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: 0; border-bottom-right-radius: 6px; background: transparent;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $ELEVATED; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid $TEXT_MUTED;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid $TEXT_MUTED;
}

/* --- checkbox -------------------------------------------------------- */
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid $BORDER_STRONG; background: $INPUT_BG;
}
QCheckBox::indicator:hover { border-color: $BRAND; }
QCheckBox::indicator:checked {
    background: $BRAND; border-color: $BRAND; $CHECK_RULE
}
QCheckBox::indicator:checked:disabled {
    background: $BRAND_DISABLED; border-color: $BRAND_DISABLED; $CHECK_RULE
}
QCheckBox::indicator:unchecked:disabled { border-color: $BORDER; background: $CANVAS; }

/* --- progress -------------------------------------------------------- */
QProgressBar {
    background: $INPUT_BG; border: 1px solid $BORDER; border-radius: 6px;
    text-align: center; color: $TEXT_SECOND; font-size: 12px; font-weight: 600;
    min-height: 22px;
}
QProgressBar::chunk { background: $BRAND; border-radius: 5px; margin: 1px; }

/* --- menu / status --------------------------------------------------- */
QMenuBar { background: $CANVAS; color: $TEXT_SECOND; border-bottom: 1px solid $BORDER; }
QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: $ELEVATED; color: $TEXT; }
QMenu {
    background: $ELEVATED; color: $TEXT_SECOND;
    border: 1px solid $BORDER; border-radius: 8px; padding: 4px;
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; }
QMenu::item:selected { background: $BRAND; color: $WHITE; }
QMenu::separator { height: 1px; background: $BORDER; margin: 4px 8px; }

QStatusBar { background: $CANVAS; color: $TEXT_MUTED; border-top: 1px solid $BORDER; }
QStatusBar::item { border: 0; }
QStatusBar QLabel { color: $TEXT_MUTED; }

/* --- scrollbars (dialogs / combo popups) ----------------------------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $BTN_HOVER; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: $TRACK; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
)


def stylesheet() -> str:
    url = _checkmark_url()
    tokens = dict(_TOKENS)
    tokens["CHECK_RULE"] = f"image: url({url});" if url else ""
    return _QSS.substitute(tokens)


def apply(app: QApplication) -> None:
    """Install the theme: Fusion base (so palette drives every widget),
    the dark palette, a Segoe UI baseline, and the stylesheet on top."""
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setFont(QFont("Segoe UI"))
    app.setStyleSheet(stylesheet())
