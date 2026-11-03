import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from sky_cotl_studio.ai.transkun_runner import TranskunCancelledError
from sky_cotl_studio.converter.convert import ConversionResult, ConversionStats
from sky_cotl_studio.models import Note, SkyNote, SongMeta
from sky_cotl_studio.pipeline.job import (
    ConversionJob,
    ConversionJobConfig,
    JobState,
)


def _meta() -> SongMeta:
    return SongMeta(
        name="song",
        author="",
        transcribed_by="",
        is_composed=False,
        bpm=500,
        bits_per_page=16,
        pitch_level=2,
        is_encrypted=False,
    )


def _conversion() -> ConversionResult:
    return ConversionResult(
        sky_notes=[SkyNote(time_ms=0, key=1)],
        transpose=0,
        grid_ms=120,
        warnings=[],
        stats=ConversionStats(
            input_note_count=1,
            merged_onset_count=1,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=1,
            distinct_time_count=1,
            max_chord_size=1,
            folded_count=0,
            out_of_scale_count=0,
        ),
    )


def _config(tmp_path: Path, *, keep_midi: bool = False) -> ConversionJobConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    input_mp3 = tmp_path / "input.mp3"
    input_mp3.write_bytes(b"audio")
    return ConversionJobConfig(
        input_path=input_mp3,
        output_path=tmp_path / "output.json",
        metadata=_meta(),
        device="cpu",
        keep_midi=keep_midi,
    )


def _patch_services(monkeypatch: pytest.MonkeyPatch) -> list[str]:
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
        progress_callback = kwargs["progress_callback"]
        assert callable(progress_callback)
        progress_callback("Transkun started")
        midi_path.write_bytes(b"midi")
        progress_callback("Transkun completed")
        return midi_path

    def read_notes(path: Path) -> list[Note]:
        calls.append("read_midi")
        assert path.is_file()
        return [Note(time_ms=100.0, duration_ms=50.0, pitch=60, velocity=90)]

    def trim(notes: list[Note]) -> tuple[list[Note], float]:
        calls.append("trim")
        return notes, 100.0

    def convert(notes: list[Note], _config: object) -> ConversionResult:
        calls.append("convert")
        assert notes[0].time_ms == 100
        return _conversion()

    def export(_meta: SongMeta, sky_notes: list[SkyNote]) -> str:
        calls.append("export")
        return json.dumps([{"songNotes": [{"time": note.time_ms} for note in sky_notes]}])

    monkeypatch.setattr("sky_cotl_studio.pipeline.job.validate_mp3", validate)
    monkeypatch.setattr("sky_cotl_studio.pipeline.job.transcribe", transcribe)
    monkeypatch.setattr("sky_cotl_studio.pipeline.job.read_notes", read_notes)
    monkeypatch.setattr(
        "sky_cotl_studio.pipeline.job.trim_leading_silence",
        trim,
    )
    monkeypatch.setattr("sky_cotl_studio.pipeline.job.convert", convert)
    monkeypatch.setattr("sky_cotl_studio.pipeline.job.export", export)
    monkeypatch.setattr(
        "sky_cotl_studio.pipeline.job.resolve_device",
        lambda device: device or "cpu",
    )
    return calls


def test_job_runs_pipeline_in_background_and_reports_ordered_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_services(monkeypatch)
    callback_events = []
    callback_threads: list[int] = []
    caller_thread = threading.get_ident()
    job = ConversionJob(
        _config(tmp_path, keep_midi=True),
        progress_callback=lambda event: (
            callback_events.append(event),
            callback_threads.append(threading.get_ident()),
        ),
    )

    job.start()
    assert job.wait(timeout=5)

    state_transitions = [
        state
        for index, state in enumerate(event.phase for event in callback_events)
        if index == 0 or state is not callback_events[index - 1].phase
    ]
    assert state_transitions == [
        JobState.VALIDATING,
        JobState.TRANSCRIBING,
        JobState.CONVERTING,
        JobState.EXPORTING,
        JobState.DONE,
    ]
    assert all(thread_id != caller_thread for thread_id in callback_threads)
    assert calls == ["validate", "transcribe", "read_midi", "trim", "convert", "export"]
    assert job.state is JobState.DONE
    assert job.result is not None
    assert job.result.json_path.is_file()
    assert job.result.midi_path is not None and job.result.midi_path.is_file()
    assert job.result.conversion == _conversion()
    assert job.result.device == "cpu"
    assert set(job.result.phase_seconds) == {
        "validate",
        "transcribe",
        "read_midi",
        "trim",
        "convert",
        "export",
    }


