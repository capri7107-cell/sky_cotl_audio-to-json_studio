"""Report conversion fidelity metrics for available MIDI fixtures."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from math import ceil, floor
from pathlib import Path
from statistics import median

from sky_cotl_studio.cli_output import safe_print
from sky_cotl_studio.converter.chords import merge_close_onsets
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import ConversionResult, convert
from sky_cotl_studio.converter.grid import (
    GridEstimationError,
    estimate_lattice,
    quantize_lattice,
)
from sky_cotl_studio.converter.mapping import pitch_to_key
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import Note

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FidelityReport:
    """Timing and note-count metrics for one converted MIDI file."""

    name: str
    input_note_count: int
    output_note_count: int
    deduplicated_count: int
    chord_trimmed_count: int
    grid_ms: float | None
    timing_median_ms: float
    timing_p90_ms: float
    timing_max_ms: float
    rounding_over_40_ratio: float
    rounding_over_40_count: int
    out_of_scale_ratio: float
    folded_ratio: float
    dedup_same_note_other_octave_ratio: float
    dedup_different_note_name_ratio: float
    max_chord_size: int
    min_onset_gap_ms: int | None
    notes_per_second: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class OutlierModeComparison:
    """Fidelity reports for snap and keep modes on one MIDI input."""

    snap: FidelityReport
    keep: FidelityReport


def analyze_midi(
    midi_path: Path,
    config: ConverterConfig | None = None,
) -> FidelityReport:
    """Read, convert, and report fidelity metrics for one MIDI file."""
    notes = read_notes(midi_path)
    return analyze_notes(midi_path.name, notes, config)


def analyze_notes(
    name: str,
    notes: Sequence[Note],
    config: ConverterConfig | None = None,
) -> FidelityReport:
    """Convert notes and compute timing, mapping, and density metrics."""
    converter_config = config if config is not None else ConverterConfig()
    result = convert(notes, converter_config)
    merged_notes = merge_close_onsets(notes, converter_config.merge_ms)
    residuals = _onset_residuals(merged_notes, result, converter_config)
    rounding_over_40_count = sum(residual > 40 for residual in residuals)
    dedup_same_octave_ratio, dedup_different_name_ratio = _deduplication_ratios(
        merged_notes,
        result,
    )
    distinct_output_times = sorted({note.time_ms for note in result.sky_notes})
    onset_gaps = [
        later - earlier
        for earlier, later in pairwise(distinct_output_times)
    ]
    count_for_mapping = len(merged_notes)
    duration_ms = (
        max(note.time_ms + note.duration_ms for note in notes)
        - min(note.time_ms for note in notes)
        if notes
        else 0.0
    )
    warnings = tuple(
        dict.fromkeys(
            warning.message
            for warning in result.warnings
            if warning.message
        )
    )

    return FidelityReport(
        name=name,
        input_note_count=result.stats.input_note_count,
        output_note_count=result.stats.output_note_count,
        deduplicated_count=result.stats.deduplicated_count,
        chord_trimmed_count=result.stats.chord_trimmed_count,
        grid_ms=result.grid_ms,
        timing_median_ms=median(residuals) if residuals else 0.0,
        timing_p90_ms=_percentile_90(residuals),
        timing_max_ms=max(residuals, default=0.0),
        rounding_over_40_ratio=(
            rounding_over_40_count / len(residuals) if residuals else 0.0
        ),
        rounding_over_40_count=rounding_over_40_count,
        out_of_scale_ratio=(
            result.stats.out_of_scale_count / count_for_mapping
            if count_for_mapping
            else 0.0
        ),
        folded_ratio=(
            result.stats.folded_count / count_for_mapping
            if count_for_mapping
            else 0.0
        ),
        dedup_same_note_other_octave_ratio=dedup_same_octave_ratio,
        dedup_different_note_name_ratio=dedup_different_name_ratio,
        max_chord_size=result.stats.max_chord_size,
        min_onset_gap_ms=min(onset_gaps) if onset_gaps else None,
        notes_per_second=(
            result.stats.output_note_count / (duration_ms / 1000)
            if duration_ms > 0
            else 0.0
        ),
        warnings=warnings,
    )


def discover_midi_files(project_root: Path = _PROJECT_ROOT) -> list[Path]:
    """Return local MIDI samples and root-level fixture MIDIs in stable order."""
    local_files = (project_root / "fixtures" / "local").glob("*.mid")
    root_files = (project_root / "fixtures").glob("*.mid")
    return sorted((*local_files, *root_files), key=lambda path: str(path).casefold())


def compare_outlier_modes(
    midi_path: Path,
    config: ConverterConfig | None = None,
) -> OutlierModeComparison:
    """Run fidelity analysis with both outlier policies for the same MIDI."""
    base_config = config if config is not None else ConverterConfig()
    notes = read_notes(midi_path)
    snap = analyze_notes(
        midi_path.name,
        notes,
        replace(base_config, grid_outliers="snap"),
    )
    keep = analyze_notes(
        midi_path.name,
        notes,
        replace(base_config, grid_outliers="keep"),
    )
    return OutlierModeComparison(snap=snap, keep=keep)


def main(argv: Sequence[str] | None = None) -> None:
    """Print fidelity metrics, optionally comparing both grid outlier modes."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compare-outliers",
        action="store_true",
        help="Compare snap and keep metrics on selected MIDI fixtures",
    )
    args = parser.parse_args(argv)
    if args.compare_outliers:
        _print_outlier_comparison()
        return

    reports = [analyze_midi(path) for path in discover_midi_files()]
    if not reports:
        safe_print("Không tìm thấy MIDI trong fixtures/ hoặc fixtures/local/.")
        return

    headers = (
        "Bài",
        "Nốt vào",
        "Nốt ra",
        "Khử trùng",
        "Cắt hợp âm",
        "Lưới (ms)",
        "Lệch trung vị",
        "Lệch P90",
        "Lệch tối đa",
        "Lệch >40 ms (%)",
        "Lệch >40 ms (n)",
        "Ngoài thang",
        "Gập quãng tám",
        "Khử trùng: khác quãng tám",
        "Khử trùng: khác tên nốt",
        "Hợp âm max",
        "Nốt/giây",
        "Khoảng min",
    )
    rows = [
        (
            report.name,
            str(report.input_note_count),
            str(report.output_note_count),
            str(report.deduplicated_count),
            str(report.chord_trimmed_count),
            f"{report.grid_ms:.2f}" if report.grid_ms is not None else "dự phòng",
            f"{report.timing_median_ms:.1f}",
            f"{report.timing_p90_ms:.1f}",
            f"{report.timing_max_ms:.1f}",
            f"{report.rounding_over_40_ratio:.1%}",
            str(report.rounding_over_40_count),
            f"{report.out_of_scale_ratio:.1%}",
            f"{report.folded_ratio:.1%}",
            f"{report.dedup_same_note_other_octave_ratio:.1%}",
            f"{report.dedup_different_note_name_ratio:.1%}",
            str(report.max_chord_size),
            f"{report.notes_per_second:.2f}",
            f"{report.min_onset_gap_ms} ms"
            if report.min_onset_gap_ms is not None
            else "—",
        )
        for report in reports
    ]
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]
    safe_print(
        "| "
        + " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
        + " |"
    )
    safe_print("|-" + "-|-".join("-" * width for width in widths) + "-|")
    for row in rows:
        safe_print(
            "| "
            + " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))
            + " |"
        )
    safe_print(
        "| "
        + " | ".join(
            value.ljust(widths[index])
            for index, value in enumerate(_summary_row(headers, rows))
        )
        + " |"
    )

    safe_print("\nCảnh báo:")
    warning_count = 0
    for report in reports:
        for warning in report.warnings:
            warning_count += 1
            safe_print(f"- {report.name}: {warning}")
    if not warning_count:
        safe_print("- Không có cảnh báo.")


