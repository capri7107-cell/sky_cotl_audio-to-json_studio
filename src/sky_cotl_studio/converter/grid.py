"""Onset grid estimation and time quantization."""

import math
from collections.abc import Sequence
from itertools import pairwise
from statistics import median

_MIN_AUTO_GRID_MS = 100.0
_MAX_AUTO_GRID_MS = 1000.0
_GRID_DIVISORS = (1, 2, 4, 8)
_MAX_LATTICE_RMSE_MS = 25.0
_MIN_AUTO_ONSETS = 5
_MIN_SINGLE_STEP_RATIO = 0.01


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


def estimate_lattice(onsets_ms: Sequence[float]) -> tuple[float, float]:
    """Fit the finest supported onset lattice, returning its step and phase.

    Candidate steps come from adjacent onset intervals and binary subdivisions
    through one eighth. Each candidate is refined by alternating integer
    assignment and least-squares fitting of ``time = phase + index * step``.
    The fit requires at least five distinct onsets, at least 1% of transitions
    advancing by one grid step, and no more than 25 ms RMS onset residual.
    """
    if any(not math.isfinite(onset) for onset in onsets_ms):
        raise ValueError("onsets_ms must contain only finite values")
    ordered_onsets = sorted(set(onsets_ms))
    if len(ordered_onsets) < _MIN_AUTO_ONSETS:
        raise ValueError(
            f"at least {_MIN_AUTO_ONSETS} distinct onsets are required"
        )

    origin = ordered_onsets[0]
    relative_onsets = [onset - origin for onset in ordered_onsets]
    intervals = [
        later - earlier
        for earlier, later in pairwise(relative_onsets)
    ]
    candidates = {
        interval / divisor
        for interval in intervals
        for divisor in _GRID_DIVISORS
        if _MIN_AUTO_GRID_MS <= interval / divisor <= _MAX_AUTO_GRID_MS
    }

    acceptable: list[tuple[float, float, float]] = []
    candidate_fits: list[tuple[float, float, float, float, int]] = []
    for candidate in candidates:
        step, phase, rmse, single_step_ratio, single_step_count = _fit_lattice(
            relative_onsets,
            candidate,
        )
        candidate_fits.append(
            (step, phase, rmse, single_step_ratio, single_step_count)
        )
        if (
            _MIN_AUTO_GRID_MS <= step <= _MAX_AUTO_GRID_MS
            and rmse <= _MAX_LATTICE_RMSE_MS
            and single_step_ratio >= _MIN_SINGLE_STEP_RATIO
        ):
            acceptable.append((step, phase, rmse))

    if not acceptable:
        diagnostics = sorted(
            (fit for fit in candidate_fits if 170 <= fit[0] <= 390),
            key=lambda fit: (fit[2], -fit[3]),
        )[:5]
        if not diagnostics:
            diagnostics = sorted(candidate_fits, key=lambda fit: (fit[2], -fit[3]))[:5]
        summary = "; ".join(
            f"{step:.2f} ms/RMS {rmse:.2f}/single {ratio:.1%} ({count})"
            for step, _phase, rmse, ratio, count in diagnostics
        )
        raise ValueError(
            "could not estimate a stable onset grid "
            f"(candidate fits: {summary}); use grid_mode='fixed' "
            "or provide a fixed grid_ms"
        )
    return min(acceptable, key=lambda fit: (fit[0], fit[2]))[:2]


def _fit_lattice(
    onsets_ms: Sequence[float],
    initial_step: float,
) -> tuple[float, float, float, float, int]:
    step = initial_step
    phase = 0.0
    indices: list[int] = []
    for _ in range(8):
        indices = [_round_index((onset - phase) / step) for onset in onsets_ms]
        mean_index = sum(indices) / len(indices)
        mean_onset = sum(onsets_ms) / len(onsets_ms)
        denominator = sum((index - mean_index) ** 2 for index in indices)
        if denominator == 0:
            break
        refined_step = sum(
            (index - mean_index) * (onset - mean_onset)
            for index, onset in zip(indices, onsets_ms)
        ) / denominator
        if refined_step <= 0 or not math.isfinite(refined_step):
            break
        refined_phase = mean_onset - refined_step * mean_index
        if abs(refined_step - step) < 1e-8 and abs(refined_phase - phase) < 1e-8:
            step, phase = refined_step, refined_phase
            break
        step, phase = refined_step, refined_phase

    indices = [_round_index((onset - phase) / step) for onset in onsets_ms]
    residuals = [
        onset - (phase + index * step)
        for onset, index in zip(onsets_ms, indices)
    ]
    rmse = math.sqrt(sum(residual * residual for residual in residuals) / len(residuals))
    single_steps = sum(
        later_index - earlier_index == 1
        for earlier_index, later_index in pairwise(indices)
    )
    transition_count = max(1, len(indices) - 1)
    return step, phase, rmse, single_steps / transition_count, single_steps


def quantize(time_ms: float, grid_ms: float) -> int:
    """Round a time in milliseconds to the nearest grid point."""
    if not math.isfinite(time_ms):
        raise ValueError("time_ms must be finite")
    if not math.isfinite(grid_ms) or grid_ms <= 0:
        raise ValueError("grid_ms must be a positive finite number")

    grid_time = math.floor(time_ms / grid_ms + 0.5) * grid_ms
    return math.floor(grid_time + 0.5)


def quantize_lattice(time_ms: float, grid_ms: float, phase_ms: float) -> int:
    """Quantize using an indexed lattice and round only the final millisecond."""
    if not math.isfinite(time_ms):
        raise ValueError("time_ms must be finite")
    if not math.isfinite(grid_ms) or grid_ms <= 0:
        raise ValueError("grid_ms must be a positive finite number")
    if not math.isfinite(phase_ms):
        raise ValueError("phase_ms must be finite")
    index = _round_index((time_ms - phase_ms) / grid_ms)
    return math.floor(index * grid_ms + 0.5)


def _round_index(value: float) -> int:
    return math.floor(value + 0.5)
