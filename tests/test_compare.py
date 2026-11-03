from sky_cotl_studio.models import SkyNote
from tools.compare import compare_notes


def test_align_notes_finds_grid_offset_with_most_matching_onsets() -> None:
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

    report = compare_notes(converted, reference, grid_ms=120, search_steps=10)

    assert report.offset_ms == 240
    assert report.matched_onsets == 3
    assert report.precision == 0.75
    assert report.recall == 0.75
    assert report.f1 == 0.75
    assert report.same_key_time_ratio == 2 / 3
    assert report.exact_note_pairs == 2


def test_offset_search_is_limited_to_configured_grid_steps() -> None:
    converted = [SkyNote(time_ms=0, key=1), SkyNote(time_ms=120, key=2)]
    reference = [SkyNote(time_ms=600, key=1), SkyNote(time_ms=720, key=2)]

    report = compare_notes(converted, reference, grid_ms=120, search_steps=2)

    assert report.offset_ms == 0
    assert report.matched_onsets == 0
