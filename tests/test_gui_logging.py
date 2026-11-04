import sys

from sky_cotl_studio.cli_output import safe_print
from sky_cotl_studio.gui.logging_utils import create_run_logger


def test_safe_print_does_not_fail_when_stdout_is_none(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    safe_print("message")


def test_run_logger_writes_utf8_log_when_stdout_is_none(
    tmp_path,
    monkeypatch,
) -> None:
    logger = create_run_logger(tmp_path)
    original_stdout = sys.stdout
    try:
        monkeypatch.setattr(sys, "stdout", None)
        logger.info("Bắt đầu xử lý")
        logger.info("yt-dlp argv: --print title --no-simulate")
        logger.error("yt-dlp stderr: Không tìm thấy định dạng tiếng Việt")
        for handler in logger.handlers:
            handler.flush()
    finally:
        monkeypatch.setattr(sys, "stdout", original_stdout)
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    assert (tmp_path / "last_run.log").read_text(encoding="utf-8").count(
        "Bắt đầu xử lý"
    ) == 1
    log_content = (tmp_path / "last_run.log").read_text(encoding="utf-8")
    assert "yt-dlp argv: --print title --no-simulate" in log_content
    assert "yt-dlp stderr: Không tìm thấy định dạng tiếng Việt" in log_content
