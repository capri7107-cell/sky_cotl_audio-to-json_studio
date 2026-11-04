from pathlib import Path

import mido

from tools.fidelity import analyze_midi, compare_outlier_modes


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


def test_fidelity_classifies_deduplicated_pitches_from_synthetic_midi(
    tmp_path: Path,
) -> None:
    midi_path = tmp_path / "deduplication-classes.mid"
    midi_file = mido.MidiFile(ticks_per_beat=120)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))

    events: list[tuple[int, int, mido.Message]] = []
    scale_pitches = (60, 62, 64, 65, 67, 69, 71, 72)
    for index, pitch in enumerate(scale_pitches):
        onset_tick = index * 24
        if index == 0:
            for extra_pitch in (48, 61):
                events.append(
                    (
                        onset_tick,
                        1,
                        mido.Message("note_on", note=extra_pitch, velocity=90),
                    )
                )
        events.append(
            (onset_tick, 1, mido.Message("note_on", note=pitch, velocity=90))
        )
        events.append(
            (
                onset_tick + 12,
                0,
                mido.Message("note_off", note=pitch, velocity=0),
            )
        )
        if index == 0:
            for extra_pitch in (48, 61):
                events.append(
                    (
                        onset_tick + 12,
                        0,
                        mido.Message("note_off", note=extra_pitch, velocity=0),
                    )
                )
    previous_tick = 0
    for tick, _order, message in sorted(events, key=lambda event: (event[0], event[1])):
        message.time = tick - previous_tick
        track.append(message)
        previous_tick = tick

    midi_file.save(midi_path)
    report = analyze_midi(midi_path)

    assert report.deduplicated_count == 2
    assert report.dedup_same_note_other_octave_ratio == 0.5
    assert report.dedup_different_note_name_ratio == 0.5
    assert report.rounding_over_40_count == 0
    assert report.rounding_over_40_ratio == 0.0


def test_fidelity_compares_snap_and_keep_for_synthetic_grid_outlier(
    tmp_path: Path,
) -> None:
    midi_path = tmp_path / "outlier-comparison.mid"
    midi_file = mido.MidiFile(ticks_per_beat=100)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    onset_ticks = [0, 40, 80, 120, 160, 200, 254, 280, 320, 360]
    events: list[tuple[int, int, mido.Message]] = []
    for index, onset_tick in enumerate(onset_ticks):
        pitch = 60 + (index % 7)
        events.append(
            (onset_tick, 1, mido.Message("note_on", note=pitch, velocity=90))
        )
        events.append(
            (
                onset_tick + 8,
                0,
                mido.Message("note_off", note=pitch, velocity=0),
            )
        )
    previous_tick = 0
    for tick, _order, message in sorted(events, key=lambda event: (event[0], event[1])):
        message.time = tick - previous_tick
        track.append(message)
        previous_tick = tick
    midi_file.save(midi_path)

    comparison = compare_outlier_modes(midi_path)

    assert comparison.snap.rounding_over_40_count == 1
    assert comparison.keep.rounding_over_40_count == 0
    assert comparison.snap.min_onset_gap_ms == 201
    assert comparison.keep.min_onset_gap_ms is not None
    assert 130 <= comparison.keep.min_onset_gap_ms <= 150
