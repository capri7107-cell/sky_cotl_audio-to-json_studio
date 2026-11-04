import os
import subprocess
import sys
import threading
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from sky_cotl_studio.audio.download import (
    DownloadCancelledError,
    DownloadError,
    DownloadProgress,
    _classify_download_failure,
    download_youtube,
    validate_youtube_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=LSwXh1Y5thY", "https://www.youtube.com/watch?v=LSwXh1Y5thY"),
        ("www.youtube.com/watch?v=LSwXh1Y5thY", "https://www.youtube.com/watch?v=LSwXh1Y5thY"),
        (" https://www.youtube.com/watch?v=LSwXh1Y5thY ", "https://www.youtube.com/watch?v=LSwXh1Y5thY"),
        ('"https://www.youtube.com/watch?v=LSwXh1Y5thY"', "https://www.youtube.com/watch?v=LSwXh1Y5thY"),
        ("https://youtube.com/watch?v=abc123", "https://youtube.com/watch?v=abc123"),
        ("https://youtu.be/abc123", "https://youtu.be/abc123"),
        ("https://www.youtube.com/shorts/abc123", "https://www.youtube.com/shorts/abc123"),
        ("https://music.youtube.com/watch?v=abc123", "https://music.youtube.com/watch?v=abc123"),
        ("https://m.youtube.com/watch?v=abc123", "https://m.youtube.com/watch?v=abc123"),
        ("https://youtube-nocookie.com/embed/abc123", "https://youtube-nocookie.com/embed/abc123"),
        ("https://www.youtube-nocookie.com/embed/abc123", "https://www.youtube-nocookie.com/embed/abc123"),
        ("https://www.youtube.com/watch?v=abc123&list=PLx", "https://www.youtube.com/watch?v=abc123&list=PLx"),
        ("https://youtu.be/abc123?t=42", "https://youtu.be/abc123?t=42"),
        ("https://youtube.com/watch?feature=share&v=abc123", "https://youtube.com/watch?feature=share&v=abc123"),
        ("https://YOUTUBE.COM/watch?v=abc123", "https://youtube.com/watch?v=abc123"),
        ("https://music.youtube.com/watch?v=abc123&si=tracking", "https://music.youtube.com/watch?v=abc123&si=tracking"),
        ("https://youtube.com.evil.com/watch?v=abc123", None),
        ("https://evilyoutube.com/watch?v=abc123", None),
        ("https://youtube.com@evil.com/watch?v=abc123", None),
        ("https://user:pass@youtube.com/watch?v=abc123", None),
        ("http://localhost/watch?v=abc123", None),
        ("ftp://youtube.com/watch?v=abc123", None),
        ("file://youtube.com/watch?v=abc123", None),
        ("javascript:alert(1)", None),
        ("-o", None),
        ("https://www.youtube.com/watch", None),
        ("https://youtu.be/", None),
        ("https://www.youtube.com/not-a-video", None),
        ("https://youtube.com/not-a-video?v=abc123", None),
    ],
)
def test_youtube_url_allowlist_and_normalization(
    url: str,
    expected: str | None,
) -> None:
    if expected is None:
        with pytest.raises(DownloadError):
            validate_youtube_url(url)
    else:
        assert validate_youtube_url(url) == expected


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://example.com/watch?v=x", "Only YouTube links are supported"),
        ("https://www.youtube.com/watch", "This link has no video ID"),
        ("https://youtu.be/", "This link has no video ID"),
        ("https://www.youtube.com/not-a-video", "This link is not formatted correctly"),
    ],
)
def test_youtube_url_errors_explain_the_reason(url: str, message: str) -> None:
    with pytest.raises(DownloadError, match=message):
        validate_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evilyoutube.com/watch?v=abc123",
        "https://youtube.com.evil.com/watch?v=abc123",
        "https://youtube.com@evil.com/watch?v=abc123",
        "http://localhost/watch?v=abc123",
        "ftp://youtube.com/watch?v=abc123",
        "file://youtube.com/watch?v=abc123",
        "javascript:alert(1)",
        "-o",
    ],
)
def test_invalid_urls_are_rejected_before_launching_ytdlp(
    url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("yt-dlp must not run for an invalid URL")

    monkeypatch.setattr("sky_cotl_studio.audio.download.subprocess.Popen", fail_if_called)

    with pytest.raises(DownloadError):
        download_youtube(url, tmp_path)

    assert not called
    assert not list(tmp_path.iterdir())


class _FakeProcess:
    def __init__(self, command: list[str], output_dir: Path) -> None:
        self.stdout = StringIO("SKYCOTL_TITLE=Vết Mưa\n")
        self.stderr = StringIO("[download]  42.5% of 4.00MiB at 2.00MiB/s\n")
        self.returncode = 0
        self.pid = 2345
        self.command = command
        (output_dir / "source.wav").write_bytes(b"wav")

    def poll(self) -> int | None:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        return int(self.returncode)


def test_download_builds_utf8_command_and_reports_progress_and_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> _FakeProcess:
        popen_calls.append((command, kwargs))
        return _FakeProcess(command, tmp_path)

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        fake_popen,
    )
    progress: list[DownloadProgress] = []

    result = download_youtube(
        "https://youtu.be/example",
        tmp_path,
        progress_callback=progress.append,
    )

    command, kwargs = popen_calls[0]
    assert command[0] == sys.executable
    assert command[1:4] == ["-m", "yt_dlp", "--no-playlist"]
    assert ["-x", "--audio-format", "wav", "--newline"] == [
        command[command.index("-x")],
        command[command.index("--audio-format")],
        command[command.index("--audio-format") + 1],
        command[command.index("--newline")],
    ]
    assert command[command.index("--match-filter") + 1] == "!is_live & duration <= 900"
    assert "--no-simulate" in command
    assert "--progress" in command
    assert command[command.index("-o") + 1].endswith("source.%(ext)s")
    assert command[-2:] == ["--", "https://youtu.be/example"]
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert result.title == "Vết Mưa"
    assert result.audio_path == tmp_path / "source.wav"
    assert result.stderr == "[download]  42.5% of 4.00MiB at 2.00MiB/s"
    assert any(event.percentage == 42.5 for event in progress)
    assert any(event.stream == "command" and "--no-simulate" in event.message for event in progress)
    assert any(event.stream == "stderr" and event.percentage == 42.5 for event in progress)
    assert os.name != "nt" or kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_print_option_does_not_simulate_instead_of_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_command: list[str] = []

    class PrintImpliesSimulationProcess(_FakeProcess):
        def __init__(self, command: list[str], output_dir: Path) -> None:
            captured_command.extend(command)
            self.command = command
            self.pid = 2345
            self.returncode = 0
            self.stdout = StringIO("Vết Mưa\n")
            self.stderr = StringIO("")
            if "--print" not in command or "--no-simulate" in command:
                (output_dir / "source.wav").write_bytes(b"wav")

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        lambda command, **_kwargs: PrintImpliesSimulationProcess(command, tmp_path),
    )

    result = download_youtube("https://youtube.com/watch?v=x", tmp_path)

    assert "--print" in captured_command
    assert "--no-simulate" in captured_command
    assert result.audio_path.is_file()


