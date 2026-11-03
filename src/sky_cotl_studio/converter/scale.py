"""Confirmed Sky instrument scale and MIDI pitch conversion."""

KEY0_MIDI_PITCH = 60
KEY_SEMITONE_OFFSETS = [
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


def key_to_pitch(key: int) -> int:
    """Return the MIDI pitch corresponding to a Sky key from 0 through 14."""
    if not isinstance(key, int) or isinstance(key, bool):
        raise TypeError("key must be an integer")
    if not 0 <= key < len(KEY_SEMITONE_OFFSETS):
        raise ValueError("key must be in the range 0..14")
    return KEY0_MIDI_PITCH + KEY_SEMITONE_OFFSETS[key]
