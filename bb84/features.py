"""Online temporal feature extraction for real-time detector integration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import statistics


FEATURE_COLUMNS = [
    "qber",
    "signal_decoy_gap",
    "qber_roll_mean",
    "qber_roll_std",
    "qber_slope",
    "gap_roll_mean",
    "gap_roll_std",
    "error_burst_count",
]


@dataclass(frozen=True)
class FeatureVector:
    qber: float
    signal_decoy_gap: float
    qber_roll_mean: float
    qber_roll_std: float
    qber_slope: float
    gap_roll_mean: float
    gap_roll_std: float
    error_burst_count: float

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in FEATURE_COLUMNS}

    def as_row(self) -> list[float]:
        return [float(getattr(self, name)) for name in FEATURE_COLUMNS]


class OnlineFeatureEngineer:
    """Compute Phase 2 features using only data available up to this window."""

    def __init__(self, roll_window: int = 5, calibration_windows: int = 10):
        if roll_window < 1 or calibration_windows < 2:
            raise ValueError("roll_window must be >= 1 and calibration_windows >= 2")
        self.roll_window = roll_window
        self.calibration_windows = calibration_windows
        self._qber = deque(maxlen=roll_window)
        self._gap = deque(maxlen=roll_window)
        self._roll_means: list[float] = []
        self._calibration: list[float] = []
        self._burst_flags = deque(maxlen=roll_window)
        self._baseline_mean: float | None = None
        self._baseline_std: float | None = None

    @staticmethod
    def _sample_std(values) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0

    @property
    def calibrated(self) -> bool:
        return len(self._calibration) >= self.calibration_windows

    def update(self, qber: float, signal_decoy_gap: float) -> FeatureVector:
        qber = float(qber)
        gap = float(signal_decoy_gap)
        if not (math.isfinite(qber) and math.isfinite(gap)):
            raise ValueError("feature inputs must be finite")

        if len(self._calibration) < self.calibration_windows:
            self._calibration.append(qber)
            self._baseline_mean = statistics.mean(self._calibration)
            self._baseline_std = self._sample_std(self._calibration) or 1e-4

        self._qber.append(qber)
        self._gap.append(gap)
        qber_mean = statistics.mean(self._qber)
        gap_mean = statistics.mean(self._gap)
        qber_std = self._sample_std(self._qber)
        gap_std = self._sample_std(self._gap)

        if len(self._roll_means) >= self.roll_window:
            qber_slope = qber_mean - self._roll_means[-self.roll_window]
        else:
            qber_slope = 0.0
        self._roll_means.append(qber_mean)

        threshold = self._baseline_mean + 3.0 * self._baseline_std
        self._burst_flags.append(int(qber > threshold))

        return FeatureVector(
            qber=qber,
            signal_decoy_gap=gap,
            qber_roll_mean=qber_mean,
            qber_roll_std=qber_std,
            qber_slope=qber_slope,
            gap_roll_mean=gap_mean,
            gap_roll_std=gap_std,
            error_burst_count=float(sum(self._burst_flags)),
        )
