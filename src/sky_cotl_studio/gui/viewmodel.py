"""Qt-independent form validation and presentation helpers for the GUI."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sky_cotl_studio.audio.download import (
    DownloadError,
    sanitize_video_title,
    validate_youtube_url,
)
from sky_cotl_studio.models import SongMeta
from sky_cotl_studio.pipeline.job import ConversionJobConfig, ConversionJobResult
from sky_cotl_studio.pipeline.output import sanitize_output_stem

SourceMode = Literal["youtube", "file"]


@dataclass(frozen=True)
class ConversionForm:
    """Values collected by the desktop form before starting a conversion."""

    source_mode: SourceMode
    input_source: str
    output_folder: str
    grid_mode: Literal["auto", "fixed"]
    grid_ms: str
    device: Literal["auto", "cuda", "cpu"]
    title: str
    author: str
    transcribed_by: str
    keep_midi: bool = False


@dataclass
class SuggestedField:
    """Track whether a text-field value is automatic or user-authored."""

    value: str = ""
    is_suggested: bool = True

    def set_by_user(self, value: str) -> None:
        self.value = value
        self.is_suggested = False

    def set_suggestion(self, value: str) -> str:
        if self.is_suggested:
            self.value = value
        return self.value

    def clear_suggestion(self) -> None:
        if self.is_suggested:
            self.value = ""


def switch_source_mode(title: SuggestedField) -> str:
    """Clear automatic source metadata but preserve a user-authored title."""
    title.clear_suggestion()
    return title.value


def update_source_title(
    source: str,
    source_mode: SourceMode,
    title: SuggestedField,
    *,
    video_title: str | None = None,
) -> str:
    """Update an automatically suggested song title for the selected source."""
    source_value = _trim_wrapping_quotes(source.strip())
    if source_mode == "youtube":
        suggestion = sanitize_video_title(video_title or "")
    else:
        suggestion = Path(source_value).stem if source_value else ""
    return title.set_suggestion(suggestion)


def validate_form(
    form: ConversionForm,
    *,
    require_input_exists: bool = False,
) -> tuple[str, ...]:
    """Return user-correctable form validation errors in English."""
    errors: list[str] = []
    source = _trim_wrapping_quotes(form.input_source.strip())
    if form.source_mode not in ("youtube", "file"):
        errors.append("Choose a source type.")
    elif not source:
        errors.append(
            "Enter a YouTube link." if form.source_mode == "youtube" else "Choose an audio file."
        )
    elif form.source_mode == "youtube":
        try:
            validate_youtube_url(source)
        except DownloadError as error:
            errors.append(str(error))
    elif _looks_like_url(source):
        errors.append("That looks like a link. Switch Source to YouTube link.")
    elif source.startswith("-") or (
        require_input_exists and not Path(source).is_file()
    ):
        errors.append("Choose an existing audio file.")
    if not form.output_folder.strip():
        errors.append("Choose an output folder.")
    if form.grid_mode not in ("auto", "fixed"):
        errors.append("Choose a valid time grid.")
    if form.grid_mode == "fixed":
        try:
            grid_ms = float(form.grid_ms)
        except ValueError:
            errors.append("Enter a valid grid duration in milliseconds.")
        else:
            if not math.isfinite(grid_ms) or grid_ms <= 0:
                errors.append("Grid duration must be greater than 0 ms.")
    if form.device not in ("auto", "cuda", "cpu"):
        errors.append("Choose a valid device.")
    return tuple(errors)


def build_job_config(form: ConversionForm) -> ConversionJobConfig:
    """Convert validated GUI values into a no-overwrite pipeline configuration."""
    errors = validate_form(form, require_input_exists=form.source_mode == "file")
    if errors:
        raise ValueError("\n".join(errors))
    source = _trim_wrapping_quotes(form.input_source.strip())
    output_directory = Path(form.output_folder).resolve()
    output_path = output_directory / "untitled.json"
    input_path = Path(source) if form.source_mode == "file" else None
    input_url = validate_youtube_url(source) if form.source_mode == "youtube" else None
    fallback_name = Path(source).stem if input_path is not None else ""
    preferred_name = form.title.strip() or fallback_name
    song_name = (
        sanitize_output_stem(preferred_name)
        if preferred_name
        else ""
    )
    return ConversionJobConfig(
        input_path=input_path,
        input_url=input_url,
        output_path=output_path,
        metadata=SongMeta(
            name=song_name,
            author=form.author.strip(),
            transcribed_by=form.transcribed_by.strip(),
            is_composed=False,
            bpm=500,
            bits_per_page=16,
            pitch_level=2,
            is_encrypted=False,
        ),
        grid_mode=form.grid_mode,
        grid_ms=float(form.grid_ms) if form.grid_mode == "fixed" else 120.0,
        device=None if form.device == "auto" else form.device,
        keep_midi=form.keep_midi,
        avoid_overwrite=True,
    )


def format_summary(result: ConversionJobResult) -> str:
    """Create an English summary of a completed conversion."""
    conversion = result.conversion
    grid_text = (
        f"{conversion.grid_ms:.1f} ms"
        if conversion.grid_ms is not None
        else "Fallback (unquantized)"
    )
    lines = [
        f"Output notes: {conversion.stats.output_note_count}",
        f"Grid: {grid_text}",
        f"Transpose: {conversion.transpose:+d} semitones",
        f"Octave-folded notes: {conversion.stats.folded_count}",
        f"Out-of-scale notes: {conversion.stats.out_of_scale_count}",
        "Phase timings:",
    ]
    lines.extend(
        f"• {phase}: {duration:.3f} s"
        for phase, duration in result.phase_seconds.items()
    )
    return "\n".join(lines)


def format_completion_status(json_path: str | Path) -> str:
    """Format the final status with the full saved JSON path."""
    return f"Done: saved to {json_path}"


def failure_message(user_message: str) -> str:
    """Return a short English user-facing failure message."""
    return {
        "The input audio could not be validated.": "The audio file could not be read or validated.",
        "The audio could not be transcribed.": "Could not transcribe the audio to MIDI.",
        "The generated MIDI could not be read.": "Could not read the generated MIDI file.",
        "The notes could not be converted.": "Could not convert the notes.",
        "The output JSON could not be created.": "Could not save the JSON file.",
        "The generated MIDI could not be processed.": "Could not process the generated MIDI file.",
        "The YouTube URL is invalid.": "Only YouTube links are supported.",
        "A network error interrupted the YouTube download.": "A network error interrupted the download.",
        "The YouTube video is private or unavailable.": "The video is private or unavailable.",
        "The YouTube video is age-restricted.": "The video is age-restricted.",
        "The YouTube video exceeds the duration limit.": "The video is longer than the 15 minute limit.",
        "Live streams are not supported.": "Livestreams are not supported.",
        "Please update yt-dlp.": "Please update yt-dlp.",
        "No supported JavaScript runtime or video format was found.": "Could not find a supported video format. Install a JavaScript runtime or update yt-dlp.",
        "The YouTube video could not be downloaded.": "Could not download audio from YouTube.",
        "yt-dlp exited with a non-zero status.": "Could not download audio from YouTube.",
        "yt-dlp finished successfully but created no audio file.": "yt-dlp finished but no audio file was created.",
        "The downloaded audio file could not be read.": "The downloaded audio file could not be read.",
    }.get(user_message, user_message)


def grid_mode_from_label(label: str) -> Literal["auto", "fixed"]:
    """Map the user-visible time-grid choice to a typed mode."""
    if label == "Automatic":
        return "auto"
    if label == "Fixed":
        return "fixed"
    raise ValueError(f"Invalid time grid: {label}")


def grid_ms_enabled(grid_mode: Literal["auto", "fixed"]) -> bool:
    """Return whether the fixed-grid duration control should be enabled."""
    return grid_mode == "fixed"


def device_from_label(label: str) -> Literal["auto", "cuda", "cpu"]:
    """Map the user-visible device choice to a typed device."""
    choices: dict[str, Literal["auto", "cuda", "cpu"]] = {
        "Automatic": "auto",
        "CUDA": "cuda",
        "CPU": "cpu",
    }
    try:
        return choices[label]
    except KeyError as error:
        raise ValueError(f"Invalid device: {label}") from error


def _looks_like_url(value: str) -> bool:
    candidate = _trim_wrapping_quotes(value.strip())
    if not candidate or re.match(r"^[A-Za-z]:[\\/]", candidate):
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", candidate):
        return True
    return re.match(
        r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:[/:?#]|$)",
        candidate,
        flags=re.IGNORECASE,
    ) is not None


def _trim_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value
