import pytest

from sky_cotl_studio.converter.config import ConverterConfig


def test_converter_config_defaults() -> None:
    assert ConverterConfig() == ConverterConfig(
        grid_ms=120,
        merge_ms=40,
        max_chord=4,
    )


@pytest.mark.parametrize(
    ("grid_ms", "merge_ms", "max_chord"),
    [(0, 40, 4), (120, -1, 4), (120, 40, 1)],
)
def test_converter_config_rejects_invalid_values(
    grid_ms: float,
    merge_ms: float,
    max_chord: int,
) -> None:
    with pytest.raises(ValueError):
        ConverterConfig(grid_ms=grid_ms, merge_ms=merge_ms, max_chord=max_chord)
