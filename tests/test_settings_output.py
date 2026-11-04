import json
from pathlib import Path

import pytest

from sky_cotl_studio.pipeline.output import (
    available_output_paths,
    publish_output_files,
    sanitize_output_stem,
)
from sky_cotl_studio.settings import (
    SETTINGS_VERSION,
    ensure_writable_directory,
    load_settings,
    save_settings,
)


def test_settings_missing_corrupt_wrong_type_and_unknown_version_fall_back(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.json"
    default = tmp_path / "output"
    missing = load_settings(settings_path, default)
    assert missing.output_directory == default
    assert missing.warning

    settings_path.write_text("{", encoding="utf-8")
    assert load_settings(settings_path, default).warning

    settings_path.write_text("[]", encoding="utf-8")
    assert load_settings(settings_path, default).warning

    settings_path.write_text(
        json.dumps({"version": SETTINGS_VERSION + 1, "output_directory": str(default)}),
        encoding="utf-8",
    )
    assert load_settings(settings_path, default).warning


def test_settings_round_trip_absolute_unicode_path_and_atomic_file(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.json"
    directory = tmp_path / "thư mục output"
    save_settings(settings_path, directory)

    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document == {
        "version": SETTINGS_VERSION,
        "output_directory": str(directory.resolve()),
    }
    assert load_settings(settings_path, tmp_path).output_directory == directory.resolve()
    assert list(tmp_path.glob("settings-*.tmp")) == []


def test_unwritable_output_directory_reports_the_os_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_mkstemp(*_args: object, **_kwargs: object) -> tuple[int, str]:
        raise PermissionError("access denied")

    monkeypatch.setattr("sky_cotl_studio.settings.tempfile.mkstemp", fail_mkstemp)
    with pytest.raises(OSError, match="access denied"):
        ensure_writable_directory(tmp_path / "output")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("bad<>:\"/\\|?*name.", "badname"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("   ", "untitled"),
        ("Vết Mưa", "Vết Mưa"),
        ("x" * 140, "x" * 120),
    ],
)
def test_output_stem_sanitization(name: str, expected: str) -> None:
    assert sanitize_output_stem(name) == expected


def test_available_output_paths_avoid_existing_json_and_midi_pairs(
    tmp_path: Path,
) -> None:
    (tmp_path / "song.json").touch()
    (tmp_path / "song (2).mid").touch()

    json_path, midi_path, stem = available_output_paths(
        tmp_path,
        "song",
        keep_midi=True,
    )

    assert stem == "song (3)"
    assert json_path.name == "song (3).json"
    assert midi_path is not None and midi_path.name == "song (3).mid"


def test_publish_output_files_never_overwrites_and_retries_pair_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "song.json").write_text("existing", encoding="utf-8")
    staged_json = tmp_path / ".stage.json"
    staged_midi = tmp_path / ".stage.mid"
    staged_json.write_text("new", encoding="utf-8")
    staged_midi.write_bytes(b"midi")

    _, _, available_stem = available_output_paths(
        tmp_path,
        "song",
        keep_midi=True,
    )
    json_path, midi_path, stem = publish_output_files(
        staged_json,
        tmp_path,
        available_stem,
        staged_midi=staged_midi,
    )

    assert stem == "song (2)"
    assert (tmp_path / "song.json").read_text(encoding="utf-8") == "existing"
    assert json_path.read_text(encoding="utf-8") == "new"
    assert midi_path is not None and midi_path.read_bytes() == b"midi"
    assert not staged_json.exists()
    assert not staged_midi.exists()


def test_settings_file_with_relative_or_non_string_path_falls_back(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.json"
    default = tmp_path / "output"
    for path in ("relative", 12, None, "C:\\invalid\x00path"):
        settings_path.write_text(
            json.dumps({"version": SETTINGS_VERSION, "output_directory": path}),
            encoding="utf-8",
        )
        result = load_settings(settings_path, default)
        assert result.output_directory == default
        assert result.warning


def test_default_settings_and_output_directories_are_project_relative() -> None:
    from sky_cotl_studio.settings import (
        DEFAULT_OUTPUT_DIRECTORY,
        DEFAULT_SETTINGS_PATH,
    )

    project_root = Path(__file__).resolve().parents[1]
    assert DEFAULT_SETTINGS_PATH == project_root / "settings.json"
    assert DEFAULT_OUTPUT_DIRECTORY == project_root / "output"
