"""Minimal Vietnamese desktop interface for MP3-to-Sky-JSON conversion."""

from __future__ import annotations

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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sky_cotl_studio.gui.viewmodel import (
    ConversionForm,
    build_job_config,
    device_from_label,
    format_summary,
    grid_mode_from_label,
    grid_ms_enabled,
    validate_form,
)
from sky_cotl_studio.pipeline.job import (
    ConversionJob,
    JobProgress,
    JobState,
)

_STATE_LABELS = {
    JobState.PENDING: "Chờ bắt đầu",
    JobState.VALIDATING: "Đang kiểm tra MP3",
    JobState.TRANSCRIBING: "Đang chuyển MP3 thành MIDI",
    JobState.CONVERTING: "Đang xử lý nốt",
    JobState.EXPORTING: "Đang xuất JSON",
    JobState.DONE: "Hoàn tất",
    JobState.FAILED: "Thất bại",
    JobState.CANCELLED: "Đã hủy",
}


class Mp3PathEdit(QLineEdit):
    """Line edit that accepts a dropped MP3 path."""

    path_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Chọn hoặc kéo thả tệp MP3 vào đây")

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
        if path.lower().endswith(".mp3"):
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
        self._build_ui()
        self.progress_received.connect(self._handle_progress)

    def _build_ui(self) -> None:
        self.setWindowTitle("Sky CotL — MP3 sang JSON")
        self.setMinimumWidth(620)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        form_layout = QFormLayout()

        self.input_path_edit = Mp3PathEdit()
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_path_edit)
        input_browse_button = QPushButton("Chọn MP3…")
        input_browse_button.clicked.connect(self._browse_mp3)
        input_row.addWidget(input_browse_button)
        form_layout.addRow("Tệp MP3:", input_row)

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

        self.summary_view = QPlainTextEdit()
        self.summary_view.setReadOnly(True)
        self.summary_view.setPlaceholderText("Tóm tắt sẽ hiện ở đây khi hoàn tất.")
        layout.addWidget(self.summary_view)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setPlaceholderText("Nhật ký xử lý")
        layout.addWidget(self.log_view)
        self.setCentralWidget(central_widget)

    def _update_grid_ms_enabled(self, label: str) -> None:
        grid_mode = grid_mode_from_label(label)
        self.grid_ms_spin.setEnabled(grid_ms_enabled(grid_mode))

    def _browse_mp3(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Chọn tệp MP3",
            "",
            "Tệp MP3 (*.mp3)",
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

        self.summary_view.clear()
        self.open_folder_button.setEnabled(False)
        try:
            config = build_job_config(form)
            job = ConversionJob(
                config,
                progress_callback=self.progress_received.emit,
            )
            job.start()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Không thể bắt đầu", str(error))
            return

        self._job = job
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(_STATE_LABELS[JobState.VALIDATING])

    @Slot()
    def _cancel_job(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self.cancel_button.setEnabled(False)
            self._append_log("Đã yêu cầu hủy tác vụ.")

    @Slot(object)
    def _handle_progress(self, event: object) -> None:
        if not isinstance(event, JobProgress):
            return
        self.status_label.setText(_STATE_LABELS[event.phase])
        self._append_log(event.message)
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
            self.summary_view.setPlainText(format_summary(job.result))
            self.open_folder_button.setEnabled(True)
        elif state is JobState.FAILED and job.failure is not None:
            self.summary_view.setPlainText(job.failure.user_message)
            self._append_log(f"Nguyên nhân kỹ thuật: {job.failure.technical_cause}")

    def _open_output_folder(self) -> None:
        if self._job is not None and self._job.result is not None:
            folder = self._job.result.json_path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def closeEvent(self, event: object) -> None:
        if self._job is not None:
            self._job.cancel()
        super().closeEvent(event)  # type: ignore[arg-type]
