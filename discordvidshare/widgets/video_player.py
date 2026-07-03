"""Video preview wrapper around QMediaPlayer + QVideoWidget.

Exposes a seconds-based API and frame stepping. The actual export/extraction is done
by ffmpeg (see ffmpeg_utils), so results are correct even when the Qt backend cannot
preview a given codec inline.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from .. import ffmpeg_utils


class VideoPlayer(QWidget):
    positionChanged = Signal(float)    # seconds
    durationChanged = Signal(float)    # seconds
    playingChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fps = 30.0
        self._source_path: str | None = None

        self._video = QVideoWidget(self)
        self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video.setMinimumSize(320, 180)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video)

    # -- loading ---------------------------------------------------------------

    def load(self, path: str, fps: float) -> None:
        self._source_path = path
        self._fps = fps if fps > 0 else 30.0
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
