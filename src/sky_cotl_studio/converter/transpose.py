"""Automatic transposition selection for the Sky C-major scale."""

from collections.abc import Sequence

_C_MAJOR_PITCH_CLASSES = frozenset((0, 2, 4, 5, 7, 9, 11))
_MIN_TRANSPOSE = -11
_MAX_TRANSPOSE = 11
_LOWEST_SKY_PITCH = 60
_HIGHEST_SKY_PITCH = 84


def best_transpose(pitches: Sequence[int]) -> int:
    """Choose the transposition maximizing scale fit, range fit, then proximity."""
    if not pitches:
        raise ValueError("pitches must contain at least one MIDI pitch")
    if any(not isinstance(pitch, int) or isinstance(pitch, bool) for pitch in pitches):
        raise TypeError("pitches must contain only integers")

    def score(transpose: int) -> tuple[int, int, int, int]:
        transposed = [pitch + transpose for pitch in pitches]
        in_scale = sum(
            pitch % 12 in _C_MAJOR_PITCH_CLASSES
            for pitch in transposed
        )
        in_range = sum(
            _LOWEST_SKY_PITCH <= pitch <= _HIGHEST_SKY_PITCH
            for pitch in transposed
        )
        return in_scale, in_range, -abs(transpose), -transpose

    return max(range(_MIN_TRANSPOSE, _MAX_TRANSPOSE + 1), key=score)
