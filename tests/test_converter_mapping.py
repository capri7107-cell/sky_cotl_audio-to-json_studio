import pytest

from sky_cotl_studio.converter.mapping import pitch_to_key


def test_pitch_to_key_maps_first_seven_fixture_notes() -> None:
    pitches = [81, 81, 78, 83, 81, 76, 74]
    mapped = [pitch_to_key(pitch, -2) for pitch in pitches]

    assert [key for key, _ in mapped] == [11, 11, 9, 12, 11, 8, 7]
    assert all(not warnings for _, warnings in mapped)


def test_pitch_below_sky_range_is_folded_by_octaves() -> None:
    key, warnings = pitch_to_key(38, 0)

    assert key == 1
    assert [warning.kind for warning in warnings] == ["folded"]
    assert warnings[0].message is None


def test_pitch_outside_scale_is_mapped_to_nearest_key_with_warning() -> None:
    key, warnings = pitch_to_key(61, 0)

    assert key == 0
    assert [warning.kind for warning in warnings] == ["out_of_scale"]
    assert warnings[0].message is not None
    assert "61" in warnings[0].message
    assert "60" in warnings[0].message


def test_pitch_between_keys_chooses_lower_key() -> None:
    key, warnings = pitch_to_key(61, 0)

    assert key == 0
    assert warnings[0].kind == "out_of_scale"


def test_pitch_above_sky_range_is_folded_into_range() -> None:
    key, warnings = pitch_to_key(96, 0)

    assert key == 14
    assert [warning.kind for warning in warnings] == ["folded"]


def test_pitch_can_report_folding_and_out_of_scale_adjustments() -> None:
    key, warnings = pitch_to_key(37, 0)

    assert key == 0
    assert [warning.kind for warning in warnings] == ["folded", "out_of_scale"]


@pytest.mark.parametrize(
    ("pitch", "transpose", "exception"),
    [
        (-1, 0, ValueError),
        (128, 0, ValueError),
        (60, 1.5, TypeError),
    ],
)
def test_pitch_to_key_rejects_invalid_inputs(
    pitch: int,
    transpose: int,
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        pitch_to_key(pitch, transpose)
