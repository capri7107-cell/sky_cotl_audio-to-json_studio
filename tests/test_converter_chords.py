from sky_cotl_studio.converter.chords import (
    limit_chord_size,
    merge_close_onsets,
)
from sky_cotl_studio.models import Note, SkyNote


def test_merge_close_onsets_uses_median_for_synthetic_chord_cluster() -> None:
    notes = [
        Note(time_ms=100.0, duration_ms=200.0, pitch=60, velocity=90),
        Note(time_ms=125.0, duration_ms=200.0, pitch=64, velocity=90),
        Note(time_ms=139.0, duration_ms=200.0, pitch=67, velocity=90),
        Note(time_ms=300.0, duration_ms=200.0, pitch=72, velocity=90),
    ]

    merged = merge_close_onsets(notes, merge_ms=40)

    assert [note.time_ms for note in merged] == [125.0, 125.0, 125.0, 300.0]
    assert [note.pitch for note in merged] == [60, 64, 67, 72]


def test_limit_chord_size_caps_synthetic_six_note_chord_and_keeps_extremes() -> None:
    chord = [SkyNote(time_ms=120, key=key) for key in (0, 2, 4, 6, 8, 10)]

    limited = limit_chord_size(chord, max_chord=4)

    assert len(limited) == 4
    assert [note.key for note in limited] == [0, 2, 8, 10]


def test_limit_chord_size_deduplicates_before_enforcing_limit() -> None:
    notes = [
        SkyNote(time_ms=0, key=2),
        SkyNote(time_ms=0, key=2),
        SkyNote(time_ms=0, key=10),
        SkyNote(time_ms=120, key=5),
    ]

    assert limit_chord_size(notes, max_chord=2) == [
        SkyNote(time_ms=0, key=2),
        SkyNote(time_ms=0, key=10),
        SkyNote(time_ms=120, key=5),
    ]
