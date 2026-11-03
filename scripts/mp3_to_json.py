"""Transcribe an MP3 and export it as Sky Studio JSON."""

import argparse
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sky_cotl_studio.ai.transkun_runner import (
    Device,
    ProgressCallback,
    TranskunError,
    resolve_device,
    transcribe,
)
from sky_cotl_studio.audio.validate import AudioValidationError, validate_mp3
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import ConversionResult, convert
from sky_cotl_studio.exporters.sky_studio import export
from sky_cotl_studio.midi.cleanup import trim_leading_silence
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import SongMeta

T = TypeVar("T")


@dataclass(frozen=True)
class MP3ConversionReport:
    """Outcome and stage timings for one MP3-to-JSON conversion."""

    midi_path: Path | None
    device: Device
    conversion: ConversionResult
    phase_seconds: dict[str, float]
    leading_silence_ms: float


def run_mp3_to_json(
    input_path: str | Path,
    output_path: str | Path,
    *,
    device: Device | None = None,
    keep_midi: bool = False,
    midi_out: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
    config: ConverterConfig | None = None,
) -> MP3ConversionReport:
    """Run the validated transcription and conversion pipeline for one MP3."""
    source = Path(input_path)
    destination = Path(output_path)
    retained_midi_path = (
        Path(midi_out)
        if midi_out is not None
        else destination.with_suffix(".mid") if keep_midi else None
    )
    if retained_midi_path is not None and _same_path(retained_midi_path, source):
        raise ValueError("MIDI output path must be different from the MP3 input path")
    if _same_path(destination, source):
        raise ValueError("JSON output path must be different from the MP3 input path")
    if retained_midi_path is not None and _same_path(retained_midi_path, destination):
        raise ValueError("MIDI and JSON output paths must be different")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if retained_midi_path is not None:
        retained_midi_path.parent.mkdir(parents=True, exist_ok=True)
        transcription_path = retained_midi_path
    else:
        transcription_path = _temporary_path(destination.parent, destination.stem, ".mid")

    cancellation = threading.Event()
    phase_seconds: dict[str, float] = {}
    json_temp_path: Path | None = None
    try:
        audio_info, phase_seconds["validate"] = _measure(lambda: validate_mp3(source))
        selected_device = resolve_device(device)
        _, phase_seconds["transcribe"] = _measure(
            lambda: transcribe(
                source,
                transcription_path,
                device=selected_device,
                progress_callback=progress_callback,
                cancel_event=cancellation,
                validated_audio=audio_info,
            )
        )
        midi_notes, phase_seconds["read_midi"] = _measure(lambda: read_notes(transcription_path))
        (trimmed_notes, leading_silence_ms), phase_seconds["trim"] = _measure(
            lambda: trim_leading_silence(midi_notes)
        )
        conversion, phase_seconds["convert"] = _measure(
            lambda: convert(trimmed_notes, config or ConverterConfig())
        )
        metadata = SongMeta(
            name=source.stem,
            author="",
            transcribed_by="",
            is_composed=False,
            bpm=500,
            bits_per_page=16,
            pitch_level=2,
            is_encrypted=False,
        )
        json_text, phase_seconds["export"] = _measure(
            lambda: export(metadata, conversion.sky_notes)
        )
        json_temp_path = _temporary_path(destination.parent, destination.stem, ".json")
        json_temp_path.write_text(json_text, encoding="utf-8")
        os.replace(json_temp_path, destination)
        json_temp_path = None
        return MP3ConversionReport(
            midi_path=retained_midi_path,
            device=selected_device,
            conversion=conversion,
            phase_seconds=phase_seconds,
            leading_silence_ms=leading_silence_ms,
        )
    except KeyboardInterrupt:
        cancellation.set()
        raise
    finally:
        if json_temp_path is not None:
            json_temp_path.unlink(missing_ok=True)
        if retained_midi_path is None:
            transcription_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mp3_path", type=Path)
    parser.add_argument("json_path", type=Path)
    defaults = ConverterConfig()
    parser.add_argument("--grid-mode", choices=("auto", "fixed"), default="auto")
    parser.add_argument("--grid-ms", type=float, default=defaults.grid_ms)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument(
        "--keep-midi",
        action="store_true",
        help="Keep the intermediate MIDI next to the JSON output",
    )
    parser.add_argument(
        "--midi-out",
        type=Path,
        help="Path to retain the intermediate MIDI (implies --keep-midi)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line pipeline and print progress and statistics."""
    args = build_parser().parse_args(argv)
    try:
        report = run_mp3_to_json(
            args.mp3_path,
            args.json_path,
            device=args.device,
            keep_midi=args.keep_midi,
            midi_out=args.midi_out,
            progress_callback=lambda message: print(f"[Transkun] {message}"),
            config=ConverterConfig(grid_mode=args.grid_mode, grid_ms=args.grid_ms),
        )
    except KeyboardInterrupt:
        print("Conversion cancelled; temporary MIDI was removed.")
        return 130
    except (AudioValidationError, OSError, TranskunError, TypeError, ValueError) as error:
        print(f"Conversion failed: {error}")
        return 1

    conversion = report.conversion
    print(f"Device: {report.device}")
    print(f"Leading silence trimmed: {report.leading_silence_ms:.1f} ms")
    for phase, seconds in report.phase_seconds.items():
        print(f"{phase.replace('_', ' ').title()} time: {seconds:.3f} s")
    print(f"Input MIDI notes: {conversion.stats.input_note_count}")
    print(f"Transpose: {conversion.transpose}")
    print(f"Grid mode: {args.grid_mode}")
    print(f"Grid: {conversion.grid_ms:g} ms")
    print(f"Output notes: {conversion.stats.output_note_count}")
    print(f"Deduplicated notes: {conversion.stats.deduplicated_count}")
    print(f"Chord-trimmed notes: {conversion.stats.chord_trimmed_count}")
    print(f"Distinct onset times: {conversion.stats.distinct_time_count}")
    print(f"Maximum chord size: {conversion.stats.max_chord_size}")
    print(f"Folded pitches: {conversion.stats.folded_count}")
    print(f"Out-of-scale pitches: {conversion.stats.out_of_scale_count}")
    if conversion.sky_notes:
        print(f"Final note time: {conversion.sky_notes[-1].time_ms} ms")
    if report.midi_path is not None:
        print(f"Kept MIDI: {report.midi_path}")
    print(f"Output JSON: {args.json_path}")
    return 0


def _measure(operation: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = operation()
    return result, time.perf_counter() - start


def _temporary_path(directory: Path, stem: str, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{stem}.",
        suffix=suffix,
        dir=directory,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _same_path(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
