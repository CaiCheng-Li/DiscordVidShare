"""A timeline widget: full-duration track with draggable In/Out handles + playhead.

Emits seconds-based signals. Frame snapping / 1-frame-minimum enforcement is the
caller's job (it owns the fps); this widget only keeps in < out by `min_gap`.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class _Drag(Enum):
    NONE = auto()
    IN = auto()
    OUT = auto()
    PLAYHEAD = auto()


class RangeSlider(QWidget):
    inChanged = Signal(float)         # user moved the In handle (seconds)
    outChanged = Signal(float)        # user moved the Out handle (seconds)
    playheadChanged = Signal(float)   # user scrubbed the playhead (seconds)

    _MARGIN = 8       # px reserved on each side for handle width
    _HANDLE_W = 8
    _GRAB_PX = 12     # click tolerance for grabbing a handle

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._in = 0.0
        self._out = 0.0
        self._pos = 0.0
        self._min_gap = 0.001
        self._drag = _Drag.NONE
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setEnabled(False)

    # -- public API ------------------------------------------------------------

    def set_duration(self, duration: float) -> None:
        self._duration = max(0.0, duration)
        self._in = 0.0
        self._out = self._duration
        self._pos = 0.0
        self.setEnabled(self._duration > 0)
        self.update()

    def set_min_gap(self, gap: float) -> None:
        self._min_gap = max(0.0, gap)

    def set_in(self, t: float) -> None:
        self._in = self._clamp(t, 0.0, max(0.0, self._out - self._min_gap))
        self.update()

    def set_out(self, t: float) -> None:
        self._out = self._clamp(t, min(self._duration, self._in + self._min_gap), self._duration)
        self.update()

    def set_playhead(self, t: float) -> None:
        self._pos = self._clamp(t, 0.0, self._duration)
        self.update()

    def in_point(self) -> float:
        return self._in

    def out_point(self) -> float:
        return self._out

    # -- geometry --------------------------------------------------------------

    def _usable_w(self) -> float:
        return max(1.0, self.width() - 2 * self._MARGIN)

    def _x_for(self, t: float) -> float:
        if self._duration <= 0:
            return float(self._MARGIN)
        return self._MARGIN + (t / self._duration) * self._usable_w()

    def _t_for(self, x: float) -> float:
        if self._duration <= 0:
            return 0.0
        return self._clamp((x - self._MARGIN) / self._usable_w() * self._duration,
                           0.0, self._duration)

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(v, hi))

    # -- interaction -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if not self.isEnabled() or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        d_in = abs(x - self._x_for(self._in))
        d_out = abs(x - self._x_for(self._out))

        if d_in <= self._GRAB_PX and d_in <= d_out:
            self._drag = _Drag.IN
        elif d_out <= self._GRAB_PX:
            self._drag = _Drag.OUT
        else:
            self._drag = _Drag.PLAYHEAD
            self._apply_playhead(x)
        self._apply_drag(x)

    def mouseMoveEvent(self, event) -> None:
        if self._drag == _Drag.NONE:
            # Hover cursor feedback over handles.
            if self.isEnabled():
                x = event.position().x()
                near = min(abs(x - self._x_for(self._in)), abs(x - self._x_for(self._out)))
                self.setCursor(Qt.CursorShape.SizeHorCursor if near <= self._GRAB_PX
                               else Qt.CursorShape.PointingHandCursor)
            return
        self._apply_drag(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        self._drag = _Drag.NONE

    def _apply_drag(self, x: float) -> None:
        if self._drag == _Drag.IN:
            self._in = self._clamp(self._t_for(x), 0.0, max(0.0, self._out - self._min_gap))
            self.inChanged.emit(self._in)
        elif self._drag == _Drag.OUT:
            self._out = self._clamp(self._t_for(x),
                                    min(self._duration, self._in + self._min_gap),
                                    self._duration)
            self.outChanged.emit(self._out)
        elif self._drag == _Drag.PLAYHEAD:
            self._apply_playhead(x)
        self.update()

    def _apply_playhead(self, x: float) -> None:
        self._pos = self._t_for(x)
        self.playheadChanged.emit(self._pos)

    # -- painting --------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()

        w, h = self.width(), self.height()
        track_h = 12
        track_top = (h - track_h) / 2
        track_rect = QRectF(self._MARGIN, track_top, w - 2 * self._MARGIN, track_h)

        # Base track.
        base = pal.mid().color() if self.isEnabled() else pal.window().color().darker(105)
        path = QPainterPath()
        path.addRoundedRect(track_rect, 5, 5)
        painter.fillPath(path, base)

        if self._duration > 0:
            x_in = self._x_for(self._in)
            x_out = self._x_for(self._out)

            # Selected region.
            sel_rect = QRectF(x_in, track_top, max(1.0, x_out - x_in), track_h)
            accent = pal.highlight().color()
            sel_path = QPainterPath()
            sel_path.addRoundedRect(sel_rect, 5, 5)
            painter.fillPath(sel_path, accent)

            # Playhead.
            x_pos = self._x_for(self._pos)
            playhead = QColor("#ff5252")
            painter.setPen(QPen(playhead, 2))
            painter.drawLine(QPointF(x_pos, track_top - 6), QPointF(x_pos, track_top + track_h + 6))
            painter.setBrush(playhead)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x_pos, track_top - 6), 3.5, 3.5)

            # In / Out handles.
            self._draw_handle(painter, x_in, track_top, track_h, pal)
            self._draw_handle(painter, x_out, track_top, track_h, pal)

    def _draw_handle(self, painter: QPainter, x: float, top: float, track_h: float, pal) -> None:
        hw = self._HANDLE_W
        rect = QRectF(x - hw / 2, top - 5, hw, track_h + 10)
        painter.setPen(QPen(pal.window().color(), 1))
        painter.setBrush(pal.highlight().color().darker(115))
        painter.drawRoundedRect(rect, 3, 3)
        # grip line
        painter.setPen(QPen(pal.brightText().color() if pal.window().color().lightness() < 128
                            else pal.window().color(), 1))
        cx = rect.center().x()
        painter.drawLine(QPointF(cx, top), QPointF(cx, top + track_h))
