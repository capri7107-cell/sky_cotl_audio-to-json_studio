"""Shared data models for the conversion pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    """A raw note extracted from a MIDI file."""

    time_ms: float
    duration_ms: float
    pitch: int
    velocity: int


@dataclass(frozen=True)
class SkyNote:
    """A note mapped to the Sky instrument's key range."""

    time_ms: int
    key: int


@dataclass(frozen=True)
class SongMeta:
    """Metadata stored alongside exported Sky Studio notes."""

    name: str
    author: str
    transcribed_by: str
    is_composed: bool
    bpm: int
    bits_per_page: int
    pitch_level: int
    is_encrypted: bool
