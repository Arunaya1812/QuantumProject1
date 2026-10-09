"""Unified adaptive-threshold and Random Forest eavesdropper detector."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
import statistics
from typing import Any

from .adaptive_threshold import AdaptiveMultiSignalDetector
from .features import FEATURE_COLUMNS, FeatureVector, OnlineFeatureEngineer


@dataclass(frozen=True)
class DetectionDecision:
    window_index: int
    attack_detected: bool
    adaptive_flag: bool
    qber_adaptive_flag: bool
    gap_adaptive_flag: bool
    ml_flag: bool
    ml_probability: float
    fusion_probability: float
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
        fusion_model: Any | None = None,
        fusion_columns: list[str] | None = None,
        fusion_guard_probability: float = 0.25,
    ):
        if not 0.0 <= ml_probability_threshold <= 1.0:
            raise ValueError("ml_probability_threshold must be between 0 and 1")
        self.model = model
        self.fusion_model = fusion_model
        self.fusion_columns = fusion_columns or [
            "ml_probability",
            "ml_roll_mean_3",
            "ml_roll_max_3",
            "ml_delta",
            "qber_z",
            "gap_z",
            "qber_adaptive_flag",
            "gap_adaptive_flag",
        ]
        self.fusion_guard_probability = fusion_guard_probability
        self.ml_probability_threshold = ml_probability_threshold
        self.features = OnlineFeatureEngineer(roll_window, calibration_windows)
        self.multi_adaptive = AdaptiveMultiSignalDetector(
            calibration_windows=calibration_windows,
            qber_k=threshold_k,
            gap_k=threshold_k,
            ema_alpha=ema_alpha,
        )
        # Backward-compatible public handle used by earlier tests and demos.
        self.adaptive = self.multi_adaptive.qber
        self._calibration_windows = calibration_windows
        self._qber_calibration: list[float] = []
        self._gap_calibration: list[float] = []
        self._probability_history = deque(maxlen=3)
        self._previous_probability: float | None = None
        self.history: list[DetectionDecision] = []

    @classmethod
    def from_joblib(cls, model_path: str | Path, **kwargs):
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("joblib is required to load the trained detector") from exc
        loaded = joblib.load(model_path)
        if isinstance(loaded, dict) and "base_model" in loaded:
            config = loaded.get("fusion_config", {})
            return cls(
                loaded["base_model"],
                fusion_model=loaded.get("fusion_model"),
                fusion_columns=loaded.get("fusion_columns"),
                fusion_guard_probability=config.get("guard_probability", 0.25),
                **kwargs,
            )
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

    @staticmethod
    def _positive_probability(model: Any, row: Any) -> float:
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(row)[0]
            classes = list(getattr(model, "classes_", [0, 1]))
            try:
                return float(probabilities[classes.index(1)])
            except (ValueError, IndexError):
                return float(probabilities[-1])
        return float(model.predict(row)[0])

    @staticmethod
    def _zscore(value: float, calibration: list[float]) -> float:
        if len(calibration) < 2:
            return 0.0
        std = statistics.stdev(calibration) or 1e-4
        return max(-10.0, min(10.0, (value - statistics.mean(calibration)) / std))

    def update(self, qber: float, signal_decoy_gap: float) -> DetectionDecision:
        vector = self.features.update(qber, signal_decoy_gap)
        probability = self._ml_probability(vector)
        ml_flag = probability >= self.ml_probability_threshold

        if len(self._qber_calibration) < self._calibration_windows:
            self._qber_calibration.append(float(qber))
            self._gap_calibration.append(float(signal_decoy_gap))

        # A low guard probability quarantines suspicious windows before the
        # final decision, preventing slow baseline-poisoning attacks.
        guard_threshold = (
            self.fusion_guard_probability if self.fusion_model is not None
            else self.ml_probability_threshold
        )
        baseline_update_allowed = probability < guard_threshold
        adaptive_flag = self.multi_adaptive.update(
            qber,
            signal_decoy_gap,
            allow_adaptation=baseline_update_allowed,
        )
        adaptive_state = self.multi_adaptive.history[-1]
        qber_flag = adaptive_state["qber_flag"]
        gap_flag = adaptive_state["gap_flag"]
        ready = self.features.calibrated and self.multi_adaptive.calibrated

        previous_probability = self._previous_probability
        self._probability_history.append(probability)
        self._previous_probability = probability
        fusion_features = {
            "ml_probability": probability,
            "ml_roll_mean_3": statistics.mean(self._probability_history),
            "ml_roll_max_3": max(self._probability_history),
            "ml_delta": (
                0.0 if previous_probability is None
                else probability - previous_probability
            ),
            "qber_z": self._zscore(qber, self._qber_calibration),
            "gap_z": self._zscore(signal_decoy_gap, self._gap_calibration),
            "qber_adaptive_flag": float(qber_flag),
            "gap_adaptive_flag": float(gap_flag),
        }

        if self.fusion_model is not None:
            try:
                import pandas as pd
                fusion_row = pd.DataFrame(
                    [fusion_features], columns=self.fusion_columns
                )
            except ImportError:
                fusion_row = [[fusion_features[name] for name in self.fusion_columns]]
            fusion_probability = self._positive_probability(self.fusion_model, fusion_row)
            fusion_flag = fusion_probability >= 0.5
            attack_detected = bool(ready and fusion_flag)
        else:
            fusion_probability = max(probability, float(adaptive_flag))
            attack_detected = bool(ready and (adaptive_flag or ml_flag))

        if not ready:
            reason = "calibrating"
        elif self.fusion_model is not None and attack_detected:
            reason = "stacked_adaptive_ml_fusion"
        elif self.fusion_model is not None:
            reason = "fusion_normal"
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
            qber_adaptive_flag=bool(qber_flag),
            gap_adaptive_flag=bool(gap_flag),
            ml_flag=bool(ml_flag),
            ml_probability=probability,
            fusion_probability=fusion_probability,
            adaptive_threshold=self.adaptive.history[-1]["threshold"],
            baseline_update_allowed=bool(baseline_update_allowed),
            reason=reason,
            features={**vector.as_dict(), **fusion_features},
        )
        self.history.append(decision)
        return decision
