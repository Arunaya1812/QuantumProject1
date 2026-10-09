"""Evaluate every detector metric on probabilistic and hybrid-Qiskit timelines.

Qiskit Aer generates BB84 preparation/measurement and therefore QBER.  The
decoy/PNS statistics remain in the optical statistical simulator, so results
are deliberately labelled ``hybrid_qiskit`` rather than hardware results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bb84.adaptive_threshold import AdaptiveMultiSignalDetector, StaticThresholdDetector
from bb84.timeline import simulate_timeline
from train_phase5_unified import (
    FUSION_COLUMNS,
    build_fusion_features,
    detection_delay,
    exact_mcnemar_pvalue,
    metric_bundle,
    online_probabilities,
)


MODEL_PATH = Path("models/phase5_unified.joblib")
OUTPUT_JSON = Path("outputs/phase5_qiskit_evaluation.json")
OUTPUT_CSV = Path("outputs/phase5_qiskit_metrics.csv")
OUTPUT_PLOT = Path("outputs/phase5_qiskit_detector_metrics.png")
BACKEND_PLOT = Path("outputs/phase5_backend_comparison.png")


SCENARIOS = [
    ("none", 0.0),
    ("intercept_resend", 1.0),
    ("intercept_resend", 0.5),
    ("intercept_resend", 0.2),
    ("pns", 1.0),
]


def make_dataset(backend, windows, photons, repeats, noise_levels):
    rows = []
    timeline_id = 0
    started = time.perf_counter()
    for noise_index, noise in enumerate(noise_levels):
        for scenario_index, (attack, intensity) in enumerate(SCENARIOS):
            for repeat in range(repeats):
                seed = 81000 + noise_index * 1000 + scenario_index * 100 + repeat
                rows.extend(simulate_timeline(
                    timeline_id=timeline_id,
                    n_windows=windows,
                    photons_per_window=photons,
                    decoy_pulses_per_window=photons,
                    noise_level=noise,
                    attack_type=attack,
                    attack_intensity=intensity,
                    attack_start_frac=0.5,
                    seed=seed,
                    protocol_backend=backend,
                ))
                timeline_id += 1
                print(
                    f"[{backend}] timeline {timeline_id}: {attack} "
                    f"intensity={intensity} noise={noise}"
                )
    return pd.DataFrame(rows), time.perf_counter() - started


def evaluate(frame, package):
    base_model = package["base_model"]
    fusion_model = package["fusion_model"]
    probabilities = online_probabilities(frame, base_model)
    fusion = build_fusion_features(frame, probabilities)
    unified_scores = fusion_model.predict_proba(fusion[FUSION_COLUMNS])[:, 1]
    truth = fusion.is_attack.to_numpy(dtype=int)

    predictions = {
        "ml": (fusion.ml_probability.to_numpy() >= 0.5).astype(int),
        "unified": (unified_scores >= 0.5).astype(int),
    }
    scores = {
        "ml": fusion.ml_probability.to_numpy(),
        "unified": unified_scores,
    }
    static_pred, adaptive_pred, static_scores = [], [], []
    ordered_parts = []
    for _, timeline in frame.groupby("timeline_id"):
        timeline = timeline.sort_values("window_idx")
        ordered_parts.append(timeline)
        static = StaticThresholdDetector(fixed_threshold=0.11)
        adaptive = AdaptiveMultiSignalDetector()
        for row in timeline.itertuples():
            static_pred.append(int(static.update(row.qber)))
            adaptive_pred.append(int(adaptive.update(row.qber, row.signal_decoy_gap)))
            static_scores.append(float(row.qber))
    predictions["static"] = np.asarray(static_pred)
    predictions["adaptive"] = np.asarray(adaptive_pred)
    scores["static"] = np.asarray(static_scores)
    scores["adaptive"] = predictions["adaptive"].astype(float)
    ordered = pd.concat(ordered_parts, ignore_index=True)

    metrics = {
        name: metric_bundle(truth, predictions[name], scores[name])
        for name in ["static", "adaptive", "ml", "unified"]
    }
    delays = {
        name: detection_delay(ordered, predictions[name])
        for name in ["static", "adaptive", "ml", "unified"]
    }
    significance = exact_mcnemar_pvalue(truth, predictions["ml"], predictions["unified"])
    return metrics, delays, significance


def flatten_metrics(results):
    rows = []
    for backend, backend_result in results.items():
        for detector, values in backend_result["metrics"].items():
            row = {"backend": backend, "detector": detector}
            row.update({k: v for k, v in values.items() if k != "confusion_matrix"})
            row.update(values["confusion_matrix"])
            rows.append(row)
    return pd.DataFrame(rows)


def make_plots(table):
    qiskit = table[table.backend == "hybrid_qiskit"].set_index("detector")
    fields = ["accuracy", "precision", "recall_detection_rate", "f1_score", "specificity"]
    labels = ["Accuracy", "Precision", "Recall", "F1", "Specificity"]
    names = ["static", "adaptive", "ml", "unified"]
    x = np.arange(len(fields))
    width = 0.19
    fig, ax = plt.subplots(figsize=(11, 6))
    for index, name in enumerate(names):
        label = "ML" if name == "ml" else name.title()
        bars = ax.bar(
            x + (index - 1.5) * width, qiskit.loc[name, fields], width, label=label
        )
        ax.bar_label(bars, fmt="%.3f", fontsize=7, padding=2, rotation=90)
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Score")
    ax.set_title("Detector metrics on hybrid Qiskit-Aer timelines")
    ax.legend(ncol=4, loc="lower right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUTPUT_PLOT, dpi=180)
    plt.close(fig)

    unified = table[table.detector == "unified"].set_index("backend")
    x = np.arange(len(fields))
    fig, ax = plt.subplots(figsize=(10, 6))
    probabilistic_bars = ax.bar(
        x - 0.18, unified.loc["probabilistic", fields], 0.36, label="Probabilistic"
    )
    qiskit_bars = ax.bar(
        x + 0.18, unified.loc["hybrid_qiskit", fields], 0.36, label="Hybrid Qiskit"
    )
    ax.bar_label(probabilistic_bars, fmt="%.3f", fontsize=9, padding=3)
    ax.bar_label(qiskit_bars, fmt="%.3f", fontsize=9, padding=3)
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Score")
    ax.set_title("Unified detector: backend validation (same scenarios and seeds)")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(BACKEND_PLOT, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=int, default=30)
    parser.add_argument("--photons", type=int, default=250)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--noise", type=float, nargs="+", default=[0.02, 0.04])
    args = parser.parse_args()
    if args.windows < 20:
        raise ValueError("use at least 20 windows so 10 clean calibration windows remain")
    package = joblib.load(MODEL_PATH)
    Path("outputs").mkdir(exist_ok=True)

    results = {}
    for backend, label in [("probabilistic", "probabilistic"), ("qiskit", "hybrid_qiskit")]:
        frame, runtime = make_dataset(
            backend, args.windows, args.photons, args.repeats, args.noise
        )
        metrics, delays, significance = evaluate(frame, package)
        results[label] = {
            "metrics": metrics,
            "detection_delay": delays,
            "mcnemar_unified_vs_ml": significance,
            "runtime_seconds": runtime,
        }

    table = flatten_metrics(results)
    table.to_csv(OUTPUT_CSV, index=False)
    make_plots(table)
    report = {
        "evaluation_design": {
            "timelines_per_backend": len(args.noise) * len(SCENARIOS) * args.repeats,
            "windows_per_timeline": args.windows,
            "photons_per_window": args.photons,
            "attack_start_fraction": 0.5,
            "noise_levels": args.noise,
            "paired_scenarios_and_seeds": True,
            "qiskit_execution": "Qiskit Aer stabilizer circuits, locally simulated",
            "decoy_execution": "statistical weak-pulse model for both backends",
        },
        "results": results,
        "honest_interpretation": (
            "The hybrid-Qiskit result is independent circuit-level validation, not IBM "
            "hardware evidence. A higher score on either backend is an observed result, not "
            "proof that the backend is inherently superior. The important comparison is "
            "Unified versus Static, Adaptive, and ML on the same backend."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Saved -> {OUTPUT_JSON}")
    print(f"Saved -> {OUTPUT_CSV}")
    print(f"Saved -> {OUTPUT_PLOT}")
    print(f"Saved -> {BACKEND_PLOT}")


if __name__ == "__main__":
    main()
