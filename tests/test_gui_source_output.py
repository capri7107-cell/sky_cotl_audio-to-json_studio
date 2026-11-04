import os
import subprocess
import sys
from pathlib import Path


def test_source_modes_output_settings_and_english_ui_offscreen(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = str(project_root / "src")
    script = r"""
import json
import re
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QLabel, QLineEdit,
    QPushButton, QRadioButton,
)
import sky_cotl_studio.gui.main_window as main_window_module
from sky_cotl_studio.gui.main_window import MainWindow
from sky_cotl_studio.settings import save_settings

root = Path(sys.argv[1])
settings = root / "settings.json"
default = root / "default output"
app = QApplication([])
window = MainWindow(
    settings_path=settings,
    default_output_folder=default,
    log_directory=root / "logs",
)
window.show()
app.processEvents()
assert window.windowTitle() == "Sky CotL — Audio to JSON"
assert window.youtube_radio.text() == "YouTube link"
assert window.audio_radio.text() == "Audio file"
assert window.source_label.text() == "YouTube link:"
assert window.youtube_link_edit.isVisible()
assert not window.audio_file_edit.isVisible()
assert window.output_folder_edit.isReadOnly()
assert not hasattr(window, "output_path_edit")

window.title_edit.setText("Video title")
window._title_suggestion.set_suggestion("Video title")
window.audio_radio.setChecked(True)
window._source_mode_changed()
assert window.audio_file_edit.isVisible()
assert window.source_label.text() == "Audio file:"
assert not window.youtube_link_edit.isVisible()
assert window.title_edit.text() == ""

window.youtube_radio.setChecked(True)
window._source_mode_changed()
assert window.youtube_link_edit.isVisible()
window.youtube_link_edit.setText("https://www.youtube.com/watch?v=LSwXh1Y5thY")
assert window._form().source_mode == "youtube"

chosen = root / "selected output"
dialog_arguments = []
initial_directory = str(window.output_directory)
QFileDialog.getExistingDirectory = lambda *args: (
    dialog_arguments.extend(args),
    str(chosen),
)[1]
window.change_output_button.click()
assert Path(window.output_folder_edit.full_path) == chosen.resolve()
assert dialog_arguments[2] == initial_directory
assert window._form().output_folder == str(chosen.resolve())
saved = json.loads(settings.read_text(encoding="utf-8"))
assert saved["output_directory"] == str(chosen.resolve())

gone = root / "gone output"
save_settings(settings, gone)
real_ensure = main_window_module.ensure_writable_directory
def deny_gone(path):
    if Path(path).resolve() == gone.resolve():
        raise PermissionError("drive unavailable")
    return real_ensure(path)
main_window_module.ensure_writable_directory = deny_gone
fallback = root / "fallback output"
fallback_window = MainWindow(
    settings_path=settings,
    default_output_folder=fallback,
    log_directory=root / "logs",
)
fallback_window.show()
app.processEvents()
assert fallback_window.output_directory == fallback.resolve()
assert fallback_window.folder_reminder_label.isVisible()
for handler in fallback_window._run_logger.handlers:
    handler.flush()
assert "Could not use saved output folder" in (
    root / "logs" / "last_run.log"
).read_text(encoding="utf-8")
fallback_window.close()

visible_strings = [window.windowTitle()]
for widget_type in (QLabel, QPushButton, QRadioButton, QCheckBox, QComboBox):
    for widget in window.findChildren(widget_type):
        if isinstance(widget, QComboBox):
            visible_strings.extend(
                [widget.currentText(), *(widget.itemText(index) for index in range(widget.count()))]
            )
        else:
            visible_strings.append(widget.text())
        visible_strings.append(widget.toolTip())
for widget in window.findChildren(QLineEdit):
    visible_strings.extend((widget.placeholderText(), widget.toolTip()))
for text in visible_strings:
    assert not re.search(r"[áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]", text, re.I), text

window.close()
app.processEvents()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=project_root,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
