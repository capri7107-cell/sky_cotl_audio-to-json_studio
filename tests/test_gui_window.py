import os
import subprocess
import sys
from pathlib import Path


def test_main_window_initializes_offscreen() -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = str(project_root / "src")
    initialization = (
        "from PySide6.QtWidgets import QApplication; "
        "from sky_cotl_studio.gui.main_window import MainWindow; "
        "app = QApplication([]); window = MainWindow(); "
        "assert window.windowTitle(); assert window.start_button.isEnabled(); "
        "window.close(); app.processEvents()"
    )
    completed = subprocess.run(
        [sys.executable, "-c", initialization],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=project_root,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
