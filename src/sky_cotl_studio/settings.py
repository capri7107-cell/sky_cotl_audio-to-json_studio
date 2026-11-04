"""Persistent desktop settings, independent from Qt and the CLI."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

SETTINGS_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "settings.json"
DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "output"


@dataclass(frozen=True)
class SettingsLoadResult:
    output_directory: Path
    warning: str | None = None


def load_settings(
    settings_path: str | Path = DEFAULT_SETTINGS_PATH,
    default_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
) -> SettingsLoadResult:
    """Load a versioned output-folder preference, falling back on invalid data."""
    settings_file = Path(settings_path)
    fallback = Path(default_directory).resolve()
    try:
        contents = json.loads(settings_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return SettingsLoadResult(fallback, f"Settings file not found: {settings_file}")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return SettingsLoadResult(fallback, f"Could not read settings: {error}")
    if not isinstance(contents, dict):
        return SettingsLoadResult(fallback, "Settings must be a JSON object.")
    version = contents.get("version")
    if type(version) is not int or version != SETTINGS_VERSION:
        return SettingsLoadResult(fallback, "Unsupported settings version.")
    output_directory = contents.get("output_directory")
    if (
        not isinstance(output_directory, str)
        or not output_directory
        or not all(character.isprintable() for character in output_directory)
    ):
        return SettingsLoadResult(fallback, "Settings output_directory must be a path.")
    path = Path(output_directory)
    if not path.is_absolute():
        return SettingsLoadResult(fallback, "Settings output_directory must be absolute.")
    return SettingsLoadResult(path, None)


def save_settings(
    settings_path: str | Path,
    output_directory: str | Path,
) -> None:
    """Atomically save only the absolute output directory and settings version."""
    destination = Path(settings_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SETTINGS_VERSION,
        "output_directory": str(Path(output_directory).resolve()),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".settings-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def ensure_writable_directory(directory: str | Path) -> Path:
    """Create a directory if needed and verify it by writing a temporary file."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".sky-cotl-write-test-",
        dir=path,
    )
    try:
        os.close(descriptor)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return path.resolve()
