"""Sky Studio JSON import and export."""

import json
import re
from collections.abc import Sequence
from pathlib import Path

from sky_cotl_studio.models import SkyNote, SongMeta

_KEY_PATTERN = re.compile(r"(?:\d+)?Key(\d+)")


def export(meta: SongMeta, sky_notes: Sequence[SkyNote]) -> str:
    """Serialize metadata and notes to a Sky Studio JSON document."""
    if not isinstance(meta, SongMeta):
        raise TypeError("meta must be a SongMeta instance")

    _validate_metadata(meta)
    notes = _normalize_notes(sky_notes)
    document = [
        {
            "name": meta.name,
            "author": meta.author,
            "transcribedBy": meta.transcribed_by,
            "isComposed": meta.is_composed,
            "bpm": meta.bpm,
            "bitsPerPage": meta.bits_per_page,
            "pitchLevel": meta.pitch_level,
            "isEncrypted": meta.is_encrypted,
            "songNotes": [
                {"time": note.time_ms, "key": f"Key{note.key}"} for note in notes
            ],
        }
    ]
    return json.dumps(document, ensure_ascii=False, indent=2)


def load(path: str | Path) -> tuple[SongMeta, list[SkyNote]]:
    """Load Sky Studio metadata and normalized notes from a JSON file."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, list) or len(document) != 1:
        raise ValueError("Sky Studio JSON root must be an array containing one object")

    song = document[0]
    if not isinstance(song, dict):
        raise TypeError("Sky Studio JSON array item must be an object")

    metadata = _load_metadata(song)
    raw_notes = song.get("songNotes")
    if not isinstance(raw_notes, list):
        raise TypeError("songNotes must be an array")

    notes = [_load_note(raw_note) for raw_note in raw_notes]
    return metadata, _normalize_notes(notes)


def _validate_metadata(meta: SongMeta) -> None:
    for field_name in ("name", "author", "transcribed_by"):
        if not isinstance(getattr(meta, field_name), str):
            raise TypeError(f"{field_name} must be a string")

    for field_name in ("is_composed", "is_encrypted"):
        if not isinstance(getattr(meta, field_name), bool):
            raise TypeError(f"{field_name} must be a boolean")

    for field_name in ("bpm", "bits_per_page", "pitch_level"):
        value = getattr(meta, field_name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{field_name} must be an integer")


def _load_metadata(song: dict[str, object]) -> SongMeta:
    name = _required_string(song, "name")
    author = _required_string(song, "author")
    transcribed_by = _required_string(song, "transcribedBy")
    is_composed = _required_boolean(song, "isComposed")
    bpm = _required_integer(song, "bpm")
    bits_per_page = _required_integer(song, "bitsPerPage")
    pitch_level = _required_integer(song, "pitchLevel")
    is_encrypted = _required_boolean(song, "isEncrypted")
    return SongMeta(
        name=name,
        author=author,
        transcribed_by=transcribed_by,
        is_composed=is_composed,
        bpm=bpm,
        bits_per_page=bits_per_page,
        pitch_level=pitch_level,
        is_encrypted=is_encrypted,
    )


def _required_string(data: dict[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _required_boolean(data: dict[str, object], field_name: str) -> bool:
    value = data.get(field_name)
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _required_integer(data: dict[str, object], field_name: str) -> int:
    value = data.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _load_note(raw_note: object) -> SkyNote:
    if not isinstance(raw_note, dict):
        raise TypeError("Each song note must be an object")

    time_ms = raw_note.get("time")
    if not isinstance(time_ms, int) or isinstance(time_ms, bool):
        raise TypeError("song note time must be an integer")
    if time_ms < 0:
        raise ValueError("song note time must be non-negative")

    raw_key = raw_note.get("key")
    if not isinstance(raw_key, str):
        raise TypeError("song note key must be a string")

    match = _KEY_PATTERN.fullmatch(raw_key)
    if match is None:
        raise ValueError(f"Invalid Sky key: {raw_key!r}")

    key = int(match.group(1))
    if not 0 <= key <= 14:
        raise ValueError(f"Sky key must be in the range 0..14: {raw_key!r}")
    return SkyNote(time_ms=time_ms, key=key)


def _normalize_notes(sky_notes: Sequence[SkyNote]) -> list[SkyNote]:
    unique_notes: dict[tuple[int, int], SkyNote] = {}
    for note in sky_notes:
        if not isinstance(note, SkyNote):
            raise TypeError("sky_notes must contain only SkyNote instances")
        if (
            not isinstance(note.time_ms, int)
            or isinstance(note.time_ms, bool)
        ):
            raise TypeError("song note time must be an integer")
        if note.time_ms < 0:
            raise ValueError("song note time must be non-negative")
        if (
            not isinstance(note.key, int)
            or isinstance(note.key, bool)
        ):
            raise TypeError("Sky key must be an integer")
        if not 0 <= note.key <= 14:
            raise ValueError("Sky key must be in the range 0..14")
        unique_notes.setdefault((note.time_ms, note.key), note)

    return sorted(unique_notes.values(), key=lambda note: note.time_ms)
