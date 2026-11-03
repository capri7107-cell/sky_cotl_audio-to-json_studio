from pathlib import Path

import mido
import pytest

from sky_cotl_studio.midi.cleanup import trim_leading_silence
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import Note

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIDI_FIXTURE = PROJECT_ROOT / "fixtures" / "test_output.mid"


def test_read_transkun_fixture_notes() -> None:
    notes = read_notes(MIDI_FIXTURE, min_duration_ms=0)

    assert len(notes) == 650
    assert min(note.pitch for note in notes) == 40
    assert max(note.pitch for note in notes) == 83
    assert notes[0].time_ms == pytest.approx(6271.354, abs=1)
    assert all(note.duration_ms > 0 for note in notes)
    assert len(read_notes(MIDI_FIXTURE)) == 650


def test_trim_leading_silence_moves_first_note_to_zero() -> None:
    notes = read_notes(MIDI_FIXTURE)

    trimmed, offset_ms = trim_leading_silence(notes)

    assert offset_ms == pytest.approx(6271.354, abs=1)
    assert min(note.time_ms for note in trimmed) == pytest.approx(0)
    assert len(trimmed) == len(notes)
    assert all(
        trimmed_note.duration_ms == original_note.duration_ms
        for trimmed_note, original_note in zip(trimmed, notes)
    )
    assert all(
        trimmed_note.time_ms == pytest.approx(original_note.time_ms - offset_ms)
        for trimmed_note, original_note in zip(trimmed, notes)
    )


def test_tempo_map_changes_tick_to_millisecond_conversion(tmp_path: Path) -> None:
    midi_file = mido.MidiFile(type=1, ticks_per_beat=480)
    tempo_track = mido.MidiTrack()
    tempo_track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    tempo_track.append(mido.MetaMessage("set_tempo", tempo=250_000, time=480))
    midi_file.tracks.append(tempo_track)

    note_track = mido.MidiTrack()
    note_track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    note_track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    note_track.append(mido.Message("note_on", note=62, velocity=80, time=0))
    note_track.append(mido.Message("note_off", note=62, velocity=0, time=480))
    midi_file.tracks.append(note_track)

    midi_path = tmp_path / "tempo_map.mid"
    midi_file.save(midi_path)

    notes = read_notes(midi_path)

    assert len(notes) == 2
    assert notes[0] == Note(time_ms=0, duration_ms=500, pitch=60, velocity=90)
    assert notes[1] == Note(time_ms=500, duration_ms=250, pitch=62, velocity=80)


def test_reader_filters_short_notes_and_exact_duplicates(tmp_path: Path) -> None:
    midi_file = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=31))
    track.append(mido.Message("note_off", note=60, velocity=0, time=0))
    track.append(mido.Message("note_on", note=62, velocity=80, time=0))
    track.append(mido.Message("note_off", note=62, velocity=0, time=28))
    track.append(mido.Message("note_on", note=64, velocity=70, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, time=30))
    midi_file.tracks.append(track)
    midi_path = tmp_path / "short_and_duplicate.mid"
    midi_file.save(midi_path)

    notes = read_notes(midi_path)

    assert [note.pitch for note in notes] == [60, 64]
    assert notes[0].duration_ms == pytest.approx(32.291667)
    assert notes[1].duration_ms == pytest.approx(31.25)


def test_trim_empty_notes() -> None:
    assert trim_leading_silence([]) == ([], 0.0)
