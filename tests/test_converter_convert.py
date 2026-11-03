from itertools import pairwise
from pathlib import Path
from statistics import mean

import pytest

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
    assert 60 <= result.grid_ms <= 300
    assert result.sky_notes
    assert min(note.time_ms for note in reloaded_notes) == 0
    assert all(0 <= note.key <= 14 for note in reloaded_notes)
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
    assert abs(metrics[0] - 649) <= 2
    assert metrics[1:3] == (230, 18)
    assert metrics[3] >= 480
    assert metrics[4] <= 4


def test_convert_applies_configured_timing_and_chord_limit() -> None:
    notes = [
        Note(time_ms=50.0, duration_ms=100.0, pitch=pitch, velocity=90)
        for pitch in (60, 62, 64, 65, 67, 69)
    ]
    config = ConverterConfig(
        grid_mode="fixed",
        grid_ms=50,
        merge_ms=40,
        max_chord=3,
    )

    result = convert(notes, config)

    assert {note.time_ms for note in result.sky_notes} == {0}
    assert len(result.sky_notes) == 3
    assert result.grid_ms == 50


def test_fixed_grid_mode_quantizes_using_configured_grid() -> None:
    notes = [
        Note(time_ms=float(time_ms), duration_ms=100.0, pitch=67, velocity=90)
        for time_ms in (0, 100, 200)
    ]

    result = convert(notes, ConverterConfig(grid_mode="fixed", grid_ms=70, merge_ms=0))

    assert result.grid_ms == 70
    assert [note.time_ms for note in result.sky_notes] == [0, 70, 210]


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


def test_convert_reports_deduplicated_and_chord_trimmed_counts_separately() -> None:
    notes = [
        Note(time_ms=0.0, duration_ms=100.0, pitch=pitch, velocity=90)
        for pitch in (60, 60, 62, 64, 65, 67, 69)
    ]

    result = convert(notes, ConverterConfig(grid_ms=120, merge_ms=0, max_chord=3))

    assert result.stats.deduplicated_count == 1
    assert result.stats.chord_trimmed_count == 3
    assert result.stats.output_note_count == 3


def test_auto_grid_real_transkun_fixture_meets_timing_requirements() -> None:
    source_notes = read_notes(PROJECT_ROOT / "fixtures" / "transkun_real.mid")
    result = convert(source_notes, ConverterConfig())
    source_onsets = sorted({note.time_ms for note in source_notes})
    output_onsets = sorted({note.time_ms for note in result.sky_notes})
    differences = [
        later - earlier
        for earlier, later in pairwise(output_onsets)
    ]

    assert result.grid_ms == pytest.approx(187, abs=5) or result.grid_ms == pytest.approx(
        374,
        abs=5,
    )
    assert differences
    assert sum(
        abs(delta / result.grid_ms - round(delta / result.grid_ms)) < 0.01
        for delta in differences
    ) / len(differences) >= 0.95
    mean_nearest_error = mean(
        min(abs(onset - output) for output in output_onsets)
        for onset in source_onsets
    )
    assert mean_nearest_error <= 25
    assert max(output_onsets) == pytest.approx(44500, abs=500)


def test_auto_grid_handles_jittered_374_4_ms_synthetic_onsets() -> None:
    jitter_ms = [0, -17, 12, 19, -8, 6, -20, 14, -3, 18, -12, 5]
    notes = [
        Note(
            time_ms=index * 374.4 + jitter,
            duration_ms=100.0,
            pitch=67,
            velocity=90,
        )
        for index, jitter in enumerate(jitter_ms)
    ]

    result = convert(notes, ConverterConfig())
    output_onsets = sorted({note.time_ms for note in result.sky_notes})
    output_steps = [later - earlier for earlier, later in pairwise(output_onsets)]

    assert result.grid_ms == pytest.approx(187.2, abs=5) or result.grid_ms == pytest.approx(
        374.4,
        abs=5,
    )
    assert max(output_steps) - min(output_steps) <= 1
    assert all(step == pytest.approx(374.4, abs=1) for step in output_steps)
