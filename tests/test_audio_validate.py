import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sky_cotl_studio.audio.validate import (
    AudioDecodeError,
    AudioFileNotFoundError,
    AudioInfo,
    AudioProbeError,
    InvalidAudioMetadataError,
    UnsupportedAudioFormatError,
    validate_audio,
    validate_mp3,
)


def _mock_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    probe_data: dict[str, object] | None = None,
    decode_returncode: int = 0,
) -> list[list[str]]:
    commands: list[list[str]] = []
    probe_result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(
            probe_data
            if probe_data is not None
            else {
                "streams": [
                    {
                        "codec_name": "mp3",
                        "sample_rate": "22050",
                        "channels": 1,
                    }
                ],
                "format": {"format_name": "mp3", "duration": "0.5"},
            }
        ),
        stderr="",
    )
    decode_result = SimpleNamespace(
        returncode=decode_returncode,
        stdout="",
        stderr="corrupt frame" if decode_returncode else "",
    )
    results = [probe_result, decode_result]

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        return results.pop(0)

    monkeypatch.setattr("sky_cotl_studio.audio.validate.shutil.which", lambda name: name)
    monkeypatch.setattr("sky_cotl_studio.audio.validate.subprocess.run", fake_run)
    return commands


def test_validate_mp3_returns_decoded_audio_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"synthetic mocked audio")
    commands = _mock_ffmpeg(monkeypatch)

    info = validate_mp3(audio_path)

    assert info == AudioInfo(duration_seconds=0.5, sample_rate=22050, channels=1)
    assert len(commands) == 2
    assert str(audio_path) in commands[0]
    assert str(audio_path) in commands[1]


def test_validate_audio_accepts_wav_at_48khz(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"synthetic wav")
    commands = _mock_ffmpeg(
        monkeypatch,
        {
            "streams": [{"codec_name": "pcm_s16le", "sample_rate": "48000", "channels": 2}],
            "format": {"format_name": "wav", "duration": "12.5"},
        },
    )

    info = validate_audio(audio_path)

    assert info == AudioInfo(duration_seconds=12.5, sample_rate=48000, channels=2)
    assert len(commands) == 2


def test_validate_mp3_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AudioFileNotFoundError, match="does not exist"):
        validate_mp3(tmp_path / "missing.mp3")


def test_validate_mp3_rejects_non_mp3_extension(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"not an mp3")

    with pytest.raises(UnsupportedAudioFormatError, match="\\.mp3"):
        validate_mp3(audio_path)


def test_validate_mp3_reports_probe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "broken.mp3"
    audio_path.write_bytes(b"broken")
    monkeypatch.setattr("sky_cotl_studio.audio.validate.shutil.which", lambda name: name)
    monkeypatch.setattr(
        "sky_cotl_studio.audio.validate.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="invalid data",
        ),
    )

    with pytest.raises(AudioProbeError, match="invalid data"):
        validate_mp3(audio_path)


@pytest.mark.parametrize(
    "probe_data",
    [
        {
            "streams": [{"codec_name": "mp3", "sample_rate": "0", "channels": 1}],
            "format": {"format_name": "mp3", "duration": "1"},
        },
        {
            "streams": [{"codec_name": "mp3", "sample_rate": "22050", "channels": 1}],
            "format": {"format_name": "mp3", "duration": "0"},
        },
        {
            "streams": [{"codec_name": "wav", "sample_rate": "22050", "channels": 1}],
            "format": {"format_name": "wav", "duration": "1"},
        },
    ],
)
def test_validate_mp3_rejects_invalid_audio_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe_data: dict[str, object],
) -> None:
    audio_path = tmp_path / "invalid.mp3"
    audio_path.write_bytes(b"synthetic mocked audio")
    _mock_ffmpeg(monkeypatch, probe_data=probe_data)

    with pytest.raises(InvalidAudioMetadataError):
        validate_mp3(audio_path)


def test_validate_mp3_reports_decode_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "corrupt.mp3"
    audio_path.write_bytes(b"synthetic mocked audio")
    _mock_ffmpeg(monkeypatch, decode_returncode=1)

    with pytest.raises(AudioDecodeError, match="corrupt frame"):
        validate_mp3(audio_path)


def test_validate_mp3_reports_missing_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"synthetic mocked audio")
    monkeypatch.setattr(
        "sky_cotl_studio.audio.validate.shutil.which",
        lambda name: None if name == "ffprobe" else "ffmpeg",
    )

    with pytest.raises(AudioProbeError, match="ffprobe"):
        validate_mp3(audio_path)


def test_validate_mp3_reports_process_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"synthetic mocked audio")
    monkeypatch.setattr("sky_cotl_studio.audio.validate.shutil.which", lambda name: name)
    monkeypatch.setattr(
        "sky_cotl_studio.audio.validate.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="ffprobe", timeout=60)
        ),
    )

    with pytest.raises(AudioProbeError, match="timed out"):
        validate_mp3(audio_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows subprocess creation flag only")
def test_validate_mp3_disables_console_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"synthetic mocked audio")
    probe_result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(
            {
                "streams": [
                    {"codec_name": "mp3", "sample_rate": "22050", "channels": 1}
                ],
                "format": {"format_name": "mp3", "duration": "0.5"},
            }
        ),
        stderr="",
    )
    run_kwargs: list[dict[str, object]] = []
    results = [probe_result, SimpleNamespace(returncode=0, stdout="", stderr="")]

    def fake_run(*_args: object, **kwargs: object) -> SimpleNamespace:
        run_kwargs.append(kwargs)
        return results.pop(0)

    monkeypatch.setattr("sky_cotl_studio.audio.validate.shutil.which", lambda name: name)
    monkeypatch.setattr("sky_cotl_studio.audio.validate.subprocess.run", fake_run)

    validate_mp3(audio_path)

    assert len(run_kwargs) == 2
    assert all(
        kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
        for kwargs in run_kwargs
    )
