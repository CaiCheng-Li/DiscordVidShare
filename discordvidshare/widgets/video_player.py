"""Video preview wrapper around QMediaPlayer + QVideoWidget.

Exposes a seconds-based API and frame stepping. The actual export/extraction is done
by ffmpeg (see ffmpeg_utils), so results are correct even when the Qt backend cannot
preview a given codec inline.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QLabel, QSizePolicy, QStackedLayout, QStyle, QVBoxLayout, QWidget,
)

from .. import ffmpeg_utils
from ..media_info import VIDEO_EXTS
from ..theme import BORDER, BRAND, TEXT, TEXT_MUTED, TEXT_SECOND


class VideoPlayer(QWidget):
    positionChanged = Signal(float)    # seconds
    durationChanged = Signal(float)    # seconds
    playingChanged = Signal(bool)
    fileDropped = Signal(str)          # a video file dropped onto the preview

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fps = 30.0
        self._source_path: str | None = None

        self._video = QVideoWidget(self)
        self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video.setMinimumSize(320, 180)

        # Drops over the preview must replace the open clip. But QVideoWidget renders into
        # an internal child widget that fills the whole area and grabs the drag events, so
        # they never reach MainWindow or a filter on QVideoWidget alone. Make the video
        # widget *and* its child surface(s) drop targets that funnel to fileDropped;
        # ChildAdded keeps that true if the surface is (re)created after a clip loads.
        self.setAcceptDrops(True)
        self._watch_for_drops(self._video)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        # Show a "drop a video here" placeholder instead of a black screen until a clip
        # is loaded, then swap the (native) video surface in. One page visible at a time
        # keeps the native window from covering the placeholder.
        self._placeholder = self._build_placeholder()
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._video)
        self._stack.setCurrentWidget(self._placeholder)

    # -- empty-state placeholder -----------------------------------------------

    @staticmethod
    def _placeholder_qss(active: bool) -> str:
        border = BRAND if active else BORDER
        bg = "rgba(88, 101, 242, 0.10)" if active else "transparent"
        title = TEXT if active else TEXT_SECOND
        body = TEXT_SECOND if active else TEXT_MUTED
        return f"""
            #VideoPlaceholder {{
                background: {bg}; border: 2px dashed {border};
                border-radius: 12px; margin: 16px;
            }}
            #VideoPlaceholder QLabel {{ background: transparent; color: {body}; }}
            #VideoPlaceholder QLabel#PlaceholderTitle {{
                color: {title}; font-size: 16px; font-weight: 600;
            }}
        """

    def _build_placeholder(self) -> QWidget:
        w = QWidget()
        w.setObjectName("VideoPlaceholder")
        w.setStyleSheet(self._placeholder_qss(False))

        app_icon = QApplication.windowIcon()
        pix = (app_icon.pixmap(72, 72) if not app_icon.isNull()
               else self.style().standardIcon(
                   QStyle.StandardPixmap.SP_DialogOpenButton).pixmap(72, 72))
        icon = QLabel()
        icon.setPixmap(pix)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Drag & drop a video here")
        title.setObjectName("PlaceholderTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("or use  Open Video…  to browse")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(icon)
        lay.addSpacing(14)
        lay.addWidget(title)
        lay.addSpacing(4)
        lay.addWidget(subtitle)
        lay.addStretch(1)
        return w

    def _set_drag_highlight(self, on: bool) -> None:
        self._placeholder.setStyleSheet(self._placeholder_qss(on))

    # -- loading ---------------------------------------------------------------

    def load(self, path: str, fps: float) -> None:
        self._source_path = path
        self._fps = fps if fps > 0 else 30.0
        self._set_drag_highlight(False)
        self._stack.setCurrentWidget(self._video)   # swap out the placeholder
        self._watch_for_drops(self._video)          # (re)cover the render surface
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.pause()

    def source_path(self) -> str | None:
        return self._source_path

    # -- transport -------------------------------------------------------------

    def toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def seek(self, seconds: float) -> None:
        self._player.setPosition(max(0, int(round(seconds * 1000))))

    def position(self) -> float:
        return self._player.position() / 1000.0

    def duration(self) -> float:
        return self._player.duration() / 1000.0

    def set_volume(self, value_0_1: float) -> None:
        self._audio.setVolume(max(0.0, min(1.0, value_0_1)))

    def step_frames(self, delta: int) -> None:
        """Move by delta frames and pause on that frame."""
        self._player.pause()
        frame_ms = 1000.0 / self._fps
        new_ms = self._player.position() + delta * frame_ms
        new_ms = max(0, min(int(round(new_ms)), self._player.duration()))
        self._player.setPosition(new_ms)

    def extract_frame(self, out_path: str) -> None:
        """Save the current frame at full resolution via ffmpeg."""
        if not self._source_path:
            raise RuntimeError("No video loaded.")
        ffmpeg_utils.extract_frame(self._source_path, self.position(), out_path)

    # -- signal relays ---------------------------------------------------------

    def _on_position(self, ms: int) -> None:
        self.positionChanged.emit(ms / 1000.0)

    def _on_duration(self, ms: int) -> None:
        self.durationChanged.emit(ms / 1000.0)

    def _on_state(self, _state) -> None:
        self.playingChanged.emit(self.is_playing())

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        # Land on the first frame once loaded so the preview isn't blank.
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._player.setPosition(0)

    # -- drag & drop over the (native) preview ---------------------------------

    @staticmethod
    def _dropped_video(mime) -> str | None:
        """First local video-file path in a mime payload, else None."""
        for url in mime.urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTS:
                return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._dropped_video(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_highlight(True)   # light up the drop zone

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._dropped_video(event.mimeData()):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_highlight(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag_highlight(False)
        path = self._dropped_video(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)

    def _watch_for_drops(self, widget: QWidget) -> None:
        """Make widget (and its current descendants) drop targets routed to fileDropped."""
        for w in (widget, *widget.findChildren(QWidget)):
            w.setAcceptDrops(True)
            w.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # Relay drags/drops Qt delivers to the video widget or its internal render surface.
        et = event.type()
        if et == QEvent.Type.ChildAdded:
            # The render surface can be created after load — keep drops working on it.
            child = event.child()
            if isinstance(child, QWidget):
                self._watch_for_drops(child)
        elif et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._dropped_video(event.mimeData()):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Type.Drop:
            path = self._dropped_video(event.mimeData())
            if path:
                event.acceptProposedAction()
                self.fileDropped.emit(path)
                return True
        return super().eventFilter(obj, event)
