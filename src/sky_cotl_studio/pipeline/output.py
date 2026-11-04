"""Windows-safe output naming and non-overwriting publication helpers."""

from __future__ import annotations

import os
from pathlib import Path

_INVALID_FILENAME_CHARACTERS = set('<>:"/\\|?*')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def sanitize_output_stem(name: str) -> str:
    """Return a Windows-compatible filename stem of at most 120 characters."""
    cleaned = "".join(
        character
        for character in name
        if character not in _INVALID_FILENAME_CHARACTERS
        and character.isprintable()
    ).rstrip(". ")
    if not cleaned:
        cleaned = "untitled"
    if cleaned.split(".", maxsplit=1)[0].upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:120].rstrip(". ") or "untitled"


def available_output_paths(
    directory: str | Path,
    name: str,
    *,
    keep_midi: bool,
) -> tuple[Path, Path | None, str]:
    """Find the first unused JSON name and optional matching MIDI name."""
    folder = Path(directory)
    base = sanitize_output_stem(name)
    suffix_number = 1
    while True:
        suffix = "" if suffix_number == 1 else f" ({suffix_number})"
        stem = f"{base[: 120 - len(suffix)]}{suffix}"
        json_path = folder / f"{stem}.json"
        midi_path = folder / f"{stem}.mid" if keep_midi else None
        if not json_path.exists() and (
            midi_path is None or not midi_path.exists()
        ):
            return json_path, midi_path, stem
        suffix_number += 1


def publish_output_files(
    staged_json: str | Path,
    directory: str | Path,
    name: str,
    *,
    staged_midi: str | Path | None = None,
) -> tuple[Path, Path | None, str]:
    """Rename completed staged files without overwriting existing outputs."""
    staged_json_path = Path(staged_json)
    staged_midi_path = Path(staged_midi) if staged_midi is not None else None
    folder = Path(directory)
    stem = sanitize_output_stem(name)
    json_path = folder / f"{stem}.json"
    midi_path = folder / f"{stem}.mid" if staged_midi_path is not None else None
    if json_path.exists() or (midi_path is not None and midi_path.exists()):
        raise FileExistsError(json_path)
    moved_midi = False
    try:
        if staged_midi_path is not None and midi_path is not None:
            os.rename(staged_midi_path, midi_path)
            moved_midi = True
        os.rename(staged_json_path, json_path)
    except BaseException:
        if moved_midi and midi_path is not None and staged_midi_path is not None:
            os.rename(midi_path, staged_midi_path)
        raise
    return json_path, midi_path, stem
