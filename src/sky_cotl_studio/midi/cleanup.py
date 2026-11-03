"""MIDI note cleanup operations."""

from dataclasses import replace

from sky_cotl_studio.models import Note


def trim_leading_silence(notes: list[Note]) -> tuple[list[Note], float]:
    """Shift the earliest note to zero and return the removed offset in milliseconds."""
    if not notes:
        return [], 0.0

    offset_ms = min(note.time_ms for note in notes)
    return [
        replace(note, time_ms=note.time_ms - offset_ms)
        for note in notes
    ], offset_ms
