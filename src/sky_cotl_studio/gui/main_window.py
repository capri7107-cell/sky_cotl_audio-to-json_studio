"""English desktop interface for audio-to-Sky-JSON conversion."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sky_cotl_studio.audio.download import _creation_flags
from sky_cotl_studio.gui.viewmodel import (
    ConversionForm,
    SourceMode,
    SuggestedField,
    build_job_config,
    device_from_label,
    failure_message,
    format_completion_status,
    grid_mode_from_label,
    grid_ms_enabled,
    switch_source_mode,
    update_source_title,
    validate_form,
)
from sky_cotl_studio.pipeline.job import ConversionJob, JobProgress, JobState
from sky_cotl_studio.settings import (
    DEFAULT_OUTPUT_DIRECTORY,
    DEFAULT_SETTINGS_PATH,
    ensure_writable_directory,
    load_settings,
    save_settings,
)

_LOG_DIRECTORY = DEFAULT_SETTINGS_PATH.parent / "logs"
_STATE_LABELS = {
    JobState.PENDING: "Waiting to start",
    JobState.DOWNLOADING: "Downloading from YouTube",
    JobState.VALIDATING: "Checking audio",
    JobState.TRANSCRIBING: "Transcribing audio to MIDI",
    JobState.CONVERTING: "Converting notes",
    JobState.EXPORTING: "Saving JSON",
    JobState.DONE: "Done",
    JobState.FAILED: "Failed",
    JobState.CANCELLED: "Cancelled",
}
_AUDIO_FILTER = (
    "Audio files (*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.aac *.wma);;All files (*)"
)


class AudioFileEdit(QLineEdit):
    """Line edit that accepts dropped audio files."""

    path_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Choose or drop an audio file")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        path = urls[0].toLocalFile()
        if Path(path).suffix.lower() in {
            ".mp3",
            ".wav",
            ".m4a",
            ".flac",
            ".ogg",
            ".opus",
            ".aac",
            ".wma",
        }:
            self.setText(path)
            self.path_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()


class ElidedPathEdit(QLineEdit):
    """Read-only path field that elides its display while retaining its full path."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.full_path = ""

    def set_full_path(self, path: str | Path) -> None:
        self.full_path = str(path)
        self.setToolTip(self.full_path)
        self._refresh_elided_text()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._refresh_elided_text()

    def _refresh_elided_text(self) -> None:
        available_width = max(0, self.width() - 12)
        elided = QFontMetrics(self.font()).elidedText(
            self.full_path,
            Qt.TextElideMode.ElideMiddle,
            available_width,
        )
        self.setText(elided)


