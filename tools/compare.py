"""Compare converted Sky notes with the transcribed fixture."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import convert
from sky_cotl_studio.exporters.sky_studio import load
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import SkyNote

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MIDI_FIXTURE = _PROJECT_ROOT / "fixtures" / "test_output.mid"
_JSON_FIXTURE = _PROJECT_ROOT / "fixtures" / "Summertime.json"


@dataclass(frozen=True)
class ComparisonReport:
    """Comparison metrics after applying the best grid-aligned time offset."""

    offset_ms: int
    matched_onsets: int
    predicted_onsets: int
    reference_onsets: int
    precision: float
    recall: float
    f1: float
    same_key_time_ratio: float
    exact_note_pairs: int
    note_count_delta: int
    duration_delta_ms: int


def compare_notes(
    converted: Sequence[SkyNote],
    reference: Sequence[SkyNote],
    grid_ms: int = 120,
    search_steps: int = 200,
    tolerance_ms: int = 60,
) -> ComparisonReport:
    """Find a grid-aligned offset and compare onset and key agreement metrics."""
    if not isinstance(grid_ms, int) or isinstance(grid_ms, bool) or grid_ms <= 0:
        raise ValueError("grid_ms must be a positive integer")
    if (
        not isinstance(search_steps, int)
        or isinstance(search_steps, bool)
        or search_steps < 0
    ):
        raise ValueError("search_steps must be a non-negative integer")
    if (
        not isinstance(tolerance_ms, int)
        or isinstance(tolerance_ms, bool)
        or tolerance_ms < 0
    ):
        raise ValueError("tolerance_ms must be a non-negative integer")

    converted_by_time = _notes_by_time(converted)
    reference_by_time = _notes_by_time(reference)
    converted_times = sorted(converted_by_time)
    reference_times = sorted(reference_by_time)

    best_offset = 0
    best_pairs: list[tuple[int, int]] = []
    for step in range(-search_steps, search_steps + 1):
        offset_ms = step * grid_ms
        pairs = _match_onsets(
            converted_times,
            reference_times,
            offset_ms,
            tolerance_ms,
        )
        if (len(pairs), -abs(offset_ms), -offset_ms) > (
            len(best_pairs),
            -abs(best_offset),
            -best_offset,
        ):
            best_offset = offset_ms
            best_pairs = pairs

    matched_onsets = len(best_pairs)
    precision = matched_onsets / len(converted_times) if converted_times else 0.0
    recall = matched_onsets / len(reference_times) if reference_times else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    matching_key_times = sum(
        bool(converted_by_time[converted_time] & reference_by_time[reference_time])
        for converted_time, reference_time in best_pairs
    )
    same_key_time_ratio = (
        matching_key_times / matched_onsets if matched_onsets else 0.0
    )

    converted_pairs = {
        (time_ms + best_offset, key)
        for time_ms, keys in converted_by_time.items()
        for key in keys
    }
    reference_pairs = {
        (time_ms, key)
        for time_ms, keys in reference_by_time.items()
        for key in keys
    }

    return ComparisonReport(
        offset_ms=best_offset,
        matched_onsets=matched_onsets,
        predicted_onsets=len(converted_times),
        reference_onsets=len(reference_times),
        precision=precision,
        recall=recall,
        f1=f1,
        same_key_time_ratio=same_key_time_ratio,
        exact_note_pairs=len(converted_pairs & reference_pairs),
        note_count_delta=len(converted) - len(reference),
        duration_delta_ms=_duration(converted) - _duration(reference),
    )


def run_fixture_comparison() -> ComparisonReport:
    """Convert the MIDI fixture and compare it to the transcribed JSON fixture."""
    _, reference_notes = load(_JSON_FIXTURE)
    result = convert(read_notes(_MIDI_FIXTURE), ConverterConfig())
    return compare_notes(
        result.sky_notes,
        reference_notes,
        grid_ms=int(result.grid_ms),
    )


def main() -> None:
    """Print comparison metrics for the repository fixtures."""
    report = run_fixture_comparison()
    print(f"Best offset: {report.offset_ms} ms")
    print(
        f"Onset matches: {report.matched_onsets}/{report.predicted_onsets} predicted, "
        f"{report.matched_onsets}/{report.reference_onsets} reference"
    )
    print(f"Onset precision: {report.precision:.4f}")
    print(f"Onset recall: {report.recall:.4f}")
    print(f"Onset F1: {report.f1:.4f}")
    print(f"Matched times with at least one key match: {report.same_key_time_ratio:.4f}")
    print(f"Exact (time, key) pairs: {report.exact_note_pairs}")
    print(f"Note count delta (converted - reference): {report.note_count_delta}")
    print(f"Duration delta (converted - reference): {report.duration_delta_ms} ms")


def _notes_by_time(notes: Sequence[SkyNote]) -> dict[int, set[int]]:
    notes_by_time: dict[int, set[int]] = defaultdict(set)
    for note in notes:
        if not isinstance(note.time_ms, int) or isinstance(note.time_ms, bool):
            raise TypeError("note times must be integers")
        if not isinstance(note.key, int) or isinstance(note.key, bool):
            raise TypeError("note keys must be integers")
        notes_by_time[note.time_ms].add(note.key)
    return dict(notes_by_time)


def _match_onsets(
    converted_times: Sequence[int],
    reference_times: Sequence[int],
    offset_ms: int,
    tolerance_ms: int,
) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    converted_index = 0
    reference_index = 0
    while converted_index < len(converted_times) and reference_index < len(reference_times):
        converted_time = converted_times[converted_index] + offset_ms
        reference_time = reference_times[reference_index]
        difference = converted_time - reference_time
        if abs(difference) <= tolerance_ms:
            pairs.append(
                (converted_times[converted_index], reference_times[reference_index])
            )
            converted_index += 1
            reference_index += 1
        elif difference < 0:
            converted_index += 1
        else:
            reference_index += 1
    return pairs


def _duration(notes: Sequence[SkyNote]) -> int:
    if not notes:
        return 0
    times = [note.time_ms for note in notes]
    return max(times) - min(times)


if __name__ == "__main__":
    main()
