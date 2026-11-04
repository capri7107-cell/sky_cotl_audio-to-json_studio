import os
import subprocess
import sys
from pathlib import Path


def test_main_window_source_workflow_status_and_errors_offscreen(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = str(project_root / "src")
    script = r"""
import sys
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QMessageBox
import sky_cotl_studio.gui.main_window as main_window_module
from sky_cotl_studio.gui.logging_utils import create_run_logger, install_exception_hook
from sky_cotl_studio.gui.main_window import MainWindow
from sky_cotl_studio.pipeline.job import JobFailure, JobProgress, JobState

root = Path(sys.argv[1])
settings = root / "settings.json"
output = root / "output"
audio = root / "Summertime.mp3"
audio.write_bytes(b"audio")
app = QApplication([])
window = MainWindow(
    settings_path=settings,
    default_output_folder=output,
    log_directory=root / "logs",
)
window.show()
app.processEvents()
assert window.windowTitle() == "Sky CotL — Audio to JSON"
assert window.status_label.text() == "Waiting to start"
assert window.youtube_link_edit.isVisible()
assert window.source_label.text() == "YouTube link:"
assert not window.audio_file_edit.isVisible()
assert window.output_folder_edit.isReadOnly()
assert not hasattr(window, "output_path_edit")
assert not hasattr(window, "summary_view")
assert not hasattr(window, "log_view")

window.title_edit.setText("Automatic title")
window._title_suggestion.set_suggestion("Automatic title")
window.audio_radio.setChecked(True)
app.processEvents()
assert window.audio_file_edit.isVisible()
assert window.source_label.text() == "Audio file:"
assert not window.youtube_link_edit.isVisible()
assert window.title_edit.text() == ""
window.audio_file_edit.setText(str(audio))
window._source_edited(str(audio))
assert window.title_edit.text() == "Summertime"

window.title_edit.setText("My title")
window._title_suggestion.set_by_user("My title")
window.youtube_radio.setChecked(True)
app.processEvents()
assert window.youtube_link_edit.isVisible()
assert window.source_label.text() == "YouTube link:"
assert window.title_edit.text() == "My title"
window.youtube_link_edit.setText("https://www.youtube.com/watch?v=LSwXh1Y5thY")

class FakeJob:
    def __init__(self, config, progress_callback=None):
        self.config = config
        self.result = None
        self.failure = None
        self.started = False
    def start(self):
        self.started = True
    def cancel(self):
        pass

main_window_module.ConversionJob = FakeJob
window._start_job()
assert window._job.started
assert not window.start_button.isEnabled()
assert window.cancel_button.isEnabled()
for control in (window.youtube_radio, window.audio_radio, window.title_edit,
                window.author_edit, window.transcribed_by_edit,
                window.keep_midi_checkbox, window.change_output_button):
    assert not control.isEnabled()
assert window.cancel_button.isEnabled()

window._job.result = SimpleNamespace(
    json_path=output / "My title.json",
    conversion=SimpleNamespace(),
)
window._handle_progress(JobProgress(JobState.DONE, "done"))
assert window.status_label.text() == f"Done: saved to {output / 'My title.json'}"
assert window.start_button.isEnabled()
assert not window.cancel_button.isEnabled()

dialogs = []
QMessageBox.exec = lambda self: (
    dialogs.append((self.windowTitle(), self.text(), self.detailedText())) or 0
)
window._job = SimpleNamespace(
    result=None,
    failure=JobFailure(
        "Could not download audio from YouTube.",
        "technical only",
        "stderr tail: ERROR video unavailable",
    ),
)
window._handle_progress(JobProgress(JobState.FAILED, "failed"))
assert dialogs[-1] == (
    "Conversion failed",
    "Could not download audio from YouTube.",
    "stderr tail: ERROR video unavailable",
)

real_ensure = main_window_module.ensure_writable_directory
def deny_output_folder(_path):
    raise PermissionError("drive not ready")
main_window_module.ensure_writable_directory = deny_output_folder
window._job = None
window._start_job()
assert dialogs[-1] == (
    "Cannot write to the output folder",
    "Cannot write to the output folder. Choose another folder.",
    "drive not ready",
)
main_window_module.ensure_writable_directory = real_ensure

window.audio_radio.setChecked(True)
app.processEvents()
window.audio_file_edit.setText("https://youtube.com/watch?v=abc")
window._start_job()
assert dialogs[-1][0] == "Invalid input"
assert dialogs[-1][1] == "That looks like a link. Switch Source to YouTube link."

window._job = None
window._run_logger = create_run_logger(root / "logs")
window._handle_progress(
    JobProgress(JobState.DOWNLOADING, "[yt-dlp stderr] Warning: V\u1ebft M\u01b0a")
)
for handler in window._run_logger.handlers:
    handler.flush()
assert "V\u1ebft M\u01b0a" in (root / "logs" / "last_run.log").read_text(encoding="utf-8")

QMessageBox.critical = lambda *args: dialogs.append(args)
original_exception_hook = sys.excepthook
install_exception_hook(root / "logs")
try:
    raise ValueError("unexpected technical detail")
except ValueError as error:
    sys.excepthook(type(error), error, error.__traceback__)
sys.excepthook = original_exception_hook
assert dialogs[-1][1] == "Application error"
assert "unexpected technical detail" in (root / "logs" / "app_error.log").read_text(
    encoding="utf-8"
)

window.close()
app.processEvents()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=project_root,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
