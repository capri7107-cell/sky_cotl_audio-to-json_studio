"""Convert a MIDI file to Sky Studio JSON."""

import argparse
from pathlib import Path

from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import convert
from sky_cotl_studio.exporters.sky_studio import export
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import SongMeta


def main() -> None:
    """Convert the requested MIDI file and print conversion statistics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("midi_path", type=Path)
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()

    midi_path: Path = args.midi_path
    json_path: Path = args.json_path
    midi_notes = read_notes(midi_path)
    result = convert(midi_notes, ConverterConfig())
    metadata = SongMeta(
        name=midi_path.stem,
        author="",
        transcribed_by="",
        is_composed=False,
        bpm=500,
        bits_per_page=16,
        pitch_level=2,
        is_encrypted=False,
    )

    json_path.write_text(export(metadata, result.sky_notes), encoding="utf-8")
    print(f"Input MIDI notes: {result.stats.input_note_count}")
    print(f"Transpose: {result.transpose}")
    print(f"Grid: {result.grid_ms:g} ms")
    print(f"Output notes: {result.stats.output_note_count}")
    print(f"Distinct onset times: {result.stats.distinct_time_count}")
    print(f"Maximum chord size: {result.stats.max_chord_size}")
    print(f"Folded pitches: {result.stats.folded_count}")
    print(f"Out-of-scale pitches: {result.stats.out_of_scale_count}")
    if result.sky_notes:
        print(f"Final note time: {result.sky_notes[-1].time_ms} ms")
    print(f"Output JSON: {json_path}")


if __name__ == "__main__":
    main()
