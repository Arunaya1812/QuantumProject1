"""Unified adaptive-threshold and Random Forest eavesdropper detector."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .adaptive_threshold import AdaptiveThresholdDetector
from .features import FEATURE_COLUMNS, FeatureVector, OnlineFeatureEngineer


@dataclass(frozen=True)
class DetectionDecision:
    window_index: int
    attack_detected: bool
    adaptive_flag: bool
    ml_flag: bool
    ml_probability: float
    adaptive_threshold: float | None
    baseline_update_allowed: bool
    reason: str
    features: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnifiedAdaptiveMLDetector:
    """
    Fuse the interpretable adaptive QBER alarm with the trained classifier.

    The ML decision is also a guard on adaptation: a window that the model
    considers suspicious is never fed back into the adaptive baseline. This
    prevents a sustained low-intensity attack from slowly teaching the
    threshold that attack traffic is normal.
    """

    def __init__(
        self,
        model: Any,
        *,
        ml_probability_threshold: float = 0.5,
        calibration_windows: int = 10,
        roll_window: int = 5,
        threshold_k: float = 3.0,
        ema_alpha: float = 0.1,
    ):
        if not 0.0 <= ml_probability_threshold <= 1.0:
            raise ValueError("ml_probability_threshold must be between 0 and 1")
        self.model = model
        self.ml_probability_threshold = ml_probability_threshold
        self.features = OnlineFeatureEngineer(roll_window, calibration_windows)
        self.adaptive = AdaptiveThresholdDetector(
            calibration_windows=calibration_windows,
            k=threshold_k,
            ema_alpha=ema_alpha,
        )
        self.history: list[DetectionDecision] = []

    @classmethod
    def from_joblib(cls, model_path: str | Path, **kwargs):
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("joblib is required to load the trained detector") from exc
        loaded = joblib.load(model_path)
        model = loaded.get("model") if isinstance(loaded, dict) and "model" in loaded else loaded
        return cls(model, **kwargs)

    def _ml_probability(self, vector: FeatureVector) -> float:
        # A DataFrame preserves the feature names used while training and
        # avoids scikit-learn's feature-name mismatch warning.
        try:
            import pandas as pd
            row = pd.DataFrame([vector.as_dict()], columns=FEATURE_COLUMNS)
        except ImportError:
            row = [vector.as_row()]

        if hasattr(self.model, "predict_proba"):
            probabilities = self.model.predict_proba(row)[0]
            classes = list(getattr(self.model, "classes_", [0, 1]))
            try:
                return float(probabilities[classes.index(1)])
            except (ValueError, IndexError):
                return float(probabilities[-1])
        return float(self.model.predict(row)[0])

    def update(self, qber: float, signal_decoy_gap: float) -> DetectionDecision:
        vector = self.features.update(qber, signal_decoy_gap)
        probability = self._ml_probability(vector)
        ml_flag = probability >= self.ml_probability_threshold

        # ML-suspicious observations can be evaluated by the adaptive rule,
        # but cannot move its baseline.
        adaptive_flag = self.adaptive.update(qber, allow_adaptation=not ml_flag)
        ready = self.features.calibrated and self.adaptive.calibrated
        attack_detected = bool(ready and (adaptive_flag or ml_flag))

        if not ready:
            reason = "calibrating"
        elif adaptive_flag and ml_flag:
            reason = "adaptive_and_ml"
        elif ml_flag:
            reason = "ml_pattern"
        elif adaptive_flag:
            reason = "adaptive_qber"
        else:
            reason = "normal"

        decision = DetectionDecision(
            window_index=len(self.history),
            attack_detected=attack_detected,
            adaptive_flag=bool(adaptive_flag),
            ml_flag=bool(ml_flag),
            ml_probability=probability,
            adaptive_threshold=self.adaptive.history[-1]["threshold"],
            baseline_update_allowed=bool(not ml_flag),
            reason=reason,
            features=vector.as_dict(),
        )
        self.history.append(decision)
        return decision
