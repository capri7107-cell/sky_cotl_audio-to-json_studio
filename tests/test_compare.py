from pathlib import Path

from sky_cotl_studio.exporters.sky_studio import export
from sky_cotl_studio.models import SkyNote, SongMeta
from tools.compare import (
    compare_files,
    compare_notes,
    find_best_offset,
    run_fixture_comparison,
)


def test_auto_conversion_preserves_fixture_comparison_score() -> None:
    assert round(run_fixture_comparison().f1, 4) == 0.8878


def test_align_notes_finds_offset_with_most_matching_onsets() -> None:
    converted = [
        SkyNote(time_ms=0, key=1),
        SkyNote(time_ms=120, key=2),
        SkyNote(time_ms=360, key=3),
        SkyNote(time_ms=600, key=4),
    ]
    reference = [
        SkyNote(time_ms=240, key=1),
        SkyNote(time_ms=360, key=2),
        SkyNote(time_ms=600, key=9),
        SkyNote(time_ms=1080, key=4),
    ]

    report = compare_notes(converted, reference, max_offset_ms=1200)

    assert report.offset_ms == 240
    assert report.matched_onsets == 3
    assert report.precision == 0.75
    assert report.recall == 0.75
    assert report.f1 == 0.75
    assert report.same_key_time_ratio == 2 / 3
    assert report.exact_note_pairs == 2


def test_offset_search_is_limited_to_configured_range() -> None:
    converted = [SkyNote(time_ms=0, key=1), SkyNote(time_ms=120, key=2)]
    reference = [SkyNote(time_ms=600, key=1), SkyNote(time_ms=720, key=2)]

    report = compare_notes(converted, reference, max_offset_ms=200)

    assert report.offset_ms == 0
    assert report.matched_onsets == 0


def test_find_best_offset_handles_ungridded_onsets_with_timing_noise() -> None:
    converted_times = [0, 173, 521, 949, 1288, 1771, 2037, 2519, 2902, 3374, 3811]
    timing_noise = [-15, 12, -9, 6, 0, 15, -12, 9, -6, 3, -3]
    expected_offset = 17_423
    reference_times = [
        time_ms + expected_offset + noise
        for time_ms, noise in zip(converted_times, timing_noise, strict=True)
    ]

    assert find_best_offset(converted_times, reference_times) == expected_offset


def test_explicit_json_comparison_drops_layers_on_both_sides(tmp_path: Path) -> None:
    converted_json = tmp_path / "converted.json"
    reference_json = tmp_path / "reference.json"
    notes = [SkyNote(time_ms=0, key=3), SkyNote(time_ms=240, key=8)]
    meta = SongMeta(
        name="Test",
        author="",
        transcribed_by="",
        is_composed=False,
        bpm=500,
        bits_per_page=16,
        pitch_level=2,
        is_encrypted=False,
    )
    serialized = export(meta, notes)
    converted_json.write_text(
        serialized.replace('"key": "Key', '"key": "1Key'),
        encoding="utf-8",
    )
    reference_json.write_text(
        serialized.replace('"key": "Key', '"key": "2Key'),
        encoding="utf-8",
    )

    report = compare_files(
        json_converted_path=converted_json,
        reference_path=reference_json,
    )

    assert report.f1 == 1.0
    assert report.offset_ms == 0
    assert report.exact_note_pairs == 2
