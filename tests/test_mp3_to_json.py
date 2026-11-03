import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from scripts.mp3_to_json import build_parser, run_mp3_to_json
from sky_cotl_studio.converter.convert import ConversionResult, ConversionStats
from sky_cotl_studio.models import SkyNote


def _conversion_result() -> ConversionResult:
    return ConversionResult(
        sky_notes=[SkyNote(time_ms=0, key=1), SkyNote(time_ms=120, key=2)],
        transpose=-2,
        grid_ms=120,
        warnings=[],
        stats=ConversionStats(
            input_note_count=2,
            merged_onset_count=2,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=2,
            distinct_time_count=2,
            max_chord_size=1,
            folded_count=0,
            out_of_scale_count=0,
        ),
    )


def test_mp3_cli_defaults_to_automatic_grid_and_accepts_fixed_mode() -> None:
    parser = build_parser()

    defaults = parser.parse_args(["input.mp3", "output.json"])
    fixed = parser.parse_args(
        ["input.mp3", "output.json", "--grid-mode", "fixed", "--grid-ms", "187"]
    )

    assert defaults.grid_mode == "auto"
    assert fixed.grid_mode == "fixed"
    assert fixed.grid_ms == 187


@pytest.mark.parametrize(
    "script_name",
    ["convert_midi.py", "mp3_to_json.py"],
)
def test_conversion_scripts_run_directly_without_pythonpath(script_name: str) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / script_name
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


def _mock_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def validate(_path: Path) -> object:
        calls.append("validate")
        return SimpleNamespace(duration_seconds=1.0, sample_rate=44100, channels=1)

    def transcribe(
        _input_path: Path,
        midi_path: Path,
        **kwargs: object,
    ) -> Path:
        calls.append("transcribe")
        assert kwargs["device"] == "cpu"
        midi_path.write_bytes(b"midi")
        return midi_path

    def read_notes(path: Path) -> list[object]:
        calls.append("read")
        assert path.suffix == ".mid"
        return []

    def trim(notes: list[object]) -> tuple[list[object], float]:
        calls.append("trim")
        return notes, 0.0

    def convert(_notes: list[object], _config: object) -> ConversionResult:
        calls.append("convert")
        return _conversion_result()

    def export(_meta: object, notes: list[SkyNote]) -> str:
        calls.append("export")
        return json.dumps([{"songNotes": [{"time": note.time_ms} for note in notes]}])

    monkeypatch.setattr("scripts.mp3_to_json.validate_mp3", validate)
    monkeypatch.setattr("scripts.mp3_to_json.transcribe", transcribe)
    monkeypatch.setattr("scripts.mp3_to_json.read_notes", read_notes)
    monkeypatch.setattr("scripts.mp3_to_json.trim_leading_silence", trim)
    monkeypatch.setattr("scripts.mp3_to_json.convert", convert)
    monkeypatch.setattr("scripts.mp3_to_json.export", export)
    monkeypatch.setattr("scripts.mp3_to_json.resolve_device", lambda _device: "cpu")
    return calls


def test_pipeline_runs_stages_and_removes_intermediate_midi_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_mp3 = tmp_path / "song.mp3"
    output_json = tmp_path / "song.json"
    input_mp3.write_bytes(b"audio")
    calls = _mock_pipeline(monkeypatch)

    report = run_mp3_to_json(input_mp3, output_json)

    assert calls == ["validate", "transcribe", "read", "trim", "convert", "export"]
    assert output_json.is_file()
    assert not list(tmp_path.glob("*.mid"))
    assert report.device == "cpu"
    assert set(report.phase_seconds) == {
        "validate",
        "transcribe",
        "read_midi",
        "trim",
        "convert",
        "export",
    }


def test_keep_midi_and_midi_out_option_preserve_transcription(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_mp3 = tmp_path / "song.mp3"
    output_json = tmp_path / "song.json"
    midi_out = tmp_path / "saved" / "transcription.mid"
    input_mp3.write_bytes(b"audio")
    _mock_pipeline(monkeypatch)

    run_mp3_to_json(input_mp3, output_json, midi_out=midi_out)

    assert midi_out.read_bytes() == b"midi"


def test_keep_midi_uses_default_path_next_to_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_mp3 = tmp_path / "song.mp3"
    output_json = tmp_path / "result.json"
    input_mp3.write_bytes(b"audio")
    _mock_pipeline(monkeypatch)

    run_mp3_to_json(input_mp3, output_json, keep_midi=True)

    assert (tmp_path / "result.mid").read_bytes() == b"midi"


def test_keyboard_interrupt_cleans_temporary_midi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_mp3 = tmp_path / "song.mp3"
    output_json = tmp_path / "song.json"
    input_mp3.write_bytes(b"audio")
    _mock_pipeline(monkeypatch)

    def interrupted_transcribe(
        _input_path: Path,
        midi_path: Path,
        **kwargs: object,
    ) -> Path:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, Event)
        midi_path.write_bytes(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr("scripts.mp3_to_json.transcribe", interrupted_transcribe)

    with pytest.raises(KeyboardInterrupt):
        run_mp3_to_json(input_mp3, output_json)

    assert not list(tmp_path.glob("*.mid"))
    assert not output_json.exists()


def test_run_mp3_to_json_rejects_midi_out_same_as_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_mp3 = tmp_path / "song.mp3"
    input_mp3.write_bytes(b"audio")
    _mock_pipeline(monkeypatch)

    with pytest.raises(ValueError, match="different"):
        run_mp3_to_json(input_mp3, tmp_path / "out.json", midi_out=input_mp3)
