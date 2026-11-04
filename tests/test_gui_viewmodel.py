from pathlib import Path

from sky_cotl_studio.converter.convert import ConversionResult, ConversionStats
from sky_cotl_studio.converter.mapping import MappingWarning
from sky_cotl_studio.gui.viewmodel import (
    ConversionForm,
    SuggestedField,
    build_job_config,
    device_from_label,
    failure_message,
    format_completion_status,
    format_summary,
    grid_mode_from_label,
    grid_ms_enabled,
    switch_source_mode,
    update_source_title,
    validate_form,
)
from sky_cotl_studio.models import SkyNote
from sky_cotl_studio.pipeline.job import ConversionJobResult


def _form(**overrides: object) -> ConversionForm:
    values: dict[str, object] = {
        "source_mode": "file",
        "input_source": "fixtures/test_output.mid",
        "output_folder": "output",
        "grid_mode": "auto",
        "grid_ms": "",
        "device": "auto",
        "title": "Song title",
        "author": "Author",
        "transcribed_by": "Transcriber",
        "keep_midi": False,
    }
    values.update(overrides)
    return ConversionForm(**values)  # type: ignore[arg-type]


def test_form_validation_is_source_mode_specific_and_checks_existing_files() -> None:
    assert validate_form(_form()) == ()
    assert validate_form(_form(input_source="missing.mp3"), require_input_exists=True) == (
        "Choose an existing audio file.",
    )
    assert validate_form(_form(input_source="https://youtu.be/abc")) == (
        "That looks like a link. Switch Source to YouTube link.",
    )
    assert validate_form(_form(input_source="")) == ("Choose an audio file.",)
    assert validate_form(_form(source_mode="youtube", input_source="")) == (
        "Enter a YouTube link.",
    )


def test_youtube_form_uses_existing_url_validation_without_auto_detection() -> None:
    link = "www.youtube.com/watch?v=LSwXh1Y5thY"
    assert validate_form(_form(source_mode="youtube", input_source=link)) == ()
    assert validate_form(
        _form(source_mode="youtube", input_source="https://example.com/watch?v=x")
    ) == ("Only YouTube links are supported.",)
    assert validate_form(
        _form(source_mode="youtube", input_source="https://youtube.com/watch")
    ) == ("This link has no video ID.",)


def test_suggested_title_tracks_source_but_user_title_survives_mode_switch() -> None:
    title = SuggestedField()
    assert update_source_title("C:/music/Vết Mưa.mp3", "file", title) == "Vết Mưa"
    assert title.is_suggested
    assert switch_source_mode(title) == ""
    assert update_source_title(
        "https://youtu.be/example",
        "youtube",
        title,
        video_title="Vết Mưa = Piano",
    ) == "Vết Mưa = Piano"
    title.set_by_user("My chosen song")
    assert switch_source_mode(title) == "My chosen song"
    assert not title.is_suggested


def test_job_config_uses_output_folder_and_non_overwrite_policy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "CON.mp3"
    source.write_bytes(b"audio")
    config = build_job_config(
        _form(
            input_source=str(source),
            output_folder="C:/exports",
            title="CON",
            keep_midi=True,
        )
    )
    assert config.input_path == source
    assert config.output_path.parent == Path("C:/exports")
    assert config.output_path.name == "untitled.json"
    assert config.metadata.name == "_CON"
    assert config.avoid_overwrite
    assert config.keep_midi

    youtube_config = build_job_config(
        _form(
            source_mode="youtube",
            input_source="https://youtu.be/example",
            title="",
        )
    )
    assert youtube_config.input_url == "https://youtu.be/example"
    assert youtube_config.metadata.name == ""


def test_english_failure_messages_and_grid_labels() -> None:
    assert failure_message("The YouTube video exceeds the duration limit.") == (
        "The video is longer than the 15 minute limit."
    )
    assert failure_message("The downloaded audio file could not be read.") == (
        "The downloaded audio file could not be read."
    )
    assert grid_mode_from_label("Automatic") == "auto"
    assert grid_mode_from_label("Fixed") == "fixed"
    assert grid_ms_enabled("fixed")
    assert not grid_ms_enabled("auto")
    assert device_from_label("Automatic") == "auto"
    assert device_from_label("CUDA") == "cuda"
    assert device_from_label("CPU") == "cpu"


def test_summary_and_completion_status_are_english_and_include_saved_path() -> None:
    conversion = ConversionResult(
        sky_notes=[SkyNote(time_ms=0, key=1)],
        transpose=-2,
        grid_ms=187.2,
        warnings=[
            MappingWarning(kind="out_of_scale", message="MIDI pitch 66 mapped to 67")
        ],
        stats=ConversionStats(
            input_note_count=4,
            merged_onset_count=2,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=649,
            distinct_time_count=1,
            max_chord_size=1,
            folded_count=1,
            out_of_scale_count=1,
        ),
    )
    result = ConversionJobResult(
        json_path=Path("output/song.json"),
        midi_path=None,
        conversion=conversion,
        device="cpu",
        phase_seconds={"validate": 0.1, "transcribe": 2.5},
        leading_silence_ms=30,
    )
    summary = format_summary(result)
    assert "Output notes: 649" in summary
    assert "Grid: 187.2 ms" in summary
    assert "Transpose: -2 semitones" in summary
    assert "transcribe: 2.500 s" in summary
    assert format_completion_status(result.json_path) == "Done: saved to output\\song.json"
