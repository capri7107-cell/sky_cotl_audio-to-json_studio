"""Complete MIDI-note to Sky-note conversion."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from sky_cotl_studio.converter.chords import (
    deduplicate_notes,
    limit_chord_size,
    merge_close_onsets,
)
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.grid import estimate_lattice, quantize_lattice
from sky_cotl_studio.converter.mapping import MappingWarning, pitch_to_key
from sky_cotl_studio.converter.transpose import best_transpose
from sky_cotl_studio.models import Note, SkyNote


@dataclass(frozen=True)
class ConversionStats:
    """Counts describing pitch adjustments and the converted note collection."""

    input_note_count: int
    merged_onset_count: int
    deduplicated_count: int
    chord_trimmed_count: int
    output_note_count: int
    distinct_time_count: int
    max_chord_size: int
    folded_count: int
    out_of_scale_count: int


@dataclass(frozen=True)
class ConversionResult:
    """Converted notes, selected settings, warnings, and processing statistics."""

    sky_notes: list[SkyNote]
    transpose: int
    grid_ms: float
    warnings: list[MappingWarning]
    stats: ConversionStats


def convert(
    notes: Sequence[Note],
    config: ConverterConfig | None = None,
) -> ConversionResult:
    """Merge, quantize, transpose, map, deduplicate, and cap input MIDI notes."""
    converter_config = config if config is not None else ConverterConfig()
    if any(not isinstance(note, Note) for note in notes):
        raise TypeError("notes must contain only Note instances")
    if any(not math.isfinite(note.time_ms) for note in notes):
        raise ValueError("note onset times must be finite")

    merged_notes = merge_close_onsets(notes, converter_config.merge_ms)
    if not merged_notes:
        stats = ConversionStats(
            input_note_count=0,
            merged_onset_count=0,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=0,
            distinct_time_count=0,
            max_chord_size=0,
            folded_count=0,
            out_of_scale_count=0,
        )
        return ConversionResult([], 0, converter_config.grid_ms, [], stats)

    earliest_onset = min(note.time_ms for note in merged_notes)
    if converter_config.grid_mode == "auto":
        distinct_onsets = {note.time_ms for note in merged_notes}
        if len(distinct_onsets) < 5:
            grid_ms, phase_ms = converter_config.grid_ms, 0.0
        else:
            grid_ms, phase_ms = estimate_lattice(
                [note.time_ms - earliest_onset for note in merged_notes]
            )
    else:
        grid_ms, phase_ms = converter_config.grid_ms, 0.0
    normalized_notes = [
        replace(
            note,
            time_ms=float(
                quantize_lattice(
                    note.time_ms - earliest_onset,
                    grid_ms,
                    phase_ms,
                )
            ),
        )
        for note in merged_notes
    ]
    transpose = best_transpose([note.pitch for note in normalized_notes])

    sky_notes: list[SkyNote] = []
    warnings: list[MappingWarning] = []
    folded_count = 0
    out_of_scale_count = 0
    for note in normalized_notes:
        key, note_warnings = pitch_to_key(note.pitch, transpose)
        sky_notes.append(SkyNote(time_ms=int(note.time_ms), key=key))
        for warning in note_warnings:
            if warning.kind == "folded":
                folded_count += 1
            elif warning.kind == "out_of_scale":
                out_of_scale_count += 1
                warnings.append(warning)

    unique_sky_notes = deduplicate_notes(sky_notes)
    final_notes = limit_chord_size(unique_sky_notes, converter_config.max_chord)
    chord_sizes = Counter(note.time_ms for note in final_notes)
    stats = ConversionStats(
        input_note_count=len(notes),
        merged_onset_count=len({note.time_ms for note in merged_notes}),
        deduplicated_count=len(sky_notes) - len(unique_sky_notes),
        chord_trimmed_count=len(unique_sky_notes) - len(final_notes),
        output_note_count=len(final_notes),
        distinct_time_count=len(chord_sizes),
        max_chord_size=max(chord_sizes.values(), default=0),
        folded_count=folded_count,
        out_of_scale_count=out_of_scale_count,
    )
    return ConversionResult(
        sky_notes=final_notes,
        transpose=transpose,
        grid_ms=grid_ms,
        warnings=warnings,
        stats=stats,
    )