def test_job_cancel_during_transcription_kills_and_cleans_staged_midi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_services(monkeypatch)
    entered_transcribe = threading.Event()

    def transcribe(
        _input_path: Path,
        midi_path: Path,
        **kwargs: object,
    ) -> Path:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, threading.Event)
        midi_path.write_bytes(b"partial")
        entered_transcribe.set()
        assert cancel_event.wait(timeout=5)
        raise TranskunCancelledError("cancelled")

    monkeypatch.setattr("sky_cotl_studio.pipeline.job.transcribe", transcribe)
    job = ConversionJob(_config(tmp_path, keep_midi=True))

    job.start()
    assert entered_transcribe.wait(timeout=5)
    job.cancel()
    assert job.wait(timeout=5)

    assert job.state is JobState.CANCELLED
    assert job.result is None
    assert job.failure is None
    assert not list(tmp_path.glob(".*.mid"))
    assert not (tmp_path / "output.mid").exists()
    assert not (tmp_path / "output.json").exists()


@pytest.mark.parametrize(
    ("failure_stage", "expected_user_message"),
    [
        ("validate", "The input MP3 could not be validated."),
        ("transcribe", "The MP3 could not be transcribed."),
        ("read_midi", "The generated MIDI could not be read."),
        ("trim", "The generated MIDI could not be processed."),
        ("convert", "The notes could not be converted."),
        ("export", "The output JSON could not be created."),
    ],
)
def test_job_reports_stage_failures_without_leaking_thread_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_user_message: str,
) -> None:
    _patch_services(monkeypatch)
    error = RuntimeError(f"technical failure in {failure_stage}")
    target_name = {
        "validate": "validate_mp3",
        "transcribe": "transcribe",
        "read_midi": "read_notes",
        "trim": "trim_leading_silence",
        "convert": "convert",
        "export": "export",
    }[failure_stage]
    monkeypatch.setattr(
        f"sky_cotl_studio.pipeline.job.{target_name}",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    job = ConversionJob(_config(tmp_path))

    job.start()

    assert job.wait(timeout=5)
    assert job.state is JobState.FAILED
    assert job.result is None
    assert job.failure is not None
    assert job.failure.user_message == expected_user_message
    assert "technical failure" in job.failure.technical_cause
    assert not list(tmp_path.glob(".*.mid"))


def test_only_one_job_can_run_at_a_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_services(monkeypatch)
    entered_validation = threading.Event()
    release_validation = threading.Event()

    def blocking_validate(_path: Path) -> object:
        entered_validation.set()
        assert release_validation.wait(timeout=5)
        return SimpleNamespace(duration_seconds=1.0, sample_rate=44100, channels=1)

    monkeypatch.setattr(
        "sky_cotl_studio.pipeline.job.validate_mp3",
        blocking_validate,
    )
    first = ConversionJob(_config(tmp_path))
    second = ConversionJob(_config(tmp_path / "second"))

    first.start()
    assert entered_validation.wait(timeout=5)
    with pytest.raises(RuntimeError, match="already running"):
        second.start()
    release_validation.set()
    assert first.wait(timeout=5)


def test_job_callback_messages_follow_pipeline_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_services(monkeypatch)
    messages: list[str] = []
    job = ConversionJob(
        _config(tmp_path),
        progress_callback=lambda event: messages.append(event.message),
    )

    job.start()
    assert job.wait(timeout=5)

    assert messages[0] == "Validating MP3"
    assert any("Transkun" in message for message in messages)
    assert messages.index("Converting MIDI notes") < messages.index("Exporting JSON")
    assert messages[-1] == "Conversion complete"