def test_title_is_read_only_from_prefixed_line_and_progress_never_becomes_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RealisticOutputProcess(_FakeProcess):
        def __init__(self, command: list[str], output_dir: Path) -> None:
            super().__init__(command, output_dir)
            self.stdout = StringIO(
                "SKYCOTL_TITLE=Vết Mưa = Piano Cover\n"
                "[download] 100% of 4.37MiB in 00:00:01 at 3.10MiB/s\n"
                "100% of 4.37MiB in 00:00:01 at 3.10MiB/s\n"
            )
            self.stderr = StringIO("")

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        lambda command, **_kwargs: RealisticOutputProcess(command, tmp_path),
    )
    progress: list[DownloadProgress] = []

    result = download_youtube(
        "https://youtube.com/watch?v=x",
        tmp_path,
        progress_callback=progress.append,
    )

    assert result.title == "Vết Mưa = Piano Cover"
    assert all(
        event.title is None or event.title == "Vết Mưa = Piano Cover"
        for event in progress
    )
    assert "--print" in result.argv
    assert "SKYCOTL_TITLE=%(title)s" in result.argv


def test_title_sanitization_preserves_unicode_equals_and_caps_length() -> None:
    from sky_cotl_studio.audio.download import sanitize_video_title

    assert sanitize_video_title("Vết Mưa = Piano") == "Vết Mưa = Piano"
    assert sanitize_video_title("  ") == ""
    assert sanitize_video_title("a\x00b\nc") == "abc"
    assert sanitize_video_title("x" * 140) == "x" * 120


def test_empty_prefixed_title_stays_empty_even_when_progress_is_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyTitleProcess(_FakeProcess):
        def __init__(self, command: list[str], output_dir: Path) -> None:
            super().__init__(command, output_dir)
            self.stdout = StringIO(
                "SKYCOTL_TITLE=\n"
                "[download] 100% of 4.37MiB in 00:00:01 at 3.10MiB/s\n"
            )
            self.stderr = StringIO("")

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        lambda command, **_kwargs: EmptyTitleProcess(command, tmp_path),
    )
    progress: list[DownloadProgress] = []

    result = download_youtube(
        "https://youtube.com/watch?v=x",
        tmp_path,
        progress_callback=progress.append,
    )

    assert result.title == ""
    assert all(event.title is None for event in progress)


