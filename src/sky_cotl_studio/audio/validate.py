"""MP3 file validation and audio metadata extraction."""

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AudioValidationError(Exception):
    """Base error for MP3 validation failures."""


class AudioFileNotFoundError(AudioValidationError):
    """Raised when the requested audio file does not exist."""


class UnsupportedAudioFormatError(AudioValidationError):
    """Raised when the input is not an MP3 file."""


class AudioProbeError(AudioValidationError):
    """Raised when ffprobe cannot inspect the audio file."""


class AudioDecodeError(AudioValidationError):
    """Raised when ffmpeg cannot decode the audio file."""


class InvalidAudioMetadataError(AudioValidationError):
    """Raised when the audio stream has invalid or unsupported metadata."""


@dataclass(frozen=True)
class AudioInfo:
    """Validated audio properties required by transcription."""

    duration_seconds: float
    sample_rate: int
    channels: int


_PROCESS_TIMEOUT_SECONDS = 60


def validate_mp3(path: str | Path) -> AudioInfo:
    """Validate an MP3 file, decode it, and return its duration and stream format."""
    audio_path = Path(path)
    if not audio_path.exists() or not audio_path.is_file():
        raise AudioFileNotFoundError(f"Audio file does not exist: {audio_path}")
    if audio_path.suffix.lower() != ".mp3":
        raise UnsupportedAudioFormatError(f"Expected an MP3 file with .mp3 extension: {audio_path}")

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise AudioProbeError("ffprobe executable was not found on PATH")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioDecodeError("ffmpeg executable was not found on PATH")

    probe_result = _run_process(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-show_entries",
            "format=format_name,duration",
            "-of",
            "json",
            str(audio_path),
        ],
        AudioProbeError,
        "Could not read audio metadata",
    )
    metadata = _parse_metadata(probe_result.stdout, audio_path)

    _run_process(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-f",
            "null",
            "-",
        ],
        AudioDecodeError,
        "Could not decode audio",
    )
    return metadata


def _run_process(
    command: list[str],
    error_type: type[AudioValidationError],
    context: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=_PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise error_type(f"{context}: process timed out") from error
    except OSError as error:
        raise error_type(f"{context}: {error}") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or f"process exited with code {result.returncode}"
        raise error_type(f"{context}: {detail}")
    return result


def _parse_metadata(output: str, path: Path) -> AudioInfo:
    try:
        data = json.loads(output)
    except json.JSONDecodeError as error:
        raise AudioProbeError(f"ffprobe returned invalid metadata for {path}") from error
    if not isinstance(data, dict):
        raise AudioProbeError(f"ffprobe returned invalid metadata for {path}")

    streams = data.get("streams")
    container = data.get("format")
    if (
        not isinstance(streams, list)
        or not streams
        or not isinstance(streams[0], dict)
        or not isinstance(container, dict)
    ):
        raise InvalidAudioMetadataError(f"No readable audio stream found: {path}")

    stream = streams[0]
    codec_name = stream.get("codec_name")
    format_name = container.get("format_name")
    if codec_name != "mp3" or not isinstance(format_name, str) or "mp3" not in format_name:
        raise InvalidAudioMetadataError(f"Input is not an MP3 audio stream: {path}")

    try:
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        duration_seconds = float(container["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidAudioMetadataError(f"Incomplete audio metadata: {path}") from error

    if (
        sample_rate <= 0
        or channels <= 0
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0
    ):
        raise InvalidAudioMetadataError(f"Invalid audio duration or stream format: {path}")
    return AudioInfo(
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        channels=channels,
    )
