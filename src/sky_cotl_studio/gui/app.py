"""Desktop application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from sky_cotl_studio.gui.main_window import MainWindow


def main() -> int:
    """Start the application event loop."""
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
