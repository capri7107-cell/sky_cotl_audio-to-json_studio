"""Onset merging and chord-size limiting."""

import math
from collections.abc import Sequence
from dataclasses import replace
from statistics import median

from sky_cotl_studio.models import Note, SkyNote


def merge_close_onsets(notes: Sequence[Note], merge_ms: float) -> list[Note]:
    """Merge notes in adjacent onset clusters closer than merge_ms using their median."""
    if not math.isfinite(merge_ms) or merge_ms < 0:
        raise ValueError("merge_ms must be a finite non-negative number")
    if any(not math.isfinite(note.time_ms) for note in notes):
        raise ValueError("note onset times must be finite")

    ordered = sorted(
        notes,
        key=lambda note: (note.time_ms, note.pitch, note.duration_ms, note.velocity),
    )
    if not ordered:
        return []

    clusters: list[list[Note]] = []
    current_cluster = [ordered[0]]
    for note in ordered[1:]:
        onset_delta = note.time_ms - current_cluster[-1].time_ms
        if onset_delta == 0 or onset_delta < merge_ms:
            current_cluster.append(note)
        else:
            clusters.append(current_cluster)
            current_cluster = [note]
    clusters.append(current_cluster)

    merged: list[Note] = []
    for cluster in clusters:
        median_onset = float(median(note.time_ms for note in cluster))
        merged.extend(replace(note, time_ms=median_onset) for note in cluster)
    return merged


def limit_chord_size(notes: Sequence[SkyNote], max_chord: int) -> list[SkyNote]:
    """Deduplicate notes and cap each chord while retaining its lowest and highest keys."""
    if not isinstance(max_chord, int) or isinstance(max_chord, bool) or max_chord < 2:
        raise ValueError("max_chord must be an integer of at least 2")

    unique_notes = deduplicate_notes(notes)
    by_time: dict[int, list[SkyNote]] = {}
    for note in unique_notes:
        by_time.setdefault(note.time_ms, []).append(note)

    limited: list[SkyNote] = []
    for chord in by_time.values():
        if len(chord) <= max_chord:
            limited.extend(chord)
            continue

        selected = [chord[0], chord[-1]]
        remaining = chord[1:-1]
        while len(selected) < max_chord:
            selected.append(remaining.pop(0))
            if len(selected) < max_chord:
                selected.append(remaining.pop())
        limited.extend(selected)

    return sorted(limited, key=lambda note: (note.time_ms, note.key))


def deduplicate_notes(notes: Sequence[SkyNote]) -> list[SkyNote]:
    """Keep one note per (time, key) pair and return notes in stable order."""
    return sorted(set(notes), key=lambda note: (note.time_ms, note.key))
