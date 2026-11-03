import pytest

from sky_cotl_studio.converter.scale import (
    KEY0_MIDI_PITCH,
    KEY_SEMITONE_OFFSETS,
    key_to_pitch,
)


@pytest.mark.parametrize(
    ("key", "expected_pitch"),
    [(0, 60), (7, 72), (14, 84)],
)
def test_sky_key_to_midi_pitch(key: int, expected_pitch: int) -> None:
    assert key_to_pitch(key) == expected_pitch


def test_sky_scale_constants_match_confirmed_key_layout() -> None:
    assert KEY0_MIDI_PITCH == 60
    assert KEY_SEMITONE_OFFSETS == [
        0,
        2,
        4,
        5,
        7,
        9,
        11,
        12,
        14,
        16,
        17,
        19,
        21,
        23,
        24,
    ]


@pytest.mark.parametrize("key", [-1, 15])
def test_key_to_pitch_rejects_keys_outside_sky_range(key: int) -> None:
    with pytest.raises(ValueError):
        key_to_pitch(key)
