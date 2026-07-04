"""Main application window: open, trim, and compress-to-size."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QStyle, QVBoxLayout, QWidget,
)

from . import __app_name__, ffmpeg_utils
from .encoder import LOW_BITRATE_FLOOR_BPS, EncodeJob, Encoder, compute_video_bitrate_bps
from .media_info import VIDEO_EXTS, MediaInfo, format_size, format_timecode, parse_timecode
from .widgets.range_slider import RangeSlider
from .widgets.video_player import VideoPlayer

VIDEO_FILTER = (
    "Video files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.mpg *.mpeg *.ts);;"
    "All files (*.*)"
)

# (label, megabytes) — Discord's common upload tiers plus a couple of extras.
SIZE_PRESETS = [
    ("Custom", None),
    ("Discord free (10 MB)", 10),
    ("25 MB", 25),
    ("Discord Nitro Basic (50 MB)", 50),
    ("100 MB", 100),
    ("Discord Nitro (500 MB)", 500),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(__app_name__)
        self.resize(940, 760)
        self.setAcceptDrops(True)

        self.settings = QSettings()
        self.info: MediaInfo | None = None
        self.encoder: Encoder | None = None
        self._pending_output = ""    # output path of the in-flight export
        self._in = 0.0
        self._out = 0.0
        self._syncing = False

        self._load_ffmpeg_override()
        self._build_ui()
        self._build_menu()
        self._wire()
        self._refresh_ffmpeg_status()
        self._update_estimate()
        self._set_controls_enabled(False)

    # -- construction ----------------------------------------------------------

    def _icon(self, sp: QStyle.StandardPixmap):
        return self.style().standardIcon(sp)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Top bar: open + file summary.
        top = QHBoxLayout()
        top.setSpacing(12)
        self.open_btn = QPushButton("Open Video…")
        self.info_label = QLabel("No file loaded — open a video or drag one here.")
        self.info_label.setObjectName("InfoLabel")
        top.addWidget(self.open_btn)
        top.addWidget(self.info_label, 1)
        root.addLayout(top)

        # Preview.
        self.player = VideoPlayer()
        self.player.setObjectName("VideoPanel")
        self.player.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.player, 1)

        # Timeline.
        self.slider = RangeSlider()
        root.addWidget(self.slider)

        # Transport row.
        transport = QHBoxLayout()
        self.prev_btn = QPushButton(self._icon(QStyle.StandardPixmap.SP_MediaSkipBackward), "")
        self.play_btn = QPushButton(self._icon(QStyle.StandardPixmap.SP_MediaPlay), "")
        self.next_btn = QPushButton(self._icon(QStyle.StandardPixmap.SP_MediaSkipForward), "")
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            b.setObjectName("Transport")
            b.setFixedWidth(48)
        self.prev_btn.setToolTip("Jump to trim start (In)")
        self.next_btn.setToolTip("Jump to trim end (Out)")
        self.play_btn.setToolTip("Play / Pause")
        self.time_label = QLabel("00:00:00.000  ·  frame 0")
        self.time_label.setObjectName("TimeLabel")
        transport.addWidget(self.prev_btn)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.next_btn)
        transport.addSpacing(12)
        transport.addWidget(self.time_label)
        transport.addStretch(1)
        root.addLayout(transport)

        # Trim + export side by side.
        panels = QHBoxLayout()
        panels.addWidget(self._build_trim_group())
        panels.addWidget(self._build_export_group(), 1)
        root.addLayout(panels)

        # Progress row.
        prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Idle")
        self.export_btn = QPushButton("Compress && Export")
        self.export_btn.setObjectName("Primary")
        self.export_btn.setMinimumHeight(40)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        prog.addWidget(self.export_btn)
        prog.addWidget(self.progress, 1)
        prog.addWidget(self.cancel_btn)
        root.addLayout(prog)

        self.status = self.statusBar()

    def _build_trim_group(self) -> QGroupBox:
        group = QGroupBox("TRIM")
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.set_in_btn = QPushButton("Set In")
        self.set_out_btn = QPushButton("Set Out")
        self.in_edit = QLineEdit()
        self.out_edit = QLineEdit()
        self.in_edit.setObjectName("Timecode")
        self.out_edit.setObjectName("Timecode")
        self.in_edit.setFixedWidth(120)
        self.out_edit.setFixedWidth(120)
        self.in_frame = QSpinBox()
        self.out_frame = QSpinBox()
        self.in_frame.setMaximum(0)
        self.out_frame.setMaximum(0)
        self.in_frame.setPrefix("f ")
        self.out_frame.setPrefix("f ")

        grid.addWidget(self.set_in_btn, 0, 0)
        grid.addWidget(self.in_edit, 0, 1)
        grid.addWidget(self.in_frame, 0, 2)
        grid.addWidget(self.set_out_btn, 1, 0)
        grid.addWidget(self.out_edit, 1, 1)
        grid.addWidget(self.out_frame, 1, 2)

        self.sel_label = QLabel("Selection: —")
        self.sel_label.setObjectName("SelLabel")
        grid.addWidget(self.sel_label, 2, 0, 1, 3)

        self.extract_btn = QPushButton("Extract Frame…")
        grid.addWidget(self.extract_btn, 3, 0, 1, 3)
        return group

    def _build_export_group(self) -> QGroupBox:
        group = QGroupBox("OUTPUT SIZE && FORMAT")
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Target size:"), 0, 0)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(0.1, 100000.0)
        self.size_spin.setDecimals(1)
        self.size_spin.setValue(10.0)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["MB (10⁶)", "MiB (2²⁰)"])
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_spin)
        size_row.addWidget(self.unit_combo)
        grid.addLayout(size_row, 0, 1)

        grid.addWidget(QLabel("Preset:"), 1, 0)
        self.preset_combo = QComboBox()
        for label, _mb in SIZE_PRESETS:
            self.preset_combo.addItem(label)
        self.preset_combo.setCurrentIndex(1)  # Discord free (10 MB)
        grid.addWidget(self.preset_combo, 1, 1)

        grid.addWidget(QLabel("Codec:"), 2, 0)
        self.codec_combo = QComboBox()
        self.codec_combo.addItem("H.264 (universal, plays in Discord)", "h264")
        self.codec_combo.addItem("H.265 / HEVC (smaller files)", "h265")
        grid.addWidget(self.codec_combo, 2, 1)

        grid.addWidget(QLabel("Audio:"), 3, 0)
        audio_row = QHBoxLayout()
        self.audio_check = QCheckBox("Keep")
        self.audio_check.setChecked(True)
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.addItems(["96 kbps", "128 kbps", "192 kbps"])
        self.audio_bitrate.setCurrentIndex(1)
        audio_row.addWidget(self.audio_check)
        audio_row.addWidget(self.audio_bitrate)
        audio_row.addStretch(1)
        grid.addLayout(audio_row, 3, 1)

        grid.addWidget(QLabel("Resolution:"), 4, 0)
        self.res_combo = QComboBox()
        self.res_combo.addItem("Keep source", None)
        self.res_combo.addItem("Downscale to 720p", 720)
        self.res_combo.addItem("Downscale to 480p", 480)
        grid.addWidget(self.res_combo, 4, 1)

        self.estimate_label = QLabel("—")
        self.estimate_label.setWordWrap(True)
        grid.addWidget(self.estimate_label, 5, 0, 1, 2)

        # Folder and file name are separate fields — the '.mp4' is fixed, so the output
        # can never end up extension-less (which breaks ffmpeg's muxer selection).
        grid.addWidget(QLabel("Folder:"), 6, 0)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose a save folder")
        self.browse_btn = QPushButton("Browse…")
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_btn)
        grid.addLayout(folder_row, 6, 1)

        grid.addWidget(QLabel("File name:"), 7, 0)
        name_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("clip")
        ext_label = QLabel(".mp4")
        ext_label.setObjectName("ExtLabel")
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(ext_label)
        grid.addLayout(name_row, 7, 1)

        self.remember_dir_check = QCheckBox("Save to last-used folder")
        self.remember_dir_check.setToolTip(
            "On: new videos default their save folder to the one you last saved into.\n"
            "Off: new videos default to the source video's folder.")
        grid.addWidget(self.remember_dir_check, 8, 1)
        return group

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_open = QAction("&Open Video…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.open_file_dialog)
        file_menu.addAction(act_open)

        act_ffmpeg = QAction("Set &FFmpeg location…", self)
        act_ffmpeg.triggered.connect(self.set_ffmpeg_location)
        file_menu.addAction(act_ffmpeg)
        file_menu.addSeparator()

        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("&Help")
        act_tutorial = QAction("Show &Tutorial…", self)
        act_tutorial.triggered.connect(lambda: self.show_tutorial())
        help_menu.addAction(act_tutorial)

        act_shortcut = QAction("Create &Desktop Shortcut…", self)
        act_shortcut.triggered.connect(lambda: self.create_desktop_shortcut())
        help_menu.addAction(act_shortcut)
        help_menu.addSeparator()

        act_about = QAction("&About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _wire(self) -> None:
        self.open_btn.clicked.connect(self.open_file_dialog)

        self.player.positionChanged.connect(self._on_position)
        self.player.playingChanged.connect(self._on_playing_changed)
        self.player.fileDropped.connect(self._on_file_dropped)   # drop onto the preview to replace

        self.slider.playheadChanged.connect(self.player.seek)
        self.slider.inChanged.connect(lambda t: self._apply_in(t, seek=True))
        self.slider.outChanged.connect(lambda t: self._apply_out(t, seek=True))

        self.prev_btn.clicked.connect(self.jump_to_in)
        self.next_btn.clicked.connect(self.jump_to_out)
        self.play_btn.clicked.connect(self.player.toggle_play)

        # Frame stepping moved off the transport buttons (they now jump to In/Out);
        # keep it on the arrow keys so frame-accurate positioning is still available.
        self._sc_prev_frame = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._sc_prev_frame.activated.connect(lambda: self._step_frames(-1))
        self._sc_next_frame = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._sc_next_frame.activated.connect(lambda: self._step_frames(1))

        self.set_in_btn.clicked.connect(lambda: self._apply_in(self.player.position()))
        self.set_out_btn.clicked.connect(lambda: self._apply_out(self.player.position()))
        self.in_edit.editingFinished.connect(self._on_in_edit)
        self.out_edit.editingFinished.connect(self._on_out_edit)
        self.in_frame.editingFinished.connect(self._on_in_frame)
        self.out_frame.editingFinished.connect(self._on_out_frame)
        self.extract_btn.clicked.connect(self.extract_frame)

        self.size_spin.valueChanged.connect(self._on_size_changed)
        self.unit_combo.currentIndexChanged.connect(self._update_estimate)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.codec_combo.currentIndexChanged.connect(self._update_estimate)
        self.audio_check.toggled.connect(self._on_audio_toggled)
        self.audio_bitrate.currentIndexChanged.connect(self._update_estimate)
        self.res_combo.currentIndexChanged.connect(self._update_estimate)
        self.browse_btn.clicked.connect(self.browse_folder)
        self.remember_dir_check.setChecked(
            self.settings.value("use_last_output_dir", True, bool))
        self.remember_dir_check.toggled.connect(self._on_remember_dir_toggled)

        self.export_btn.clicked.connect(self.start_export)
        self.cancel_btn.clicked.connect(self.cancel_export)

    # -- ffmpeg discovery ------------------------------------------------------

    def _load_ffmpeg_override(self) -> None:
        ffmpeg = self.settings.value("ffmpeg_path", "", str)
        ffprobe = self.settings.value("ffprobe_path", "", str)
        ffmpeg_utils.set_overrides(ffmpeg or None, ffprobe or None)

    def _refresh_ffmpeg_status(self) -> None:
        try:
            path = ffmpeg_utils.discover_ffmpeg()
            self.statusBar().showMessage(f"FFmpeg: {path}")
        except ffmpeg_utils.FFmpegNotFound as exc:
            self.statusBar().showMessage("FFmpeg not found — set its location in the File menu.")
            QMessageBox.warning(self, "FFmpeg not found", str(exc))

    def set_ffmpeg_location(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ffmpeg executable", "", "ffmpeg (ffmpeg.exe ffmpeg);;All files (*.*)"
        )
        if not path:
            return
        folder = Path(path).parent
        probe = folder / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        self.settings.setValue("ffmpeg_path", path)
        if probe.exists():
            self.settings.setValue("ffprobe_path", str(probe))
        self._load_ffmpeg_override()
        self._refresh_ffmpeg_status()

    # -- file loading ----------------------------------------------------------

    def open_file_dialog(self) -> None:
        start_dir = self.settings.value("last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(self, "Open video", start_dir, VIDEO_FILTER)
        if path:
            self.load_video(path)

    def load_video(self, path: str) -> None:
        if self.encoder is not None and self.encoder.is_running():
            QMessageBox.information(
                self, "Export in progress",
                "Finish or cancel the current export before opening another video.")
            return
        if not ffmpeg_utils.ffmpeg_available():
            self._refresh_ffmpeg_status()
            return
        try:
            info = ffmpeg_utils.probe(path)
        except Exception as exc:  # noqa: BLE001 - surface any probe failure to the user
            QMessageBox.critical(self, "Could not open file", str(exc))
            return

        if info.duration <= 0:
            QMessageBox.critical(self, "Could not open file",
                                 "This file has no readable duration.")
            return

        self.info = info
        self.settings.setValue("last_dir", str(Path(path).parent))

        self._in = 0.0
        self._out = info.duration
        self.slider.set_min_gap(info.frame_duration)
        self.slider.set_duration(info.duration)
        self.in_frame.setMaximum(info.frame_count)
        self.out_frame.setMaximum(info.frame_count)

        self.player.load(path, info.fps)
        self.player.set_volume(0.8)

        audio = f"{info.a_codec}" if info.has_audio else "no audio"
        self.info_label.setText(
            f"{Path(path).name}  ·  {format_timecode(info.duration, show_ms=False)}  ·  "
            f"{info.width}×{info.height}  ·  {info.fps:.3f} fps  ·  "
            f"{format_size(info.file_size)}  ·  {info.v_codec}/{audio}"
        )
        self.audio_check.setEnabled(info.has_audio)
        if not info.has_audio:
            self.audio_check.setChecked(False)

        # Default output path: last-used folder (if enabled) else next to the source.
        self._apply_default_output_path()

        self._set_controls_enabled(True)
        self._refresh_trim_widgets()
        self._update_estimate()

    # -- trim logic ------------------------------------------------------------

    def _snap_time(self, t: float) -> float:
        if not self.info:
            return max(0.0, t)
        fd = self.info.frame_duration
        if fd <= 0:
            return max(0.0, min(t, self.info.duration))
        snapped = round(t / fd) * fd
        return max(0.0, min(snapped, self.info.duration))

    def _apply_in(self, t: float, seek: bool = True) -> None:
        if not self.info:
            return
        fd = self.info.frame_duration
        t = self._snap_time(t)
        t = min(t, max(0.0, self._out - fd))    # keep at least one frame
        self._in = max(0.0, t)
        self._refresh_trim_widgets()
        if seek:
            self.player.seek(self._in)
        self._update_estimate()

    def _apply_out(self, t: float, seek: bool = True) -> None:
        if not self.info:
            return
        fd = self.info.frame_duration
        t = self._snap_time(t)
        t = max(t, self._in + fd)               # keep at least one frame
        self._out = min(self.info.duration, t)
        self._refresh_trim_widgets()
        if seek:
            self.player.seek(self._out)
        self._update_estimate()

    def _refresh_trim_widgets(self) -> None:
        if not self.info:
            return
        fd = self.info.frame_duration
        self._syncing = True
        self.in_edit.setText(format_timecode(self._in))
        self.out_edit.setText(format_timecode(self._out))
        self.in_frame.setValue(round(self._in / fd) if fd else 0)
        self.out_frame.setValue(round(self._out / fd) if fd else 0)
        self.slider.set_in(self._in)
        self.slider.set_out(self._out)
        dur = self._out - self._in
        frames = round(dur / fd) if fd else 0
        self.sel_label.setText(
            f"Selection: {format_timecode(dur)}  ({frames} frame{'s' if frames != 1 else ''})"
        )
        self._syncing = False

    def _on_in_edit(self) -> None:
        if self._syncing:
            return
        t = parse_timecode(self.in_edit.text())
        if t is None:
            self._refresh_trim_widgets()
        else:
            self._apply_in(t)

    def _on_out_edit(self) -> None:
        if self._syncing:
            return
        t = parse_timecode(self.out_edit.text())
        if t is None:
            self._refresh_trim_widgets()
        else:
            self._apply_out(t)

    def _on_in_frame(self) -> None:
        if self._syncing or not self.info:
            return
        self._apply_in(self.in_frame.value() * self.info.frame_duration)

    def _on_out_frame(self) -> None:
        if self._syncing or not self.info:
            return
        self._apply_out(self.out_frame.value() * self.info.frame_duration)

    # -- playback callbacks ----------------------------------------------------

    def jump_to_in(self) -> None:
        """Move the playhead to the start of the trim selection."""
        if self.info:
            self.player.seek(self._in)

    def jump_to_out(self) -> None:
        """Move the playhead to the end of the trim selection."""
        if self.info:
            self.player.seek(self._out)

    def _step_frames(self, delta: int) -> None:
        if self.info:
            self.player.step_frames(delta)

    def _on_position(self, seconds: float) -> None:
        if not self.info:
            return
        frame = round(seconds / self.info.frame_duration) if self.info.frame_duration else 0
        self.time_label.setText(f"{format_timecode(seconds)}  ·  frame {frame}")
        self.slider.set_playhead(seconds)

    def _on_playing_changed(self, playing: bool) -> None:
        icon = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.play_btn.setIcon(self._icon(icon))

    # -- extract frame ---------------------------------------------------------

    def extract_frame(self) -> None:
        if not self.info:
            return
        default_dir = self.settings.value("last_dir", "", str)
        stem = Path(self.info.path).stem
        pos = self.player.position()
        default = os.path.join(default_dir, f"{stem}_frame_{format_timecode(pos).replace(':', '-')}.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save frame", default, "PNG image (*.png);;JPEG image (*.jpg)"
        )
        if not path:
            return
        try:
            self.player.extract_frame(path)
            self.statusBar().showMessage(f"Saved frame → {path}", 5000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Extract frame failed", str(exc))

    # -- size / estimate -------------------------------------------------------

    def _unit_bytes(self) -> int:
        return 1_000_000 if self.unit_combo.currentIndex() == 0 else 1_048_576

    def _target_bytes(self) -> int:
        return int(self.size_spin.value() * self._unit_bytes())

    def _audio_kbps(self) -> int:
        return [96, 128, 192][self.audio_bitrate.currentIndex()]

    def _on_size_changed(self) -> None:
        if not self._syncing:
            self.preset_combo.setCurrentIndex(0)  # Custom
        self._update_estimate()

    def _on_preset_changed(self, index: int) -> None:
        mb = SIZE_PRESETS[index][1]
        if mb is not None:
            self._syncing = True
            self.unit_combo.setCurrentIndex(0)  # MB
            self.size_spin.setValue(float(mb))
            self._syncing = False
        self._update_estimate()

    def _on_audio_toggled(self, _checked: bool) -> None:
        self.audio_bitrate.setEnabled(self.audio_check.isChecked())
        self._update_estimate()

    def _update_estimate(self) -> None:
        duration = self._out - self._in
        if not self.info or duration <= 0:
            self.estimate_label.setText("Load a video and choose a selection to see the estimate.")
            return
        audio_bps = self._audio_kbps() * 1000 if self.audio_check.isChecked() else 0
        vb = compute_video_bitrate_bps(self._target_bytes(), duration, audio_bps)
        text = (f"Clip {format_timecode(duration)} → video ≈ {vb / 1000:,.0f} kbps"
                f" + audio {audio_bps // 1000 if audio_bps else 0} kbps")
        if vb < LOW_BITRATE_FLOOR_BPS:
            text += "  ⚠ very low bitrate — expect blocky video; try a shorter clip or lower resolution."
            self.estimate_label.setStyleSheet("color: #F0B232;")  # theme WARNING
        else:
            self.estimate_label.setStyleSheet("")
        self.estimate_label.setText(text)

    # -- export ----------------------------------------------------------------

    def _default_output_dir(self, src_path: str) -> str:
        """Save folder for a source: last-used folder if the option is on and it still
        exists, otherwise the source video's own folder."""
        if self.remember_dir_check.isChecked():
            last = self.settings.value("last_output_dir", "", str)
            if last and Path(last).is_dir():
                return last
        return str(Path(src_path).parent)

    def _apply_default_output_path(self) -> None:
        if self.info:
            src = Path(self.info.path)
            self.folder_edit.setText(self._default_output_dir(self.info.path))
            self.name_edit.setText(f"{src.stem}_trimmed")

    @staticmethod
    def _sanitize_stem(name: str) -> str:
        """A safe base file name (no extension): drop a typed '.mp4', replace characters
        Windows forbids in a filename, and trim trailing dots/spaces."""
        name = name.strip()
        if name.lower().endswith(".mp4"):
            name = name[:-4]
        name = "".join("_" if c in '\\/:*?"<>|' else c for c in name)
        return name.strip().rstrip(". ")

    def _output_path(self) -> str | None:
        """Compose folder + name + '.mp4', or None if either field is empty."""
        folder = self.folder_edit.text().strip()
        stem = self._sanitize_stem(self.name_edit.text())
        if not folder or not stem:
            return None
        return str(Path(folder) / f"{stem}.mp4")

    def _remember_output_dir(self, folder: str) -> None:
        """Record a folder as the next default save location."""
        if folder:
            self.settings.setValue("last_output_dir", folder)

    def _on_remember_dir_toggled(self, checked: bool) -> None:
        self.settings.setValue("use_last_output_dir", checked)
        self._apply_default_output_path()   # reflect the new preference in the folder field

    def browse_folder(self) -> None:
        start = (self.folder_edit.text().strip()
                 or self.settings.value("last_output_dir", "", str)
                 or self.settings.value("last_dir", "", str))
        folder = QFileDialog.getExistingDirectory(self, "Choose save folder", start)
        if folder:
            self.folder_edit.setText(folder)
            self._remember_output_dir(folder)   # a browsed folder becomes the new default

    def start_export(self) -> None:
        if not self.info:
            return
        if self.encoder is not None and self.encoder.is_running():
            return
        out_path = self._output_path()
        if not out_path:
            QMessageBox.warning(self, "Missing output",
                                "Choose a save folder and enter a file name.")
            return
        # Reflect the sanitized name back so the field matches what will be written.
        self.name_edit.setText(Path(out_path).stem)
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if not os.path.isdir(out_dir):
            QMessageBox.warning(self, "Folder not found",
                                f"This folder does not exist:\n{out_dir}\n\n"
                                "Pick a different location.")
            return
        if os.path.abspath(out_path) == os.path.abspath(self.info.path):
            QMessageBox.warning(self, "Same file", "Output path must differ from the source.")
            return

        duration = self._out - self._in
        audio_bps = self._audio_kbps() * 1000 if self.audio_check.isChecked() else 0
        vb = compute_video_bitrate_bps(self._target_bytes(), duration, audio_bps)
        if vb < LOW_BITRATE_FLOOR_BPS:
            resp = QMessageBox.question(
                self, "Very low bitrate",
                f"The target size gives only ~{vb / 1000:.0f} kbps of video, which will look "
                "rough at this resolution. If the encode overshoots the size limit, the app "
                "will automatically downscale and re-encode until the file fits.\n\n"
                "Export anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

        scale_height = self.res_combo.currentData()
        if scale_height and self.info.height and self.info.height <= scale_height:
            scale_height = None  # never upscale

        job = EncodeJob(
            input_path=self.info.path,
            output_path=out_path,
            start=self._in,
            duration=duration,
            target_bytes=self._target_bytes(),
            codec=self.codec_combo.currentData(),
            keep_audio=self.audio_check.isChecked() and self.info.has_audio,
            audio_kbps=self._audio_kbps(),
            scale_height=scale_height,
            fps=self.info.fps,   # normalize VFR sources to this constant rate
            src_width=self.info.width,
            src_height=self.info.height,   # start rung for the auto-fit ladder
        )

        self._pending_output = out_path   # remembered for the finished handler
        self.player.pause()
        self.encoder = Encoder(self)
        self.encoder.progress.connect(self._on_encode_progress)
        self.encoder.finished.connect(self._on_encode_finished)
        self.encoder.log.connect(lambda line: self.statusBar().showMessage(line))
        self._set_exporting(True)
        try:
            self.encoder.start(job)
        except Exception as exc:  # noqa: BLE001
            self._set_exporting(False)
            QMessageBox.critical(self, "Could not start", str(exc))

    def cancel_export(self) -> None:
        if self.encoder is not None and self.encoder.is_running():
            self.encoder.cancel()

    def _on_encode_progress(self, percent: int, stage: str) -> None:
        self.progress.setValue(percent)
        self.progress.setFormat(f"{stage} — {percent}%")

    def _on_encode_finished(self, success: bool, message: str) -> None:
        self._set_exporting(False)
        self.progress.setFormat("Done" if success else "Idle")
        self.progress.setValue(100 if success else 0)
        self.encoder = None
        if success:
            out_path = self._pending_output
            self._remember_output_dir(str(Path(out_path).parent))   # default future saves here
            box = QMessageBox(self)
            box.setWindowTitle("Export complete")
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(message)
            open_btn = box.addButton("Show in folder", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out_path).parent)))
        elif message != "Cancelled.":
            QMessageBox.critical(self, "Export failed", message)
        else:
            self.statusBar().showMessage("Export cancelled.", 5000)

    # -- enable/disable --------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self.slider, self.prev_btn, self.play_btn, self.next_btn,
                  self.set_in_btn, self.set_out_btn, self.in_edit, self.out_edit,
                  self.in_frame, self.out_frame, self.extract_btn, self.export_btn,
                  self.browse_btn, self.folder_edit, self.name_edit):
            w.setEnabled(enabled)

    def _set_exporting(self, exporting: bool) -> None:
        self.cancel_btn.setEnabled(exporting)
        for w in (self.export_btn, self.open_btn, self.set_in_btn, self.set_out_btn,
                  self.extract_btn, self.size_spin, self.unit_combo, self.preset_combo,
                  self.codec_combo, self.audio_check, self.audio_bitrate, self.res_combo,
                  self.browse_btn, self.folder_edit, self.name_edit):
            w.setEnabled(not exporting)
        if exporting:
            self.progress.setValue(0)

    # -- drag & drop -----------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTS:
                event.acceptProposedAction()
                return

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTS:
                self._on_file_dropped(url.toLocalFile())
                return

    def _on_file_dropped(self, path: str) -> None:
        """Handle a dropped video. If a clip is already open, confirm the swap first."""
        if self.encoder is not None and self.encoder.is_running():
            # Defer to load_video, which shows the "export in progress" refusal.
            self.load_video(path)
            return
        if self.info is not None:
            resp = QMessageBox.question(
                self, "Replace video?",
                f"Replace the open video with “{Path(path).name}”?\n"
                "The current trim selection will be reset.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        self.load_video(path)

    # -- misc ------------------------------------------------------------------

    # -- onboarding ------------------------------------------------------------

    def run_first_launch(self) -> None:
        """Show the tutorial the first time the app is ever opened. Safe to call
        on every launch — it's a no-op once the tutorial has been seen."""
        from . import onboarding

        if onboarding.should_show_tutorial(self.settings):
            self.show_tutorial(first_run=True)

    def show_tutorial(self, first_run: bool = False) -> None:
        from . import onboarding

        onboarding.WelcomeDialog(self, self.settings, first_run=first_run).exec()

    def create_desktop_shortcut(self) -> None:
        from . import onboarding

        ok, detail = onboarding.create_desktop_shortcut()
        if ok:
            self.statusBar().showMessage(f"Desktop shortcut created → {detail}", 5000)
            QMessageBox.information(
                self, "Shortcut created",
                f"A shortcut to {__app_name__} was placed on your desktop.",
            )
        else:
            QMessageBox.warning(self, "Shortcut not created", detail)

    def _show_about(self) -> None:
        from . import __version__
        QMessageBox.about(
            self, "About DiscordVidShare",
            f"<b>DiscordVidShare {__version__}</b><br><br>"
            "Trim a video clip and compress it to a target file size using two-pass "
            "FFmpeg encoding — built for sharing clips under upload limits.",
        )

    def closeEvent(self, event) -> None:
        if self.encoder is not None and self.encoder.is_running():
            self.encoder.cancel()
        event.accept()
