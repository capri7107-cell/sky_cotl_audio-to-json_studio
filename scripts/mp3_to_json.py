"""Transcribe an MP3 and export it as Sky Studio JSON."""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sky_cotl_studio.ai.transkun_runner import Device
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.models import SongMeta
from sky_cotl_studio.pipeline.job import (
    ConversionJob,
    ConversionJobCancelled,
    ConversionJobConfig,
    ConversionJobError,
    ConversionJobResult,
    JobState,
)

LegacyProgressCallback = Callable[[str], None]


def run_mp3_to_json(
    input_path: str | Path,
    output_path: str | Path,
    *,
    device: Device | None = None,
    keep_midi: bool = False,
    midi_out: str | Path | None = None,
    progress_callback: LegacyProgressCallback | None = None,
    config: ConverterConfig | None = None,
    metadata: SongMeta | None = None,
) -> ConversionJobResult:
    """Run a ``ConversionJob`` synchronously for existing CLI callers."""
    source = Path(input_path)
    destination = Path(output_path)
    converter_config = config or ConverterConfig()
    song_metadata = metadata or SongMeta(
        name=source.stem,
        author="",
        transcribed_by="",
        is_composed=False,
        bpm=500,
        bits_per_page=16,
        pitch_level=2,
        is_encrypted=False,
    )
    job = ConversionJob(
        ConversionJobConfig(
            input_path=source,
            output_path=destination,
            metadata=song_metadata,
            grid_mode=converter_config.grid_mode,
            grid_ms=converter_config.grid_ms,
            merge_ms=converter_config.merge_ms,
            max_chord=converter_config.max_chord,
            device=device,
            keep_midi=keep_midi,
            midi_out=Path(midi_out) if midi_out is not None else None,
        ),
        progress_callback=(
            lambda event: progress_callback(event.message)
            if progress_callback is not None
            else None
        ),
    )
    job.start()
    try:
        job.wait()
    except KeyboardInterrupt:
        job.cancel()
        job.wait()
        raise

    if job.state is JobState.FAILED and job.failure is not None:
        raise ConversionJobError(job.failure)
    if job.state is JobState.CANCELLED:
        raise ConversionJobCancelled("Conversion was cancelled")
    if job.result is None:
        raise RuntimeError("Conversion job ended without a result")
    return job.result


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
    except ConversionJobCancelled:
        print("Conversion cancelled; temporary MIDI was removed.")
        return 130
    except ConversionJobError as error:
        print(f"Conversion failed: {error.failure.user_message}")
        print(f"Technical cause: {error.failure.technical_cause}")
        return 1
    except (OSError, TypeError, ValueError) as error:
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
    grid_text = (
        f"{conversion.grid_ms:g} ms"
        if conversion.grid_ms is not None
        else "not detected (unquantized)"
    )
    print(f"Grid: {grid_text}")
    for warning in conversion.warnings:
        if warning.message:
            print(f"Warning: {warning.message}")
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


if __name__ == "__main__":
    raise SystemExit(main())
