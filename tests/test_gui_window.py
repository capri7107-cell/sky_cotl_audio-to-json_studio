import os
import subprocess
import sys
from pathlib import Path


def test_main_window_status_failure_dialog_and_slim_layout_offscreen(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = str(project_root / "src")
    initialization = """
import sys
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QMessageBox
from sky_cotl_studio.converter.convert import ConversionResult, ConversionStats
from sky_cotl_studio.gui.logging_utils import install_exception_hook
from sky_cotl_studio.gui.main_window import MainWindow
from sky_cotl_studio.pipeline.job import JobFailure, JobProgress, JobState
from sky_cotl_studio.models import SkyNote

app = QApplication([])
window = MainWindow()
assert window.windowTitle()
assert window.start_button.isEnabled()
assert not hasattr(window, "summary_view")
assert not hasattr(window, "log_view")
assert window.status_label.text() == "Ch\u1edd b\u1eaft \u0111\u1ea7u"
assert any(
    label.text() == "T\u1ec7p \u00e2m thanh ho\u1eb7c li\u00ean k\u1ebft YouTube:"
    for label in window.findChildren(type(window.status_label))
)
window._handle_progress(
    JobProgress(JobState.DOWNLOADING, "Downloading", 42.5, "V\u1ebft M\u01b0a")
)
assert window.status_label.text() == "\u0110ang t\u1ea3i video YouTube (42%)"
assert window.progress_bar.value() == 42
assert window.title_edit.text() == "V\u1ebft M\u01b0a"
assert Path(window.output_path_edit.text()).name == "V\u1ebft M\u01b0a.json"

conversion = ConversionResult(
    sky_notes=[SkyNote(time_ms=0, key=1)],
    transpose=0,
    grid_ms=119.99,
    warnings=[],
    stats=ConversionStats(
        input_note_count=1, merged_onset_count=1, deduplicated_count=0,
        chord_trimmed_count=0, output_note_count=649, distinct_time_count=1,
        max_chord_size=1, folded_count=0, out_of_scale_count=18,
    ),
)
window._job = SimpleNamespace(result=SimpleNamespace(conversion=conversion), failure=None)
window._handle_progress(JobProgress(JobState.DONE, "done"))
assert window.status_label.text() == (
    "Ho\u00e0n t\u1ea5t: 649 n\u1ed1t, l\u01b0\u1edbi 119,99 ms, 18 n\u1ed1t ngo\u00e0i thang \u00e2m"
)

dialogs = []
QMessageBox.critical = lambda *args: dialogs.append(args)
window._job = SimpleNamespace(
    result=None,
    failure=JobFailure("The output JSON could not be created.", "technical details"),
)
window._handle_progress(JobProgress(JobState.FAILED, "failed"))
assert len(dialogs) == 1
assert dialogs[0][2] == "Kh\u00f4ng th\u1ec3 t\u1ea1o t\u1ec7p JSON \u0111\u1ea7u ra."
assert "technical details" not in repr(dialogs)
original_exception_hook = sys.excepthook
install_exception_hook(Path(sys.argv[1]))
try:
    raise ValueError("unexpected technical detail")
except ValueError as error:
    sys.excepthook(type(error), error, error.__traceback__)
sys.excepthook = original_exception_hook
assert len(dialogs) == 2
assert dialogs[1][1] == "L\u1ed7i \u1ee9ng d\u1ee5ng"
assert "unexpected technical detail" in (Path(sys.argv[1]) / "app_error.log").read_text(
    encoding="utf-8"
)
window._job = None
window.close()
app.processEvents()
"""
    completed = subprocess.run(
        [sys.executable, "-c", initialization, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=project_root,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
