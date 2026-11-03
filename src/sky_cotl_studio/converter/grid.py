"""Onset grid estimation and time quantization."""

import math
from collections.abc import Sequence
from itertools import pairwise
from statistics import median


def estimate_grid(onsets_ms: Sequence[float]) -> float:
    """Estimate the dominant interval between successive note onsets."""
    if any(not math.isfinite(onset) for onset in onsets_ms):
        raise ValueError("onsets_ms must contain only finite values")

    ordered_onsets = sorted(set(onsets_ms))
    if len(ordered_onsets) < 2:
        raise ValueError("at least two distinct onsets are required")

    intervals = [
        later - earlier
        for earlier, later in pairwise(ordered_onsets)
    ]

    def nearby_intervals(candidate: float) -> list[float]:
        tolerance = max(8.0, candidate * 0.04)
        return [
            interval
            for interval in intervals
            if abs(interval - candidate) <= tolerance
        ]

    dominant_cluster = max(
        (nearby_intervals(candidate) for candidate in intervals),
        key=lambda cluster: (len(cluster), -median(cluster)),
    )
    return float(median(dominant_cluster))


def quantize(time_ms: float, grid_ms: float) -> int:
    """Round a time in milliseconds to the nearest grid point."""
    if not math.isfinite(time_ms):
        raise ValueError("time_ms must be finite")
    if not math.isfinite(grid_ms) or grid_ms <= 0:
        raise ValueError("grid_ms must be a positive finite number")

    grid_time = math.floor(time_ms / grid_ms + 0.5) * grid_ms
    return math.floor(grid_time + 0.5)
