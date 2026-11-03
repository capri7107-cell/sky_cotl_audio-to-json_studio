import io
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from sky_cotl_studio.ai.transkun_runner import (
    MissingFFmpegError,
    TranskunCancelledError,
    TranskunOutputError,
    TranskunProcessError,
    transcribe,
)


class _FakeProcess:
    def __init__(
        self,
        command: list[str],
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        create_output: Path | None = None,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.killed = False
        self.waited = False
        self.create_output = create_output is not None

    def poll(self) -> int | None:
        return -9 if self.killed else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        return self.poll() or 0

    def kill(self) -> None:
        self.killed = True


def _setup_runner(
    monkeypatch: pytest.MonkeyPatch,
    process: _FakeProcess,
    *,
    cuda_available: bool = False,
    ffmpeg: str | None = "ffmpeg",
) -> list[list[str]]:
    commands: list[list[str]] = []

    def fake_popen(command: list[str], **_: object) -> _FakeProcess:
        commands.append(command)
        if process.create_output:
            Path(command[4]).write_bytes(b"partial midi")
        return process

    monkeypatch.setattr(
        "sky_cotl_studio.ai.transkun_runner.validate_mp3",
        lambda _path: SimpleNamespace(duration_seconds=1.0, sample_rate=44100, channels=1),
    )
    monkeypatch.setattr(
        "sky_cotl_studio.ai.transkun_runner.shutil.which",
        lambda name: ffmpeg if name == "ffmpeg" else None,
    )
    monkeypatch.setattr(
        "sky_cotl_studio.ai.transkun_runner._cuda_available",
        lambda: cuda_available,
    )
    monkeypatch.setattr(
        "sky_cotl_studio.ai.transkun_runner.subprocess.Popen",
        fake_popen,
    )
    return commands


def test_transcribe_uses_current_interpreter_and_auto_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    process = _FakeProcess(
        [],
        stdout="starting transcription\nfinished segment\n",
        create_output=output_path,
    )
    commands = _setup_runner(monkeypatch, process, cuda_available=True)
    progress: list[str] = []

    result = transcribe(input_path, output_path, progress_callback=progress.append)

    assert result == output_path
    assert commands[0][:3] == [sys.executable, "-m", "transkun.transcribe"]
    assert commands[0][-2:] == ["--device", "cuda"]
    assert "Transkun started" in progress[0]
    assert "starting transcription" in progress
    assert "Transkun completed" in progress[-1]
    assert process.waited


def test_transcribe_auto_selects_cpu_when_cuda_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    process = _FakeProcess([], create_output=output_path)
    commands = _setup_runner(monkeypatch, process, cuda_available=False)

    transcribe(input_path, output_path)

    assert commands[0][-2:] == ["--device", "cpu"]


def test_transcribe_allows_device_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    process = _FakeProcess([], create_output=output_path)
    commands = _setup_runner(monkeypatch, process, cuda_available=False)

    transcribe(input_path, output_path, device="cuda")

    assert commands[0][-2:] == ["--device", "cuda"]


def test_transcribe_reports_only_start_and_end_when_process_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    process = _FakeProcess([], create_output=output_path)
    _setup_runner(monkeypatch, process)
    progress: list[str] = []

    transcribe(input_path, output_path, progress_callback=progress.append)

    assert progress == ["Transkun started", "Transkun completed"]


def test_transcribe_rejects_invalid_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"audio")
    _setup_runner(monkeypatch, _FakeProcess([]))

    with pytest.raises(ValueError, match="device"):
        transcribe(input_path, tmp_path / "output.mid", device="tpu")


def test_transcribe_validates_audio_before_launching_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"audio")
    commands = _setup_runner(monkeypatch, _FakeProcess([]))
    expected_error = RuntimeError("invalid input")

    def fail_validation(_path: Path) -> None:
        raise expected_error

    monkeypatch.setattr(
        "sky_cotl_studio.ai.transkun_runner.validate_mp3",
        fail_validation,
    )

    with pytest.raises(RuntimeError, match="invalid input"):
        transcribe(input_path, tmp_path / "output.mid")
    assert commands == []


def test_transcribe_fails_clearly_when_ffmpeg_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"audio")
    _setup_runner(monkeypatch, _FakeProcess([]), ffmpeg=None)

    with pytest.raises(MissingFFmpegError, match="ffmpeg"):
        transcribe(input_path, tmp_path / "output.mid")


def test_transcribe_includes_stderr_tail_and_removes_partial_output_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    stderr = "".join(f"diagnostic line {index}\n" for index in range(30))
    process = _FakeProcess([], returncode=2, stderr=stderr, create_output=output_path)
    _setup_runner(monkeypatch, process)

    with pytest.raises(TranskunProcessError) as error:
        transcribe(input_path, output_path)

    assert "diagnostic line 19" in str(error.value)
    assert "diagnostic line 9\n" not in str(error.value)
    assert not output_path.exists()


def test_transcribe_reports_missing_output_and_removes_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    process = _FakeProcess([])
    _setup_runner(monkeypatch, process)

    with pytest.raises(TranskunOutputError, match="did not create"):
        transcribe(input_path, output_path)
    assert not output_path.exists()


def test_transcribe_cancellation_kills_process_and_removes_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mid"
    input_path.write_bytes(b"audio")
    process = _FakeProcess([], create_output=output_path)
    _setup_runner(monkeypatch, process)
    cancellation = threading.Event()
    progress: list[str] = []

    def cancel_after_start(message: str) -> None:
        progress.append(message)
        if message == "Transkun started":
            cancellation.set()

    with pytest.raises(TranskunCancelledError):
        transcribe(
            input_path,
            output_path,
            cancel_event=cancellation,
            progress_callback=cancel_after_start,
        )

    assert process.killed
    assert process.waited
    assert not output_path.exists()


@pytest.mark.gpu
def test_real_transkun_on_synthetic_mp3(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for the Transkun integration test")

    input_path = tmp_path / "silence.mp3"
    output_path = tmp_path / "silence.mid"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "0.5",
            "-codec:a",
            "libmp3lame",
            str(input_path),
        ],
        check=True,
        timeout=30,
    )

    assert transcribe(input_path, output_path, device="cpu") == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
