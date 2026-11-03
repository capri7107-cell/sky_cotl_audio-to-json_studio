from pathlib import Path

import pytest

from sky_cotl_studio.converter.grid import estimate_grid, quantize, quantize_lattice
from sky_cotl_studio.midi.reader import read_notes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIDI_FIXTURE = PROJECT_ROOT / "fixtures" / "test_output.mid"


def test_estimate_grid_from_fixture_onsets() -> None:
    notes = read_notes(MIDI_FIXTURE)
    onsets = [note.time_ms for note in notes]

    assert estimate_grid(onsets) == pytest.approx(239.5833333333, abs=1e-6)


def test_estimate_grid_uses_dominant_interval_when_onsets_are_jittered() -> None:
    onsets = [0.0, 241.0, 480.0, 720.0, 1200.0]

    assert estimate_grid(onsets) == pytest.approx(240, abs=2)


@pytest.mark.parametrize(
    ("time_ms", "grid_ms", "expected"),
    [(0, 120, 0), (61, 120, 120), (179, 120, 120), (181, 120, 240)],
)
def test_quantize_rounds_to_nearest_grid(
    time_ms: float,
    grid_ms: float,
    expected: int,
) -> None:
    assert quantize(time_ms, grid_ms) == expected


def test_quantize_lattice_uses_phase_and_rounds_only_final_time() -> None:
    assert quantize_lattice(100.0, 187.2, 5.0) == 187
    assert quantize_lattice(374.0, 187.2, 5.0) == 374


@pytest.mark.parametrize("onsets", [[], [10.0]])
def test_estimate_grid_requires_at_least_two_onsets(onsets: list[float]) -> None:
    with pytest.raises(ValueError):
        estimate_grid(onsets)


@pytest.mark.parametrize("grid_ms", [0.0, -1.0, float("inf"), float("nan")])
def test_quantize_requires_a_positive_finite_grid(grid_ms: float) -> None:
    with pytest.raises(ValueError):
        quantize(120, grid_ms)
