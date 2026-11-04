"""Desktop application entry point."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from sky_cotl_studio.gui.logging_utils import install_exception_hook
from sky_cotl_studio.gui.main_window import MainWindow


def main() -> int:
    """Start the application event loop."""
    log_directory = Path(__file__).resolve().parents[3] / "logs"
    application = QApplication(sys.argv)
    install_exception_hook(log_directory)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
