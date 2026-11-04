"""Minimal Vietnamese desktop interface for audio-to-Sky-JSON conversion."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
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
    QVBoxLayout,
    QWidget,
)

from sky_cotl_studio.gui.viewmodel import (
    ConversionForm,
    build_job_config,
    device_from_label,
    failure_message_vi,
    format_completion_status,
    grid_mode_from_label,
    grid_ms_enabled,
    validate_form,
    youtube_output_suggestion,
)
from sky_cotl_studio.pipeline.job import (
    ConversionJob,
    JobProgress,
    JobState,
)

_LOG_DIRECTORY = Path(__file__).resolve().parents[3] / "logs"

_STATE_LABELS = {
    JobState.PENDING: "Chờ bắt đầu",
    JobState.DOWNLOADING: "Đang tải video YouTube",
    JobState.VALIDATING: "Đang kiểm tra âm thanh",
    JobState.TRANSCRIBING: "Đang chuyển MP3 thành MIDI",
    JobState.CONVERTING: "Đang xử lý nốt",
    JobState.EXPORTING: "Đang xuất JSON",
    JobState.DONE: "Hoàn tất",
    JobState.FAILED: "Thất bại",
    JobState.CANCELLED: "Đã hủy",
}


class Mp3PathEdit(QLineEdit):
    """Line edit that accepts a dropped audio file."""

    path_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Chọn tệp âm thanh hoặc dán liên kết YouTube")

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


class MainWindow(QMainWindow):
    """Main application window; worker callbacks are relayed through Qt signals."""

    progress_received = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._job: ConversionJob | None = None
        self._run_logger: logging.Logger | None = None
        self._build_ui()
        self.progress_received.connect(self._handle_progress)

    def _build_ui(self) -> None:
        self.setWindowTitle("Sky CotL — Âm thanh sang JSON")
        self.setMinimumSize(520, 360)
        self.resize(600, 400)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        form_layout = QFormLayout()

        self.input_path_edit = Mp3PathEdit()
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_path_edit)
        input_browse_button = QPushButton("Chọn tệp…")
        input_browse_button.clicked.connect(self._browse_mp3)
        input_row.addWidget(input_browse_button)
        form_layout.addRow("Tệp âm thanh hoặc liên kết YouTube:", input_row)

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Đường dẫn JSON đầu ra")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path_edit)
        output_browse_button = QPushButton("Lưu JSON…")
        output_browse_button.clicked.connect(self._browse_json)
        output_row.addWidget(output_browse_button)
        form_layout.addRow("Lưu JSON tại:", output_row)

        self.grid_mode_combo = QComboBox()
        self.grid_mode_combo.addItems(["Tự động", "Cố định"])
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
        form_layout.addRow("Lưới thời gian:", grid_row)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["Tự động", "CUDA", "CPU"])
        form_layout.addRow("Thiết bị:", self.device_combo)

        self.title_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.transcribed_by_edit = QLineEdit()
        form_layout.addRow("Tên bài:", self.title_edit)
        form_layout.addRow("Tác giả:", self.author_edit)
        form_layout.addRow("Người chép:", self.transcribed_by_edit)

        self.keep_midi_checkbox = QCheckBox("Giữ tệp MIDI trung gian")
        form_layout.addRow("", self.keep_midi_checkbox)
        layout.addLayout(form_layout)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Bắt đầu")
        self.start_button.clicked.connect(self._start_job)
        self.cancel_button = QPushButton("Hủy")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_job)
        self.open_folder_button = QPushButton("Mở thư mục chứa file")
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

    def _update_grid_ms_enabled(self, label: str) -> None:
        grid_mode = grid_mode_from_label(label)
        self.grid_ms_spin.setEnabled(grid_ms_enabled(grid_mode))

    def _browse_mp3(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Chọn tệp âm thanh",
            "",
            "Tệp âm thanh (*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.aac *.wma);;Tất cả tệp (*)",
        )
        if path:
            self.input_path_edit.setText(path)
            if not self.output_path_edit.text().strip():
                self.output_path_edit.setText(str(Path(path).with_suffix(".json")))
            if not self.title_edit.text().strip():
                self.title_edit.setText(Path(path).stem)

    def _browse_json(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Lưu JSON",
            self.output_path_edit.text(),
            "Tệp JSON (*.json)",
        )
        if path:
            self.output_path_edit.setText(path)

    def _form(self) -> ConversionForm:
        return ConversionForm(
            input_mp3=self.input_path_edit.text(),
            output_json=self.output_path_edit.text(),
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
        try:
            form = self._form()
        except ValueError as error:
            QMessageBox.warning(self, "Thông tin chưa hợp lệ", str(error))
            return
        errors = validate_form(form)
        if errors:
            QMessageBox.warning(
                self,
                "Thông tin chưa hợp lệ",
                "\n".join(errors),
            )
            return

        self.open_folder_button.setEnabled(False)
        try:
            config = build_job_config(form)
            self._start_run_log()
            self._log_info(
                "Bắt đầu chuyển đổi: %s",
                config.input_url or config.input_path,
            )
            job = ConversionJob(
                config,
                progress_callback=self.progress_received.emit,
            )
            job.start()
        except (OSError, RuntimeError, TypeError, ValueError):
            self._log_exception("Không thể bắt đầu tác vụ chuyển đổi")
            QMessageBox.critical(
                self,
                "Không thể bắt đầu",
                "Không thể khởi chạy tác vụ chuyển đổi.",
            )
            return

        self._job = job
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        if config.input_url is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.status_label.setText(_STATE_LABELS[JobState.DOWNLOADING])
        else:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(_STATE_LABELS[JobState.VALIDATING])

    @Slot()
    def _cancel_job(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self.cancel_button.setEnabled(False)
            self._log_info("Đã yêu cầu hủy tác vụ.")

    @Slot(object)
    def _handle_progress(self, event: object) -> None:
        if not isinstance(event, JobProgress):
            return
        self.status_label.setText(_STATE_LABELS[event.phase])
        if event.title:
            if not self.title_edit.text().strip():
                self.title_edit.setText(event.title)
            if not self.output_path_edit.text().strip():
                self.output_path_edit.setText(youtube_output_suggestion(event.title))
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
            self.start_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self._show_terminal_result(event.phase)

    def _show_terminal_result(self, state: JobState) -> None:
        job = self._job
        if job is None:
            return
        if state is JobState.DONE and job.result is not None:
            self.status_label.setText(
                format_completion_status(job.result.conversion)
            )
            self._log_info("Kết quả: %s", self.status_label.text())
            self.open_folder_button.setEnabled(True)
        elif state is JobState.FAILED and job.failure is not None:
            self._log_error(
                "Chuyển đổi thất bại: %s",
                job.failure.technical_cause,
            )
            QMessageBox.critical(
                self,
                "Chuyển đổi thất bại",
                failure_message_vi(job.failure.user_message),
            )
        elif state is JobState.CANCELLED:
            self._log_info("Tác vụ đã bị hủy.")

    def _open_output_folder(self) -> None:
        if self._job is not None and self._job.result is not None:
            folder = self._job.result.json_path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _start_run_log(self) -> None:
        from sky_cotl_studio.gui.logging_utils import create_run_logger

        self._run_logger = create_run_logger(_LOG_DIRECTORY)

    def _log_info(self, message: str, *args: object) -> None:
        if self._run_logger is not None:
            self._run_logger.info(message, *args)

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
