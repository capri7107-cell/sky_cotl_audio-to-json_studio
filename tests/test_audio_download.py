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
    "url",
    ["", "ftp://youtube.com/watch?v=x", "-o", "javascript:alert(1)", "https://evil.test/x"],
)
def test_invalid_youtube_urls_are_rejected_before_subprocess(
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
        self.stdout = StringIO("Vết Mưa\n")
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
    assert any(event.percentage == 42.5 for event in progress)
    assert os.name != "nt" or kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


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
        "https://media.example/video",
        allowed_domains=("media.example",),
    ) == "https://media.example/video"


@pytest.mark.network
def test_youtube_download_integration(tmp_path: Path) -> None:
    result = download_youtube(
        "https://www.youtube.com/watch?v=BaW_jenozKc",
        tmp_path,
        max_duration_seconds=30,
    )
    assert result.audio_path.is_file()
    assert result.audio_path.stat().st_size > 0
