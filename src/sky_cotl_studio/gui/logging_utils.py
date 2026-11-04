"""UTF-8 file logging for GUI runs and uncaught application errors."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from types import TracebackType

from PySide6.QtWidgets import QMessageBox


def create_run_logger(log_directory: Path) -> logging.Logger:
    """Create a dedicated UTF-8 logger that overwrites the previous run log."""
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sky_cotl_studio.last_run")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _close_handlers(logger)
    handler = logging.FileHandler(
        log_directory / "last_run.log",
        mode="w",
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def install_exception_hook(log_directory: Path) -> None:
    """Log uncaught exceptions and show a non-technical GUI error dialog."""
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sky_cotl_studio.app_error")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    _close_handlers(logger)
    handler = logging.FileHandler(
        log_directory / "app_error.log",
        mode="a",
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: TracebackType | None,
    ) -> None:
        logger.error(
            "Uncaught application exception:\n%s",
            "".join(
                traceback.format_exception(
                    exception_type,
                    exception,
                    traceback_object,
                )
            ),
        )
        handler.flush()
        QMessageBox.critical(
            None,
            "Application error",
            "The application encountered an unexpected error. Details were saved to logs/app_error.log.",
        )

    sys.excepthook = handle_exception


def _close_handlers(logger: logging.Logger) -> None:
    for existing_handler in logger.handlers[:]:
        existing_handler.close()
        logger.removeHandler(existing_handler)