def _print_outlier_comparison() -> None:
    requested_names = {
        "imagine dragons",
        "love story",
        "transkun_real",
        "dance monkey",
    }
    midi_files = [
        path
        for path in discover_midi_files()
        if path.stem.casefold() in requested_names
    ]
    comparisons = [compare_outlier_modes(path) for path in midi_files]
    headers = (
        "Bài",
        "Lưới (ms)",
        "Snap >40 ms (%)",
        "Snap >40 ms (n)",
        "Keep >40 ms (%)",
        "Keep >40 ms (n)",
        "Khoảng min snap",
        "Khoảng min keep",
    )
    rows = [
        (
            comparison.snap.name,
            f"{comparison.snap.grid_ms:.2f}"
            if comparison.snap.grid_ms is not None
            else "dự phòng",
            f"{comparison.snap.rounding_over_40_ratio:.1%}",
            str(comparison.snap.rounding_over_40_count),
            f"{comparison.keep.rounding_over_40_ratio:.1%}",
            str(comparison.keep.rounding_over_40_count),
            f"{comparison.snap.min_onset_gap_ms} ms"
            if comparison.snap.min_onset_gap_ms is not None
            else "—",
            f"{comparison.keep.min_onset_gap_ms} ms"
            if comparison.keep.min_onset_gap_ms is not None
            else "—",
        )
        for comparison in comparisons
    ]
    _print_table(headers, rows)


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    if not rows:
        safe_print("Không tìm thấy MIDI phù hợp để so sánh.")
        return
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]
    safe_print(
        "| "
        + " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
        + " |"
    )
    safe_print("|-" + "-|-".join("-" * width for width in widths) + "-|")
    for row in rows:
        safe_print(
            "| "
            + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
            + " |"
        )


