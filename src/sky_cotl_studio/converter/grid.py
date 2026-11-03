"""Onset grid estimation and time quantization."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

_MIN_AUTO_GRID_MS = 100.0
_MAX_AUTO_GRID_MS = 1000.0
_GRID_DIVISORS = (1, 2, 4, 8)
_MAX_LATTICE_RMSE_MS = 25.0
_MIN_AUTO_ONSETS = 5
_MIN_ODD_ONSETS = 2
_MAX_FINE_GRID_RMSE_RATIO = 0.75
_LATTICE_RESIDUAL_TOLERANCE_MS = 25.0


class GridEstimationError(ValueError):
    """Raised when onset times do not support a stable fitted grid."""


@dataclass(frozen=True)
class _LatticeFit:
    step_ms: float
    phase_ms: float
    rmse_ms: float
    odd_onset_count: int


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
    A finer binary grid is accepted only when its step is at least 100 ms,
    its RMS residual is at most 25 ms and at most 75% of the coarser fit's
    RMS, and at least two onsets fall within 25 ms of an odd grid index.
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

    fits_by_step: dict[float, _LatticeFit] = {}
    for candidate in candidates:
        fit = _fit_lattice(relative_onsets, candidate)
        if not _MIN_AUTO_GRID_MS <= fit.step_ms <= _MAX_AUTO_GRID_MS:
            continue
        step_key = round(fit.step_ms, 1)
        previous_fit = fits_by_step.get(step_key)
        if previous_fit is None or fit.rmse_ms < previous_fit.rmse_ms:
            fits_by_step[step_key] = fit

    stable_fits = [
        fit
        for fit in fits_by_step.values()
        if fit.rmse_ms <= _LATTICE_RESIDUAL_TOLERANCE_MS
    ]
    if not stable_fits:
        diagnostics = sorted(fits_by_step.values(), key=lambda fit: fit.rmse_ms)[:5]
        summary = "; ".join(
            f"{fit.step_ms:.2f} ms/RMS {fit.rmse_ms:.2f}"
            for fit in diagnostics
        )
        raise GridEstimationError(
            "could not estimate a stable onset grid "
            f"(candidate fits: {summary}); use grid_mode='fixed' "
            "or provide a fixed grid_ms"
        )

    selected_fit = max(stable_fits, key=lambda fit: fit.step_ms)
    while True:
        finer_fits = [
            fit
            for fit in stable_fits
            if _is_binary_subdivision(selected_fit.step_ms, fit.step_ms)
            and fit.odd_onset_count >= _MIN_ODD_ONSETS
            and fit.rmse_ms
            <= selected_fit.rmse_ms * _MAX_FINE_GRID_RMSE_RATIO
        ]
        if not finer_fits:
            break
        selected_fit = min(finer_fits, key=lambda fit: (fit.step_ms, fit.rmse_ms))

    return selected_fit.step_ms, selected_fit.phase_ms


def _fit_lattice(
    onsets_ms: Sequence[float],
    initial_step: float,
) -> _LatticeFit:
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
    odd_onset_count = sum(
        index % 2 == 1 and abs(residual) <= _LATTICE_RESIDUAL_TOLERANCE_MS
        for index, residual in zip(indices, residuals)
    )
    return _LatticeFit(step, phase, rmse, odd_onset_count)


def _is_binary_subdivision(coarser_step_ms: float, finer_step_ms: float) -> bool:
    if finer_step_ms >= coarser_step_ms:
        return False
    return abs(coarser_step_ms - 2 * finer_step_ms) <= max(
        2.0,
        finer_step_ms * 0.02,
    )


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
