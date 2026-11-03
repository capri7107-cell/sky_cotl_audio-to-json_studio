"""Configuration values shared by converter operations."""

import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ConverterConfig:
    """User-adjustable converter settings."""

    grid_ms: float = 120
    merge_ms: float = 40
    max_chord: int = 4
    grid_mode: Literal["auto", "fixed"] = "auto"

    def __post_init__(self) -> None:
        if self.grid_mode not in ("auto", "fixed"):
            raise ValueError("grid_mode must be 'auto' or 'fixed'")
        if (
            isinstance(self.grid_ms, bool)
            or not isinstance(self.grid_ms, (int, float))
            or not math.isfinite(self.grid_ms)
            or self.grid_ms <= 0
        ):
            raise ValueError("grid_ms must be a positive finite number")
        if (
            isinstance(self.merge_ms, bool)
            or not isinstance(self.merge_ms, (int, float))
            or not math.isfinite(self.merge_ms)
            or self.merge_ms < 0
        ):
            raise ValueError("merge_ms must be a non-negative finite number")
        if (
            not isinstance(self.max_chord, int)
            or isinstance(self.max_chord, bool)
            or self.max_chord < 2
        ):
            raise ValueError("max_chord must be an integer of at least 2")
