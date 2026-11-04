"""Compare converted Sky notes with a reference transcription."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sky_cotl_studio.cli_output import safe_print
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import convert
from sky_cotl_studio.exporters.sky_studio import load
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import SkyNote

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MIDI_FIXTURE = _PROJECT_ROOT / "fixtures" / "test_output.mid"
_JSON_FIXTURE = _PROJECT_ROOT / "fixtures" / "Summertime.json"
_MAX_OFFSET_MS = 30_000
_COARSE_STEP_MS = 10
_ONSET_TOLERANCE_MS = 60


@dataclass(frozen=True)
class ComparisonReport:
    """Comparison metrics after applying the best time offset."""

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
    max_offset_ms: int = _MAX_OFFSET_MS,
    tolerance_ms: int = _ONSET_TOLERANCE_MS,
) -> ComparisonReport:
    """Find an unrestricted integer-ms offset and compare onset/key agreement."""
    if (
        not isinstance(max_offset_ms, int)
        or isinstance(max_offset_ms, bool)
        or max_offset_ms < 0
    ):
        raise ValueError("max_offset_ms must be a non-negative integer")
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
    best_offset = find_best_offset(
        converted_times,
        reference_times,
        max_offset_ms=max_offset_ms,
        tolerance_ms=tolerance_ms,
    )
    best_pairs = _match_onsets(
        converted_times,
        reference_times,
        best_offset,
        tolerance_ms,
    )

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


def find_best_offset(
    converted_times: Sequence[int],
    reference_times: Sequence[int],
    max_offset_ms: int = _MAX_OFFSET_MS,
    tolerance_ms: int = _ONSET_TOLERANCE_MS,
) -> int:
    """Search ±30 seconds coarsely, then refine the best integer-ms offset."""
    if max_offset_ms < 0 or tolerance_ms < 0:
        raise ValueError("offset range and tolerance must be non-negative")
    coarse_candidates = set(
        range(-max_offset_ms, max_offset_ms + 1, _COARSE_STEP_MS)
    )
    coarse_candidates.update((-max_offset_ms, max_offset_ms))
    best_coarse = max(
        coarse_candidates,
        key=lambda offset: _offset_score(
            converted_times,
            reference_times,
            offset,
            tolerance_ms,
        ),
    )
    fine_candidates = range(
        max(-max_offset_ms, best_coarse - _COARSE_STEP_MS),
        min(max_offset_ms, best_coarse + _COARSE_STEP_MS) + 1,
    )
    return max(
        fine_candidates,
        key=lambda offset: _offset_score(
            converted_times,
            reference_times,
            offset,
            tolerance_ms,
        ),
    )


def compare_files(
    *,
    midi_path: Path | None = None,
    json_converted_path: Path | None = None,
    reference_path: Path,
) -> ComparisonReport:
    """Load a MIDI or converted JSON and compare it with a reference JSON."""
    if (midi_path is None) == (json_converted_path is None):
        raise ValueError("Provide exactly one of midi_path or json_converted_path")
    if midi_path is not None:
        converted = convert(read_notes(midi_path), ConverterConfig()).sky_notes
    else:
        assert json_converted_path is not None
        _, converted = load(json_converted_path)
    _, reference = load(reference_path)
    return compare_notes(converted, reference)


def run_fixture_comparison() -> ComparisonReport:
    """Convert the default MIDI fixture and compare it to Summertime.json."""
    return compare_files(midi_path=_MIDI_FIXTURE, reference_path=_JSON_FIXTURE)


def main(argv: Sequence[str] | None = None) -> None:
    """Print comparison metrics for explicit files or the repository fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--midi", type=Path, help="Raw MIDI to convert and compare")
    source_group.add_argument(
        "--json-converted",
        type=Path,
        help="Already converted Sky Studio JSON",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        help="Reference Sky Studio JSON (required with --midi or --json-converted)",
    )
    args = parser.parse_args(argv)

    if args.midi is None and args.json_converted is None and args.reference is None:
        report = run_fixture_comparison()
    elif args.reference is None or (
        args.midi is None and args.json_converted is None
    ):
        parser.error("--reference must be used with exactly one comparison input")
    else:
        report = compare_files(
            midi_path=args.midi,
            json_converted_path=args.json_converted,
            reference_path=args.reference,
        )

    _print_report(report)


def _print_report(report: ComparisonReport) -> None:
    safe_print(f"Best offset: {report.offset_ms} ms")
    safe_print(
        f"Onset matches: {report.matched_onsets}/{report.predicted_onsets} predicted, "
        f"{report.matched_onsets}/{report.reference_onsets} reference"
    )
    safe_print(f"Onset precision: {report.precision:.4f}")
    safe_print(f"Onset recall: {report.recall:.4f}")
    safe_print(f"Onset F1: {report.f1:.4f}")
    safe_print(f"Matched times with at least one key match: {report.same_key_time_ratio:.4f}")
    safe_print(f"Exact (time, key) pairs: {report.exact_note_pairs}")
    safe_print(f"Note count delta (converted - reference): {report.note_count_delta}")
    safe_print(f"Duration delta (converted - reference): {report.duration_delta_ms} ms")


def _notes_by_time(notes: Sequence[SkyNote]) -> dict[int, set[int]]:
    notes_by_time: dict[int, set[int]] = defaultdict(set)
    for note in notes:
        if not isinstance(note.time_ms, int) or isinstance(note.time_ms, bool):
            raise TypeError("note times must be integers")
        if not isinstance(note.key, int) or isinstance(note.key, bool):
            raise TypeError("note keys must be integers")
        notes_by_time[note.time_ms].add(note.key)
    return dict(notes_by_time)


def _offset_score(
    converted_times: Sequence[int],
    reference_times: Sequence[int],
    offset_ms: int,
    tolerance_ms: int,
) -> tuple[int, int, int, int]:
    pairs = _match_onsets(converted_times, reference_times, offset_ms, tolerance_ms)
    residual_ms = sum(
        abs(converted_time + offset_ms - reference_time)
        for converted_time, reference_time in pairs
    )
    return (len(pairs), -residual_ms, -abs(offset_ms), -offset_ms)


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
