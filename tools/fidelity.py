"""Report conversion fidelity metrics for available MIDI fixtures."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import ceil
from pathlib import Path
from statistics import median

from sky_cotl_studio.converter.chords import merge_close_onsets
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import ConversionResult, convert
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
    out_of_scale_ratio: float
    folded_ratio: float
    max_chord_size: int
    min_onset_gap_ms: int | None
    notes_per_second: float
    warnings: tuple[str, ...]


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
    residuals = _onset_residuals(merged_notes, result)
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


def main() -> None:
    """Print a fidelity table for all discovered MIDI fixtures."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    reports = [analyze_midi(path) for path in discover_midi_files()]
    if not reports:
        print("Không tìm thấy MIDI trong fixtures/ hoặc fixtures/local/.")
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
        "Ngoài thang",
        "Gập quãng tám",
        "Hợp âm max",
        "Khoảng min",
        "Nốt/giây",
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
            f"{report.out_of_scale_ratio:.1%}",
            f"{report.folded_ratio:.1%}",
            str(report.max_chord_size),
            f"{report.min_onset_gap_ms} ms"
            if report.min_onset_gap_ms is not None
            else "—",
            f"{report.notes_per_second:.2f}",
        )
        for report in reports
    ]
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]
    print(
        "| "
        + " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
        + " |"
    )
    print("|-" + "-|-".join("-" * width for width in widths) + "-|")
    for row in rows:
        print(
            "| "
            + " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))
            + " |"
        )

    print("\nCảnh báo:")
    warning_count = 0
    for report in reports:
        for warning in report.warnings:
            warning_count += 1
            print(f"- {report.name}: {warning}")
    if not warning_count:
        print("- Không có cảnh báo.")


def _onset_residuals(
    merged_notes: Sequence[Note],
    conversion: ConversionResult,
) -> list[float]:
    if not merged_notes or not conversion.sky_notes:
        return []
    first_onset = min(note.time_ms for note in merged_notes)
    output_times = sorted({note.time_ms for note in conversion.sky_notes})
    return [
        float(
            min(
                abs((note.time_ms - first_onset) - output_time)
                for output_time in output_times
            )
        )
        for note in merged_notes
    ]


def _percentile_90(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, ceil(0.9 * len(ordered)) - 1)]


if __name__ == "__main__":
    main()
