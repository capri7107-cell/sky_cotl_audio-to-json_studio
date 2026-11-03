import json
from pathlib import Path

import pytest

from sky_cotl_studio.exporters.sky_studio import export, load
from sky_cotl_studio.models import SkyNote, SongMeta

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "Summertime.json"


def test_fixture_load_export_load_round_trip(tmp_path: Path) -> None:
    metadata, notes = load(FIXTURE_PATH)
    assert len(notes) == 987

    output_path = tmp_path / "round_trip.json"
    output_path.write_text(export(metadata, notes), encoding="utf-8")
    reloaded_metadata, reloaded_notes = load(output_path)

    assert reloaded_metadata == metadata
    assert reloaded_notes == notes


def test_load_accepts_layered_and_unlayered_keys_and_export_removes_layer(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "keys.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "name": "Test",
                    "author": "",
                    "transcribedBy": "",
                    "isComposed": False,
                    "bpm": 500,
                    "bitsPerPage": 16,
                    "pitchLevel": 2,
                    "isEncrypted": False,
                    "songNotes": [
                        {"time": 10, "key": "Key0"},
                        {"time": 0, "key": "Key11"},
                        {"time": 0, "key": "1Key11"},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    metadata, notes = load(input_path)
    assert notes == [SkyNote(time_ms=0, key=11), SkyNote(time_ms=10, key=0)]

    exported = json.loads(export(metadata, notes))
    assert exported[0]["songNotes"] == [
        {"time": 0, "key": "Key11"},
        {"time": 10, "key": "Key0"},
    ]


@pytest.mark.parametrize("key", ["key11", "Key15", "1Key-1", "Key", "1Key11x"])
def test_load_rejects_invalid_keys(tmp_path: Path, key: str) -> None:
    input_path = tmp_path / "invalid_key.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "name": "Test",
                    "author": "",
                    "transcribedBy": "",
                    "isComposed": False,
                    "bpm": 500,
                    "bitsPerPage": 16,
                    "pitchLevel": 2,
                    "isEncrypted": False,
                    "songNotes": [{"time": 0, "key": key}],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load(input_path)


def test_export_has_expected_root_field_order_and_preserves_unicode() -> None:
    metadata = SongMeta(
        name="Summertime",
        author="麦吉Maggie x 盖盖Nyan",
        transcribed_by="NRSPlays",
        is_composed=True,
        bpm=500,
        bits_per_page=16,
        pitch_level=2,
        is_encrypted=False,
    )

    result = export(metadata, [SkyNote(time_ms=0, key=11)])
    parsed = json.loads(result)

    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert list(parsed[0]) == [
        "name",
        "author",
        "transcribedBy",
        "isComposed",
        "bpm",
        "bitsPerPage",
        "pitchLevel",
        "isEncrypted",
        "songNotes",
    ]
    assert "麦吉Maggie x 盖盖Nyan" in result
    assert parsed[0]["songNotes"] == [{"time": 0, "key": "Key11"}]


@pytest.mark.parametrize("key", [-1, 15])
def test_export_rejects_keys_outside_sky_range(key: int) -> None:
    metadata = SongMeta(
        name="Test",
        author="",
        transcribed_by="",
        is_composed=False,
        bpm=500,
        bits_per_page=16,
        pitch_level=2,
        is_encrypted=False,
    )

    with pytest.raises(ValueError):
        export(metadata, [SkyNote(time_ms=0, key=key)])
