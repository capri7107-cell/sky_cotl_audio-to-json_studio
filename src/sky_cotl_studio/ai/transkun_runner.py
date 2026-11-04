"""Subprocess-based Transkun transcription with progress and cancellation."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TextIO

from sky_cotl_studio.audio.validate import AudioInfo, validate_mp3

Device = Literal["cpu", "cuda"]
ProgressCallback = Callable[[str], None]
_STDERR_TAIL_LINES = 20
_STREAM_POLL_SECONDS = 0.05


class TranskunError(Exception):
    """Base error for transcription failures."""


class MissingFFmpegError(TranskunError):
    """Raised when the external FFmpeg decoder is unavailable."""


class TranskunDeviceError(TranskunError):
    """Raised when the requested device cannot be determined or used."""


class TranskunProcessError(TranskunError):
    """Raised when the Transkun subprocess cannot start or exits unsuccessfully."""


class TranskunOutputError(TranskunError):
    """Raised when Transkun does not create a non-empty MIDI output."""


class TranskunCancelledError(TranskunError):
    """Raised when transcription is cancelled."""


def transcribe(
    input_path: str | Path,
    output_path: str | Path,
    device: Device | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    validated_audio: AudioInfo | None = None,
) -> Path:
    """Validate an MP3 and transcribe it to MIDI in a cancellable subprocess."""
    source = Path(input_path)
    destination = Path(output_path)

    if device not in (None, "cpu", "cuda"):
        raise ValueError("device must be 'cpu', 'cuda', or None")
    if shutil.which("ffmpeg") is None:
        raise MissingFFmpegError("ffmpeg executable was not found on PATH")
    if cancel_event is not None and cancel_event.is_set():
        raise TranskunCancelledError("Transkun transcription was cancelled before it started")

    if validated_audio is None:
        validate_mp3(source)
    elif not isinstance(validated_audio, AudioInfo):
        raise TypeError("validated_audio must be an AudioInfo instance")
    selected_device = resolve_device(device)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = _temporary_output_path(destination)

    command = [
        _child_python_executable(),
        "-m",
        "transkun.transcribe",
        str(source),
        str(temporary_output),
        "--device",
        selected_device,
    ]
    try:
        _run_transkun(command, temporary_output, progress_callback, cancel_event)
        if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
            raise TranskunOutputError(
                f"Transkun exited successfully but did not create a MIDI output: {destination}"
            )
        os.replace(temporary_output, destination)
    except BaseException:
        _remove_partial_output(temporary_output)
        raise

    if progress_callback is not None:
        progress_callback("Transkun completed")
    return destination


def resolve_device(device: Device | None = None) -> Device:
    """Resolve an explicit device or select CUDA when it is available."""
    if device not in (None, "cpu", "cuda"):
        raise ValueError("device must be 'cpu', 'cuda', or None")
    return device if device is not None else ("cuda" if _cuda_available() else "cpu")


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError as error:
        raise TranskunDeviceError(
            "PyTorch is required to automatically select a CUDA or CPU device"
        ) from error
    return torch.cuda.is_available()


def _child_python_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.casefold() == "pythonw.exe":
        return str(executable.with_name("python.exe"))
    return sys.executable


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _temporary_output_path(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=".mid",
        dir=destination.parent,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _run_transkun(
    command: list[str],
    temporary_output: Path,
    progress_callback: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> None:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_creation_flags(),
        )
    except OSError as error:
        raise TranskunProcessError(f"Could not start Transkun: {error}") from error

    messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
    streams = (("stdout", process.stdout), ("stderr", process.stderr))
    readers = [
        threading.Thread(
            target=_read_stream,
            args=(stream_name, stream, messages),
            daemon=True,
        )
        for stream_name, stream in streams
        if stream is not None
    ]
    for reader in readers:
        reader.start()

    stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
    finished_streams = 0

    try:
        if progress_callback is not None:
            progress_callback("Transkun started")
        while finished_streams < len(readers):
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.wait()
                raise TranskunCancelledError("Transkun transcription was cancelled")

            try:
                stream_name, line = messages.get(timeout=_STREAM_POLL_SECONDS)
            except queue.Empty:
                if process.poll() is not None and all(not reader.is_alive() for reader in readers):
                    break
                continue

            if line is None:
                finished_streams += 1
                continue

            clean_line = line.rstrip("\r\n")
            if stream_name == "stderr":
                stderr_tail.append(clean_line)
            if clean_line and progress_callback is not None:
                progress_callback(clean_line)

        return_code = process.wait()
        if return_code != 0:
            tail = "\n".join(line for line in stderr_tail if line)
            detail = tail or "Transkun exited without reporting an error"
            raise TranskunProcessError(
                f"Transkun exited with code {return_code}. Stderr tail:\n{detail}"
            )
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        _remove_partial_output(temporary_output)
        raise
    finally:
        for reader in readers:
            reader.join(timeout=1)


def _read_stream(
    stream_name: str,
    stream: TextIO,
    messages: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        for line in stream:
            messages.put((stream_name, line))
    finally:
        stream.close()
        messages.put((stream_name, None))


def _remove_partial_output(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise TranskunOutputError(f"Could not remove partial MIDI output {path}: {error}") from error