def test_download_uses_python_exe_when_running_under_pythonw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "executable", r"C:\python-env\pythonw.exe")
    captured: list[list[str]] = []

    def fake_popen(command: list[str], **_kwargs: object) -> _FakeProcess:
        captured.append(command)
        return _FakeProcess(command, tmp_path)

    monkeypatch.setattr("sky_cotl_studio.audio.download.subprocess.Popen", fake_popen)
    download_youtube("https://youtube.com/watch?v=x", tmp_path)

    assert captured[0][0] == r"C:\python-env\python.exe"


def test_cancelled_download_kills_process_and_removes_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_event = threading.Event()
    killed: list[int] = []

    class RunningProcess(_FakeProcess):
        def __init__(self, command: list[str], output_dir: Path) -> None:
            super().__init__(command, output_dir)
            self.returncode = None
            cancel_event.set()

        def poll(self) -> int | None:
            return self.returncode

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        lambda command, **_kwargs: RunningProcess(command, tmp_path),
    )
    monkeypatch.setattr(
        "sky_cotl_studio.audio.download._terminate_process_tree",
        lambda process: killed.append(process.pid),
    )

    with pytest.raises(DownloadCancelledError):
        download_youtube(
            "https://youtube.com/watch?v=x",
            tmp_path,
            cancel_event=cancel_event,
        )

    assert killed == [2345]
    assert not (tmp_path / "source.wav").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree termination only")
def test_windows_cancellation_uses_taskkill_tree_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sky_cotl_studio.audio.download import _terminate_process_tree

    calls: list[tuple[list[str], dict[str, object]]] = []

    class Process:
        pid = 1234
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = -9
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.run",
        lambda command, **kwargs: (
            calls.append((command, kwargs)),
            SimpleNamespace(returncode=0),
        )[1],
    )
    process = Process()

    _terminate_process_tree(process)  # type: ignore[arg-type]

    assert calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert calls[0][1]["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert process.returncode == -9


def test_failed_download_removes_partial_output_and_maps_js_runtime_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedProcess(_FakeProcess):
        def __init__(self, command: list[str], output_dir: Path) -> None:
            super().__init__(command, output_dir)
            self.stderr = StringIO(
                "WARNING: No supported JavaScript runtime could be found\n"
                "ERROR: No video formats found\n"
            )
            self.returncode = 1

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        lambda command, **_kwargs: FailedProcess(command, tmp_path),
    )

    with pytest.raises(DownloadError) as error:
        download_youtube("https://youtube.com/watch?v=x", tmp_path)

    assert error.value.category == "javascript_runtime"
    assert not (tmp_path / "source.wav").exists()


def test_js_runtime_warning_does_not_fail_successful_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SuccessfulWarningProcess(_FakeProcess):
        def __init__(self, command: list[str], output_dir: Path) -> None:
            super().__init__(command, output_dir)
            self.stderr = StringIO(
                "WARNING: No supported JavaScript runtime could be found\n"
                "[download] 100.0% of 4.00MiB\n"
            )

    monkeypatch.setattr(
        "sky_cotl_studio.audio.download.subprocess.Popen",
        lambda command, **_kwargs: SuccessfulWarningProcess(command, tmp_path),
    )
    progress: list[DownloadProgress] = []

    result = download_youtube(
        "https://youtube.com/watch?v=x",
        tmp_path,
        progress_callback=progress.append,
    )

    assert result.title == "Vết Mưa"
    assert result.audio_path.is_file()
    assert any("No supported JavaScript runtime" in event.message for event in progress)


@pytest.mark.parametrize(
    ("output", "category"),
    [
        ("urlopen error: connection refused", "network"),
        ("ERROR: Private video", "unavailable"),
        ("ERROR: This video is age-restricted", "age_restricted"),
        ("ERROR: Video does not pass filter (duration <= 900)", "too_long"),
        ("ERROR: This is a livestream", "livestream"),
        ("ERROR: yt-dlp is outdated; please update yt-dlp", "outdated"),
        ("ERROR: No supported JavaScript runtime could be found", "javascript_runtime"),
    ],
)
def test_download_failures_are_classified(
    output: str,
    category: str,
) -> None:
    assert _classify_download_failure(output) == category


def test_progress_parser_rejects_non_progress_lines() -> None:
    from sky_cotl_studio.audio.download import parse_download_percentage

    assert parse_download_percentage("[download] 100.0% of 10MiB") == 100
    assert parse_download_percentage("No supported JavaScript runtime") is None
    assert validate_youtube_url(
        "https://media.example/watch?v=abc123",
        allowed_domains=("media.example",),
    ) == "https://media.example/watch?v=abc123"


@pytest.mark.network
def test_youtube_download_integration(tmp_path: Path) -> None:
    result = download_youtube(
        "https://www.youtube.com/watch?v=BaW_jenozKc",
        tmp_path,
        max_duration_seconds=30,
    )
    assert result.audio_path.is_file()
    assert result.audio_path.stat().st_size > 0
