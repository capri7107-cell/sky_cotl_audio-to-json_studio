from pathlib import Path

import pytest

from sky_cotl_studio.converter.transpose import best_transpose
from sky_cotl_studio.midi.reader import read_notes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIDI_FIXTURE = PROJECT_ROOT / "fixtures" / "test_output.mid"


def test_best_transpose_for_fixture_is_minus_two_semitones() -> None:
    notes = read_notes(MIDI_FIXTURE)

    assert len(notes) == 650
    assert best_transpose([note.pitch for note in notes]) == -2


def test_best_transpose_breaks_scale_score_ties_by_instrument_range() -> None:
    assert best_transpose([52]) == 8


def test_best_transpose_prefers_smallest_shift_when_scores_tie() -> None:
    assert best_transpose([60]) == 0


def test_best_transpose_requires_nonempty_integer_pitches() -> None:
    with pytest.raises(ValueError):
        best_transpose([])
