from pathlib import Path

from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import convert
from sky_cotl_studio.exporters.sky_studio import export, load
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import Note

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIDI_FIXTURE = PROJECT_ROOT / "fixtures" / "test_output.mid"
JSON_FIXTURE = PROJECT_ROOT / "fixtures" / "Summertime.json"


def test_convert_fixture_through_exporter_and_loader(tmp_path: Path) -> None:
    notes = read_notes(MIDI_FIXTURE)
    metadata, _ = load(JSON_FIXTURE)

    result = convert(notes, ConverterConfig())
    output_path = tmp_path / "converted.json"
    output_path.write_text(export(metadata, result.sky_notes), encoding="utf-8")
    _, reloaded_notes = load(output_path)

    assert reloaded_notes == result.sky_notes
    assert result.transpose == -2
    assert result.grid_ms == 120
    assert result.sky_notes
    assert min(note.time_ms for note in reloaded_notes) == 0
    assert all(0 <= note.key <= 14 for note in reloaded_notes)
    assert all(note.time_ms % 120 == 0 for note in reloaded_notes)
    assert all(note.time_ms >= 0 for note in reloaded_notes)
    assert len({(note.time_ms, note.key) for note in reloaded_notes}) == len(reloaded_notes)
    assert all(warning.kind == "out_of_scale" for warning in result.warnings)
    assert result.stats.out_of_scale_count == len(result.warnings)
    assert result.stats.folded_count > 0
    metrics = (
        result.stats.output_note_count,
        result.stats.folded_count,
        result.stats.out_of_scale_count,
        result.stats.distinct_time_count,
        result.stats.max_chord_size,
        max(note.time_ms for note in reloaded_notes),
    )
    assert metrics == (649, 230, 18, 492, 2, 156720)


def test_convert_applies_configured_timing_and_chord_limit() -> None:
    notes = [
        Note(time_ms=50.0, duration_ms=100.0, pitch=pitch, velocity=90)
        for pitch in (60, 62, 64, 65, 67, 69)
    ]
    config = ConverterConfig(grid_ms=50, merge_ms=40, max_chord=3)

    result = convert(notes, config)

    assert {note.time_ms for note in result.sky_notes} == {0}
    assert len(result.sky_notes) == 3
    assert result.grid_ms == 50


def test_convert_stats_count_folded_and_out_of_scale_notes_separately() -> None:
    pitches = [38, *range(48, 60)]
    notes = [
        Note(time_ms=index * 120.0, duration_ms=100.0, pitch=pitch, velocity=90)
        for index, pitch in enumerate(pitches)
    ]

    result = convert(notes, ConverterConfig())

    assert result.stats.folded_count > 0
    assert result.stats.out_of_scale_count > 0
    assert result.stats.out_of_scale_count == len(result.warnings)
    assert all(warning.kind == "out_of_scale" for warning in result.warnings)
    assert all(warning.message for warning in result.warnings)