class MainWindow(QMainWindow):
    """Main window; worker callbacks are relayed through a Qt signal."""

    progress_received = Signal(object)

    def __init__(
        self,
        *,
        settings_path: str | Path = DEFAULT_SETTINGS_PATH,
        default_output_folder: str | Path = DEFAULT_OUTPUT_DIRECTORY,
        log_directory: str | Path = _LOG_DIRECTORY,
    ) -> None:
        super().__init__()
        self._settings_path = Path(settings_path)
        self._default_output_folder = Path(default_output_folder).resolve()
        self._log_directory = Path(log_directory)
        self._job: ConversionJob | None = None
        self._run_logger: logging.Logger | None = None
        self._title_suggestion = SuggestedField()
        self._settings_warning: str | None = None
        self._folder_reminder: str | None = None
        self.output_directory = self._load_output_directory()
        self._build_ui()
        self.progress_received.connect(self._handle_progress)
        self._start_run_log()
        if self._settings_warning:
            self._log_warning(self._settings_warning)

    def _load_output_directory(self) -> Path:
        settings = load_settings(self._settings_path, self._default_output_folder)
        if settings.warning:
            self._settings_warning = settings.warning
        try:
            return ensure_writable_directory(settings.output_directory)
        except (OSError, ValueError) as error:
            self._settings_warning = (
                f"Could not use saved output folder {settings.output_directory}: {error}"
            )
            self._folder_reminder = (
                "The saved output folder is unavailable. Using the default output folder."
            )
            try:
                return ensure_writable_directory(self._default_output_folder)
            except (OSError, ValueError) as fallback_error:
                self._settings_warning += f"; default output folder also failed: {fallback_error}"
                self._folder_reminder = (
                    "The saved output folder is unavailable, and the default output folder "
                    "could not be created."
                )
                return self._default_output_folder

    def _build_ui(self) -> None:
        self.setWindowTitle("Sky CotL — Audio to JSON")
        self.setMinimumSize(520, 360)
        self.resize(620, 420)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        form_layout = QFormLayout()

        self.youtube_radio = QRadioButton("YouTube link")
        self.audio_radio = QRadioButton("Audio file")
        self.youtube_radio.setChecked(True)
        source_row = QHBoxLayout()
        source_row.addWidget(self.youtube_radio)
        source_row.addWidget(self.audio_radio)
        source_row.addStretch()
        form_layout.addRow("Source:", source_row)

        self.source_stack = QStackedWidget()
        youtube_page = QWidget()
        youtube_row = QHBoxLayout(youtube_page)
        youtube_row.setContentsMargins(0, 0, 0, 0)
        self.youtube_link_edit = QLineEdit()
        self.youtube_link_edit.setPlaceholderText("Paste a YouTube link")
        self.youtube_link_edit.textEdited.connect(self._source_edited)
        youtube_row.addWidget(self.youtube_link_edit)
        self.paste_button = QPushButton("Paste")
        self.paste_button.clicked.connect(self._paste_link)
        youtube_row.addWidget(self.paste_button)

        audio_page = QWidget()
        audio_row = QHBoxLayout(audio_page)
        audio_row.setContentsMargins(0, 0, 0, 0)
        self.audio_file_edit = AudioFileEdit()
        self.audio_file_edit.textEdited.connect(self._source_edited)
        self.audio_file_edit.path_dropped.connect(self._source_edited)
        audio_row.addWidget(self.audio_file_edit)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse_audio)
        audio_row.addWidget(self.browse_button)
        self.source_stack.addWidget(youtube_page)
        self.source_stack.addWidget(audio_page)
        self.source_label = QLabel("YouTube link:")
        form_layout.addRow(self.source_label, self.source_stack)
        self.youtube_radio.toggled.connect(self._source_mode_changed)
        self.audio_radio.toggled.connect(self._source_mode_changed)

        output_row = QHBoxLayout()
        self.output_folder_edit = ElidedPathEdit()
        self.output_folder_edit.set_full_path(self.output_directory)
        output_row.addWidget(self.output_folder_edit)
        self.change_output_button = QPushButton("Change…")
        self.change_output_button.clicked.connect(self._change_output_folder)
        output_row.addWidget(self.change_output_button)
        form_layout.addRow("Output folder:", output_row)

        self.grid_mode_combo = QComboBox()
        self.grid_mode_combo.addItems(["Automatic", "Fixed"])
        self.grid_ms_spin = QDoubleSpinBox()
        self.grid_ms_spin.setRange(1.0, 10000.0)
        self.grid_ms_spin.setDecimals(2)
        self.grid_ms_spin.setValue(120.0)
        self.grid_ms_spin.setSuffix(" ms")
        self.grid_ms_spin.setEnabled(False)
        self.grid_mode_combo.currentTextChanged.connect(self._update_grid_ms_enabled)
        grid_row = QHBoxLayout()
        grid_row.addWidget(self.grid_mode_combo)
        grid_row.addWidget(self.grid_ms_spin)
        form_layout.addRow("Time grid:", grid_row)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["Automatic", "CUDA", "CPU"])
        form_layout.addRow("Device:", self.device_combo)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Song title")
        self.title_edit.textEdited.connect(self._title_suggestion.set_by_user)
        self.author_edit = QLineEdit()
        self.transcribed_by_edit = QLineEdit()
        form_layout.addRow("Song title:", self.title_edit)
        form_layout.addRow("Author:", self.author_edit)
        form_layout.addRow("Transcribed by:", self.transcribed_by_edit)

        self.keep_midi_checkbox = QCheckBox("Keep intermediate MIDI file")
        form_layout.addRow("", self.keep_midi_checkbox)
        layout.addLayout(form_layout)

        self.folder_reminder_label = QLabel("")
        self.folder_reminder_label.setWordWrap(True)
        self.folder_reminder_label.setVisible(bool(self._folder_reminder))
        if self._folder_reminder:
            self.folder_reminder_label.setText(self._folder_reminder)
        layout.addWidget(self.folder_reminder_label)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._start_job)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_job)
        self.open_folder_button = QPushButton("Open folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        controls.addWidget(self.start_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.open_folder_button)
        layout.addLayout(controls)

        self.status_label = QLabel(_STATE_LABELS[JobState.PENDING])
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.setCentralWidget(central_widget)
        self.adjustSize()
        self.open_folder_button.setEnabled(True)

    def _source_mode(self) -> SourceMode:
        return "youtube" if self.youtube_radio.isChecked() else "file"

    def _source_mode_changed(self) -> None:
        if self.youtube_radio.isChecked():
            self.source_stack.setCurrentIndex(0)
            self.source_label.setText("YouTube link:")
        elif self.audio_radio.isChecked():
            self.source_stack.setCurrentIndex(1)
            self.source_label.setText("Audio file:")
        else:
            return
        self.youtube_link_edit.clear()
        self.audio_file_edit.clear()
        self.title_edit.setText(switch_source_mode(self._title_suggestion))

    def _active_source_edit(self) -> QLineEdit:
        return self.youtube_link_edit if self._source_mode() == "youtube" else self.audio_file_edit

    def _source_edited(self, source: str) -> None:
        self.title_edit.setText(
            update_source_title(source, self._source_mode(), self._title_suggestion)
        )

    def _paste_link(self) -> None:
        self.youtube_link_edit.setText(self._clipboard().text())
        self._source_edited(self.youtube_link_edit.text())

    def _clipboard(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.clipboard()

    def _browse_audio(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose an audio file",
            "",
            _AUDIO_FILTER,
        )
        if path:
            self.audio_file_edit.setText(path)
            self._source_edited(path)

    def _change_output_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose output folder",
            str(self.output_directory),
        )
        if not selected:
            return
        try:
            directory = ensure_writable_directory(selected)
            save_settings(self._settings_path, directory)
        except (OSError, ValueError) as error:
            self._show_error(
                "Cannot write to the output folder",
                "Cannot write to the output folder. Choose another folder.",
                str(error),
            )
            self._log_error("Could not save output folder: %s", error)
            return
        self.output_directory = directory
        self.output_folder_edit.set_full_path(directory)
        self.folder_reminder_label.clear()
        self.folder_reminder_label.setVisible(False)
        self.open_folder_button.setEnabled(True)

    def _update_grid_ms_enabled(self, label: str) -> None:
        self.grid_ms_spin.setEnabled(
            grid_ms_enabled(grid_mode_from_label(label))
        )

    def _form(self) -> ConversionForm:
        return ConversionForm(
            source_mode=self._source_mode(),
            input_source=self._active_source_edit().text(),
            output_folder=str(self.output_directory),
            grid_mode=grid_mode_from_label(self.grid_mode_combo.currentText()),
            grid_ms=str(self.grid_ms_spin.value()),
            device=device_from_label(self.device_combo.currentText()),
            title=self.title_edit.text(),
            author=self.author_edit.text(),
            transcribed_by=self.transcribed_by_edit.text(),
            keep_midi=self.keep_midi_checkbox.isChecked(),
        )

    @Slot()
    def _start_job(self) -> None:
        self._start_run_log()
        try:
            self.output_directory = ensure_writable_directory(self.output_directory)
        except (OSError, ValueError) as error:
            self._log_error("Output folder is not writable: %s", error)
            self._show_error(
                "Cannot write to the output folder",
                "Cannot write to the output folder. Choose another folder.",
                str(error),
            )
            return
        form = self._form()
        errors = validate_form(form, require_input_exists=form.source_mode == "file")
        if errors:
            self._show_error("Invalid input", "\n".join(errors))
            return

        self.open_folder_button.setEnabled(False)
        try:
            config = build_job_config(form)
            self._log_info(
                "Starting conversion: %s",
                config.input_url or config.input_path,
            )
            job = ConversionJob(
                config,
                progress_callback=self.progress_received.emit,
            )
            job.start()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._log_exception("Could not start conversion")
            self._show_error("Invalid input", "Could not start the conversion.", str(error))
            return

        self._job = job
        self._set_inputs_enabled(False)
        self.cancel_button.setEnabled(True)
        if config.input_url is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.status_label.setText(_STATE_LABELS[JobState.DOWNLOADING])
        else:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(_STATE_LABELS[JobState.VALIDATING])

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for widget in (
            self.youtube_radio,
            self.audio_radio,
            self.youtube_link_edit,
            self.paste_button,
            self.audio_file_edit,
            self.browse_button,
            self.change_output_button,
            self.grid_mode_combo,
            self.grid_ms_spin,
            self.device_combo,
            self.title_edit,
            self.author_edit,
            self.transcribed_by_edit,
            self.keep_midi_checkbox,
            self.start_button,
            self.open_folder_button,
        ):
            widget.setEnabled(enabled)

    @Slot()
    def _cancel_job(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self.cancel_button.setEnabled(False)
            self._log_info("Cancellation requested.")

    @Slot(object)
    def _handle_progress(self, event: object) -> None:
        if not isinstance(event, JobProgress):
            return
        self.status_label.setText(_STATE_LABELS[event.phase])
        if event.title and self._source_mode() == "youtube":
            self.title_edit.setText(
                update_source_title(
                    self.youtube_link_edit.text(),
                    "youtube",
                    self._title_suggestion,
                    video_title=event.title,
                )
            )
        if event.phase is JobState.DOWNLOADING:
            if event.percentage is None:
                if self.progress_bar.maximum() != 100:
                    self.progress_bar.setRange(0, 0)
            else:
                self.status_label.setText(
                    f"{_STATE_LABELS[event.phase]} ({event.percentage:.0f}%)"
                )
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(round(event.percentage))
        elif event.phase not in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
            self.progress_bar.setRange(0, 0)
        self._log_info("%s: %s", event.phase.value, event.message)
        if event.phase in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1 if event.phase is JobState.DONE else 0)
            self._set_inputs_enabled(True)
            self.cancel_button.setEnabled(False)
            self._show_terminal_result(event.phase)

    def _show_terminal_result(self, state: JobState) -> None:
        job = self._job
        if job is None:
            return
        if state is JobState.DONE and job.result is not None:
            self.status_label.setText(format_completion_status(job.result.json_path))
            self._log_info("Saved JSON: %s", job.result.json_path)
            self.open_folder_button.setEnabled(True)
        elif state is JobState.FAILED and job.failure is not None:
            self._log_error(
                "Conversion failed: %s",
                job.failure.technical_cause,
            )
            self._show_error(
                "Conversion failed",
                failure_message(job.failure.user_message),
                job.failure.details,
            )
        elif state is JobState.CANCELLED:
            self.status_label.setText(_STATE_LABELS[JobState.CANCELLED])
            self._log_info("Conversion cancelled.")

    def _open_output_folder(self) -> None:
        result = self._job.result if self._job is not None else None
        if result is not None and os.name == "nt":
            try:
                subprocess.Popen(
                    ["explorer.exe", "/select,", str(result.json_path)],
                    creationflags=_creation_flags(),
                )
                return
            except OSError as error:
                self._log_warning("Could not select the output file in Explorer: %s", error)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_directory)))

    def _show_error(self, title: str, message: str, details: str = "") -> None:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setDetailedText(details)
        dialog.exec()

    def _start_run_log(self) -> None:
        if self._run_logger is None:
            from sky_cotl_studio.gui.logging_utils import create_run_logger

            self._run_logger = create_run_logger(self._log_directory)

    def _log_info(self, message: str, *args: object) -> None:
        if self._run_logger is not None:
            self._run_logger.info(message, *args)

    def _log_warning(self, message: str, *args: object) -> None:
        if self._run_logger is not None:
            self._run_logger.warning(message, *args)

    def _log_error(self, message: str, *args: object) -> None:
        if self._run_logger is not None:
            self._run_logger.error(message, *args)

    def _log_exception(self, message: str) -> None:
        if self._run_logger is not None:
            self._run_logger.exception(message)

    def closeEvent(self, event: object) -> None:
        if self._job is not None:
            self._job.cancel()
        super().closeEvent(event)  # type: ignore[arg-type]
