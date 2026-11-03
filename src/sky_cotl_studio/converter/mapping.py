"""Map transposed MIDI pitches to the Sky instrument's keys."""

from dataclasses import dataclass
from typing import Literal

from sky_cotl_studio.converter.scale import KEY0_MIDI_PITCH, KEY_SEMITONE_OFFSETS

MappingWarningKind = Literal["folded", "out_of_scale", "grid_fallback"]


@dataclass(frozen=True)
class MappingWarning:
    """A typed record of a pitch adjustment made during key mapping."""

    kind: MappingWarningKind
    message: str | None = None


def pitch_to_key(pitch: int, transpose: int) -> tuple[int, tuple[MappingWarning, ...]]:
    """Fold and map a MIDI pitch to its nearest Sky key, returning any warning."""
    if not isinstance(pitch, int) or isinstance(pitch, bool):
        raise TypeError("pitch must be an integer")
    if not 0 <= pitch <= 127:
        raise ValueError("pitch must be in the MIDI range 0..127")
    if not isinstance(transpose, int) or isinstance(transpose, bool):
        raise TypeError("transpose must be an integer")

    transposed_pitch = pitch + transpose
    folded_pitch = transposed_pitch
    while folded_pitch < KEY0_MIDI_PITCH:
        folded_pitch += 12
    while folded_pitch > KEY0_MIDI_PITCH + KEY_SEMITONE_OFFSETS[-1]:
        folded_pitch -= 12

    key = min(
        range(len(KEY_SEMITONE_OFFSETS)),
        key=lambda candidate: (
            abs(KEY0_MIDI_PITCH + KEY_SEMITONE_OFFSETS[candidate] - folded_pitch),
            KEY0_MIDI_PITCH + KEY_SEMITONE_OFFSETS[candidate],
        ),
    )
    mapped_pitch = KEY0_MIDI_PITCH + KEY_SEMITONE_OFFSETS[key]

    warnings: list[MappingWarning] = []
    if folded_pitch != transposed_pitch:
        warnings.append(MappingWarning(kind="folded"))
    if mapped_pitch != folded_pitch:
        warnings.append(
            MappingWarning(
                kind="out_of_scale",
                message=(
                    f"MIDI pitch {pitch} (after transpose {transpose}) "
                    f"mapped from {folded_pitch} to {mapped_pitch}"
                ),
            )
        )
    return key, tuple(warnings)
