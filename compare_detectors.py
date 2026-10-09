"""
compare_detectors.py
-----------------------
The key demonstration script for your report/defense. It runs FOUR
detectors side by side on the same simulated timelines and shows why
the adaptive + ML approach is better than a naive fixed threshold:

  1. StaticThresholdDetector  - conventional fixed 11% QBER threshold
  2. AdaptiveMultiSignalDetector - adaptive QBER + decoy-gap baselines
  3. Trained ML model (Random Forest, using temporal features)
  4. Unified detector - stacked adaptive evidence + RF confidence/persistence

It generates plots (outputs/comparison_*.png) for a few representative
scenarios:
  (a) Gradual environmental drift, no attack -> static threshold false-alarms,
      adaptive threshold correctly tracks the drift and stays quiet.
  (b) Stealthy low-intensity intercept-resend attack -> static threshold
      misses it (QBER bump too small), adaptive + ML both catch it.
  (c) PNS attack -> QBER-only detectors (static and adaptive) miss it
      completely (by design, PNS doesn't raise QBER), but the ML model
      catches it because it was trained on the signal_decoy_gap feature too.

Run (after train_model.py):
    python compare_detectors.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import joblib

from bb84.timeline import simulate_timeline
from bb84.adaptive_threshold import AdaptiveMultiSignalDetector, StaticThresholdDetector
from bb84.unified_detector import UnifiedAdaptiveMLDetector
from feature_engineering import engineer_features_for_timeline
from train_model import FEATURE_COLUMNS

MODEL_PATH = "models/phase5_unified.joblib"
OUT_DIR = "outputs"


def run_threshold_detectors(qber_series, gap_series):
    static = StaticThresholdDetector(fixed_threshold=0.11)
    adaptive = AdaptiveMultiSignalDetector(
        calibration_windows=10, qber_k=3.0, gap_k=3.0, ema_alpha=0.1
    )

    static_flags, adaptive_flags = [], []
    static_thresholds, adaptive_thresholds, adaptive_gap_thresholds = [], [], []

    for qber, gap in zip(qber_series, gap_series):
        sf = static.update(qber)
        af = adaptive.update(qber, gap)
        static_flags.append(sf)
        adaptive_flags.append(af)
        static_thresholds.append(static.history[-1]["threshold"])
        adaptive_thresholds.append(adaptive.history[-1]["qber_threshold"])
        adaptive_gap_thresholds.append(adaptive.history[-1]["gap_threshold"])

    return {
        "static_flags": static_flags,
        "adaptive_flags": adaptive_flags,
        "static_thresholds": static_thresholds,
        "adaptive_thresholds": adaptive_thresholds,
        "adaptive_gap_thresholds": adaptive_gap_thresholds,
    }


def run_ml_detectors(df_timeline):
    package = joblib.load(MODEL_PATH)
    clf = package["base_model"]
    featured = engineer_features_for_timeline(df_timeline)
    X = featured[FEATURE_COLUMNS]
    preds = clf.predict(X)
    unified = UnifiedAdaptiveMLDetector(
        clf,
        fusion_model=package["fusion_model"],
        fusion_columns=package["fusion_columns"],
        fusion_guard_probability=package["fusion_config"]["guard_probability"],
    )
    unified_predictions = [
        unified.update(row.qber, row.signal_decoy_gap).attack_detected
        for row in df_timeline.sort_values("window_idx").itertuples()
    ]
    return preds, np.asarray(unified_predictions, dtype=int), featured


def plot_scenario(name, df_timeline, results, ml_preds, unified_preds, title):
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    w = df_timeline["window_idx"]
    qber = df_timeline["qber"]
    truth = df_timeline["is_attack"]

    # --- Top plot: QBER + thresholds ---
    ax = axes[0]
    ax.plot(w, qber, label="QBER (observed)", color="tab:blue", linewidth=1.2)
    ax.plot(w, results["static_thresholds"], label="Static threshold", color="tab:red",
            linestyle="--")
    ax.plot(w, results["adaptive_thresholds"], label="Adaptive threshold", color="tab:green",
            linestyle="--")

    attack_start = truth[truth == 1].index.min() if (truth == 1).any() else None
    if attack_start is not None:
        ax.axvline(df_timeline.loc[attack_start, "window_idx"], color="black",
                   linestyle=":", label="True attack start")

    ax.set_ylabel("QBER")
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8)

    # --- Middle plot: decoy-state evidence and adaptive gap threshold ---
    ax_gap = axes[1]
    ax_gap.plot(w, df_timeline["signal_decoy_gap"], label="Signal-decoy gap", color="tab:orange")
    ax_gap.plot(w, results["adaptive_gap_thresholds"], label="Adaptive gap threshold",
                color="tab:green", linestyle="--")
    ax_gap.set_ylabel("Detection-rate gap")
    ax_gap.legend(loc="upper left", fontsize=8)

    # --- Bottom plot: detection flags per detector ---
    ax2 = axes[2]
    ax2.step(w, [1 if f else 0 for f in results["static_flags"]], where="mid",
              label="Static flagged", color="tab:red", alpha=0.7)
    ax2.step(w, [2 if f else 0 for f in results["adaptive_flags"]], where="mid",
              label="Adaptive flagged", color="tab:green", alpha=0.7)
    ax2.step(w, [3 if f else 0 for f in ml_preds], where="mid",
              label="ML model flagged", color="tab:purple", alpha=0.7)
    ax2.step(w, [4 if f else 0 for f in unified_preds], where="mid",
              label="Unified flagged", color="tab:blue", linewidth=1.8)
    ax2.set_yticks([0, 1, 2, 3, 4])
    ax2.set_yticklabels(["-", "Static", "Adaptive", "ML", "Unified"])
    ax2.set_xlabel("Window index (time)")
    ax2.set_ylabel("Detector output")
    ax2.legend(loc="upper left", fontsize=8)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, f"comparison_{name}.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"Saved {path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    scenarios = [
        {
            "name": "no_attack_drift",
            "title": "Scenario A: No attack, normal channel variation",
            "attack_type": "none",
            "attack_intensity": 0.0,
            "noise_level": 0.025,
        },
        {
            "name": "stealthy_intercept",
            "title": "Scenario B: Stealthy intercept-resend (intensity=0.2)",
            "attack_type": "intercept_resend",
            "attack_intensity": 0.2,
            "noise_level": 0.02,
        },
        {
            "name": "pns_attack",
            "title": "Scenario C: PNS attack (QBER barely changes)",
            "attack_type": "pns",
            "attack_intensity": 1.0,
            "noise_level": 0.02,
        },
    ]

    for i, scenario in enumerate(scenarios):
        rows = simulate_timeline(
            timeline_id=9000 + i,
            n_windows=120,
            photons_per_window=250,
            decoy_pulses_per_window=250,
            noise_level=scenario["noise_level"],
            attack_type=scenario["attack_type"],
            attack_intensity=scenario["attack_intensity"],
            attack_start_frac=0.5,
            seed=1000 + i,
        )
        df_timeline = pd.DataFrame(rows)

        results = run_threshold_detectors(
            df_timeline["qber"].tolist(), df_timeline["signal_decoy_gap"].tolist()
        )
        ml_preds, unified_preds, _ = run_ml_detectors(df_timeline)

        plot_scenario(
            scenario["name"], df_timeline, results, ml_preds, unified_preds, scenario["title"]
        )

        # Print a short numeric summary too
        n_attack_windows = int(df_timeline["is_attack"].sum())
        if n_attack_windows > 0:
            static_recall = np.mean(
                [f for f, t in zip(results["static_flags"], df_timeline["is_attack"]) if t == 1]
            )
            adaptive_recall = np.mean(
                [f for f, t in zip(results["adaptive_flags"], df_timeline["is_attack"]) if t == 1]
            )
            ml_recall = np.mean(
                [p for p, t in zip(ml_preds, df_timeline["is_attack"]) if t == 1]
            )
            unified_recall = np.mean(
                [p for p, t in zip(unified_preds, df_timeline["is_attack"]) if t == 1]
            )
            print(f"  {scenario['name']}: static_recall={static_recall:.2f}  "
                  f"adaptive_recall={adaptive_recall:.2f}  ml_recall={ml_recall:.2f}  "
                  f"unified_recall={unified_recall:.2f}")
        else:
            static_fp = np.mean(results["static_flags"])
            adaptive_fp = np.mean(results["adaptive_flags"])
            ml_fp = np.mean(ml_preds)
            unified_fp = np.mean(unified_preds)
            print(f"  {scenario['name']}: static_false_positive_rate={static_fp:.2f}  "
                  f"adaptive_false_positive_rate={adaptive_fp:.2f}  ml_false_positive_rate={ml_fp:.2f}  "
                  f"unified_false_positive_rate={unified_fp:.2f}")


if __name__ == "__main__":
    main()
