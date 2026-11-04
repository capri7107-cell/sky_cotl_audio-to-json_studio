from pathlib import Path

import mido

from tools.fidelity import analyze_midi


def test_fidelity_timing_error_is_zero_for_onsets_on_the_lattice(
    tmp_path: Path,
) -> None:
    midi_path = tmp_path / "on-grid.mid"
    midi_file = mido.MidiFile(ticks_per_beat=120)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=600_000, time=0))

    events: list[tuple[int, int, mido.Message]] = []
    for index in range(6):
        onset_tick = index * 24
        pitch = 60 + index
        events.append(
            (onset_tick, 1, mido.Message("note_on", note=pitch, velocity=90))
        )
        events.append(
            (onset_tick + 12, 0, mido.Message("note_off", note=pitch, velocity=0))
        )
    previous_tick = 0
    for tick, _order, message in sorted(events, key=lambda event: (event[0], event[1])):
        message.time = tick - previous_tick
        track.append(message)
        previous_tick = tick

    midi_file.save(midi_path)
    report = analyze_midi(midi_path)

    assert report.input_note_count == 6
    assert report.output_note_count == 6
    assert report.grid_ms == 120.0
    assert report.timing_median_ms == 0.0
    assert report.timing_p90_ms == 0.0
    assert report.timing_max_ms == 0.0
