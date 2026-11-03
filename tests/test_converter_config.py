import pytest

from sky_cotl_studio.converter.config import ConverterConfig


def test_converter_config_defaults() -> None:
    assert ConverterConfig() == ConverterConfig(
        grid_ms=120,
        merge_ms=40,
        max_chord=4,
        grid_mode="auto",
    )


def test_converter_config_accepts_fixed_grid_mode() -> None:
    config = ConverterConfig(grid_mode="fixed", grid_ms=187)

    assert config.grid_mode == "fixed"
    assert config.grid_ms == 187


@pytest.mark.parametrize(
    ("grid_ms", "merge_ms", "max_chord", "grid_mode"),
    [
        (0, 40, 4, "auto"),
        (120, -1, 4, "auto"),
        (120, 40, 1, "auto"),
        (120, 40, 4, "unknown"),
    ],
)
def test_converter_config_rejects_invalid_values(
    grid_ms: float,
    merge_ms: float,
    max_chord: int,
    grid_mode: str,
) -> None:
    with pytest.raises(ValueError):
        ConverterConfig(
            grid_ms=grid_ms,
            merge_ms=merge_ms,
            max_chord=max_chord,
            grid_mode=grid_mode,
        )