def _onset_residuals(
    merged_notes: Sequence[Note],
    conversion: ConversionResult,
    config: ConverterConfig,
) -> list[float]:
    if not merged_notes or not conversion.sky_notes:
        return []
    first_onset = min(note.time_ms for note in merged_notes)
    if conversion.grid_ms is None:
        return [
            abs(
                (onset - first_onset)
                - floor(onset - first_onset + 0.5)
            )
            for onset in sorted({note.time_ms for note in merged_notes})
        ]
    if config.grid_mode == "fixed":
        grid_ms, phase_ms = config.grid_ms, 0.0
    else:
        try:
            grid_ms, phase_ms = estimate_lattice(
                [note.time_ms - first_onset for note in merged_notes]
            )
        except GridEstimationError:
            return [0.0] * len({note.time_ms for note in merged_notes})

    residuals = []
    for onset in sorted({note.time_ms for note in merged_notes}):
        relative_time = onset - first_onset
        index = floor((relative_time - phase_ms) / grid_ms + 0.5)
        lattice_point = phase_ms + index * grid_ms
        deviation = abs(relative_time - lattice_point)
        if config.grid_outliers == "keep" and deviation > config.outlier_ms:
            residuals.append(
                abs(relative_time - floor(relative_time + 0.5))
            )
        else:
            residuals.append(deviation)
    return residuals


def _deduplication_ratios(
    merged_notes: Sequence[Note],
    conversion: ConversionResult,
) -> tuple[float, float]:
    if not merged_notes or not conversion.stats.deduplicated_count:
        return 0.0, 0.0

    origin = min(note.time_ms for note in merged_notes)
    lattice: tuple[float, float] | None = None
    if conversion.grid_ms is not None:
        lattice = estimate_lattice(
            [note.time_ms - origin for note in merged_notes]
        )

    mapped_by_time_key: dict[tuple[int, int], list[int]] = {}
    for note in merged_notes:
        relative_time = note.time_ms - origin
        mapped_time = (
            floor(relative_time + 0.5)
            if lattice is None
            else quantize_lattice(relative_time, lattice[0], lattice[1])
        )
        key, _warnings = pitch_to_key(note.pitch, conversion.transpose)
        mapped_by_time_key.setdefault((mapped_time, key), []).append(note.pitch)

    same_note_other_octave = 0
    different_note_name = 0
    for pitches in mapped_by_time_key.values():
        if len(pitches) < 2:
            continue
        retained_pitch = pitches[0]
        for pitch in pitches[1:]:
            if pitch % 12 == retained_pitch % 12 and pitch != retained_pitch:
                same_note_other_octave += 1
            elif pitch % 12 != retained_pitch % 12:
                different_note_name += 1

    deduplicated_count = conversion.stats.deduplicated_count
    return (
        same_note_other_octave / deduplicated_count,
        different_note_name / deduplicated_count,
    )


def _summary_row(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> tuple[str, ...]:
    numeric_columns = {
        "Nốt vào",
        "Nốt ra",
        "Khử trùng",
        "Cắt hợp âm",
        "Lưới (ms)",
        "Lệch trung vị",
        "Lệch P90",
        "Lệch tối đa",
        "Lệch >40 ms (%)",
        "Lệch >40 ms (n)",
        "Ngoài thang",
        "Gập quãng tám",
        "Khử trùng: khác quãng tám",
        "Khử trùng: khác tên nốt",
        "Hợp âm max",
        "Nốt/giây",
        "Khoảng min",
    }
    summary = ["Min–max"]
    for index, header in enumerate(headers[1:], start=1):
        if header not in numeric_columns:
            summary.append("")
            continue
        values = []
        for row in rows:
            value = row[index]
            if value.endswith(" ms"):
                value = value.removesuffix(" ms")
            try:
                values.append(float(value.rstrip("%")))
            except ValueError:
                continue
        if values:
            suffix = "%" if "%" in rows[0][index] else ""
            if rows[0][index].endswith(" ms"):
                suffix = " ms"
            summary.append(f"{min(values):g}–{max(values):g}{suffix}")
        else:
            summary.append("—")
    return tuple(summary)


def _percentile_90(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, ceil(0.9 * len(ordered)) - 1)]


if __name__ == "__main__":
    main()
