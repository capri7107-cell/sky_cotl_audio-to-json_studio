"""MIDI note extraction with tempo-map support."""

import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from mido import MidiFile

from sky_cotl_studio.models import Note

_DEFAULT_TEMPO = 500_000


def read_notes(
    path: str | Path,
    min_duration_ms: float = 30.0,
) -> list[Note]:
    """Read, pair, and filter notes from every track in a MIDI file."""
    if not math.isfinite(min_duration_ms) or min_duration_ms < 0:
        raise ValueError("min_duration_ms must be a finite non-negative number")

    midi_file = MidiFile(path)
    if midi_file.type == 2:
        raise ValueError("MIDI type 2 tracks have independent timelines and are unsupported")
    if midi_file.ticks_per_beat <= 0:
        raise ValueError("SMPTE time division is unsupported; MIDI must use ticks per beat")

    events: list[tuple[int, int, int, Any]] = []
    for track_index, track in enumerate(midi_file.tracks):
        absolute_tick = 0
        for event_index, message in enumerate(track):
            absolute_tick += message.time
            events.append((absolute_tick, track_index, event_index, message))
    events.sort(key=lambda event: (event[0], event[1], event[2]))

    active_notes: dict[tuple[int, int], deque[tuple[float, int]]] = defaultdict(deque)
    completed_notes: list[Note] = []
    tempo = _DEFAULT_TEMPO
    previous_tick = 0
    current_time_ms = 0.0

    for tick, _, _, message in events:
        tick_delta = tick - previous_tick
        current_time_ms += tick_delta * tempo / midi_file.ticks_per_beat / 1000
        previous_tick = tick

        if message.type == "set_tempo":
            tempo = message.tempo
            continue
        if message.is_meta or message.type not in ("note_on", "note_off"):
            continue

        note_key = (message.channel, message.note)
        if message.type == "note_on" and message.velocity > 0:
            active_notes[note_key].append((current_time_ms, message.velocity))
            continue

        if not active_notes[note_key]:
            raise ValueError(
                f"Unmatched note-off for pitch {message.note} on channel {message.channel}"
            )
        start_time_ms, velocity = active_notes[note_key].popleft()
        duration_ms = current_time_ms - start_time_ms
        if duration_ms >= min_duration_ms:
            completed_notes.append(
                Note(
                    time_ms=start_time_ms,
                    duration_ms=duration_ms,
                    pitch=message.note,
                    velocity=velocity,
                )
            )

    unfinished = [key for key, pending in active_notes.items() if pending]
    if unfinished:
        pitch, channel = unfinished[0][1], unfinished[0][0]
        raise ValueError(
            f"Missing note-off for pitch {pitch} on channel {channel}"
        )

    unique_notes = {
        (note.time_ms, note.duration_ms, note.pitch, note.velocity): note
        for note in completed_notes
    }
    return sorted(
        unique_notes.values(),
        key=lambda note: (note.time_ms, note.pitch, note.duration_ms, note.velocity),
    )
