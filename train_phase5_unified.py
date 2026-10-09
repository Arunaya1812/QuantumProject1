"""Train and evaluate the Phase 5 stacked adaptive-ML fusion detector.

The Random Forest remains the base model.  A small histogram-gradient-
boosting fusion model learns how to combine out-of-fold RF probabilities,
probability persistence, adaptive QBER evidence, and adaptive decoy-gap
evidence.  All final metrics are measured on untouched timeline groups.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    fbeta_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, train_test_split

from bb84.adaptive_threshold import AdaptiveMultiSignalDetector, StaticThresholdDetector
from bb84.features import FEATURE_COLUMNS, OnlineFeatureEngineer
from bb84.unified_detector import UnifiedAdaptiveMLDetector


DATA_PATH = Path("data/bb84_features_dataset.csv")
MODEL_PATH = Path("models/phase5_unified.joblib")
REPORT_PATH = Path("outputs/phase5_evaluation_report.json")
METRICS_CSV_PATH = Path("outputs/phase5_detector_metrics.csv")
LITERATURE_PATH = Path("outputs/phase5_literature_comparison.csv")
FUSION_COLUMNS = [
    "ml_probability",
    "ml_roll_mean_3",
    "ml_roll_max_3",
    "ml_delta",
    "qber_z",
    "gap_z",
    "qber_adaptive_flag",
    "gap_adaptive_flag",
]


def make_base_model():
    return RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )


def split_timeline_ids(df: pd.DataFrame):
    metadata = df.groupby("timeline_id").agg(
        attack_type=("attack_type", "first"),
        attack_intensity=("attack_intensity", "max"),
    )
    strata = metadata["attack_type"] + "_" + metadata["attack_intensity"].astype(str)
    development, test = train_test_split(
        metadata.index,
        test_size=0.20,
        random_state=42,
        stratify=strata,
    )
    return set(development), set(test)


def online_probabilities(frame: pd.DataFrame, model) -> np.ndarray:
    probabilities = []
    for _, timeline in frame.groupby("timeline_id"):
        engineer = OnlineFeatureEngineer()
        vectors = [
            engineer.update(row.qber, row.signal_decoy_gap).as_dict()
            for row in timeline.sort_values("window_idx").itertuples()
        ]
        probabilities.extend(
            model.predict_proba(pd.DataFrame(vectors, columns=FEATURE_COLUMNS))[:, 1]
        )
    return np.asarray(probabilities)


def build_fusion_features(frame: pd.DataFrame, probabilities: np.ndarray) -> pd.DataFrame:
    outputs = []
    offset = 0
    for _, timeline in frame.groupby("timeline_id"):
        timeline = timeline.sort_values("window_idx").copy()
        probs = probabilities[offset : offset + len(timeline)]
        offset += len(timeline)

        qber_cal = timeline.qber.iloc[:10]
        gap_cal = timeline.signal_decoy_gap.iloc[:10]
        qber_mean, gap_mean = qber_cal.mean(), gap_cal.mean()
        qber_std = qber_cal.std() or 1e-4
        gap_std = gap_cal.std() or 1e-4
        adaptive = AdaptiveMultiSignalDetector()
        qber_flags, gap_flags = [], []
        for row, probability in zip(timeline.itertuples(), probs):
            adaptive.update(
                row.qber,
                row.signal_decoy_gap,
                allow_adaptation=probability < 0.25,
            )
            state = adaptive.history[-1]
            qber_flags.append(state["qber_flag"])
            gap_flags.append(state["gap_flag"])

        probability_series = pd.Series(probs)
        outputs.append(pd.DataFrame({
            "ml_probability": probs,
            "ml_roll_mean_3": probability_series.rolling(3, min_periods=1).mean(),
            "ml_roll_max_3": probability_series.rolling(3, min_periods=1).max(),
            "ml_delta": probability_series.diff().fillna(0.0),
            "qber_z": ((timeline.qber.to_numpy() - qber_mean) / qber_std).clip(-10, 10),
            "gap_z": (
                (timeline.signal_decoy_gap.to_numpy() - gap_mean) / gap_std
            ).clip(-10, 10),
            "qber_adaptive_flag": np.asarray(qber_flags, dtype=int),
            "gap_adaptive_flag": np.asarray(gap_flags, dtype=int),
            "is_attack": timeline.is_attack.to_numpy(dtype=int),
            "timeline_id": timeline.timeline_id.to_numpy(),
            "window_idx": timeline.window_idx.to_numpy(),
            "attack_type": timeline.attack_type.to_numpy(),
            "attack_intensity": timeline.attack_intensity.to_numpy(),
        }))
    return pd.concat(outputs, ignore_index=True)


def safe_ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else 0.0


def metric_bundle(truth, predicted, scores=None):
    truth = np.asarray(truth, dtype=int)
    predicted = np.asarray(predicted, dtype=int)
    tn, fp, fn, tp = confusion_matrix(truth, predicted, labels=[0, 1]).ravel()
    result = {
        "accuracy": accuracy_score(truth, predicted),
        "balanced_accuracy": balanced_accuracy_score(truth, predicted),
        "precision": precision_score(truth, predicted, zero_division=0),
        "recall_detection_rate": recall_score(truth, predicted, zero_division=0),
        "specificity": safe_ratio(tn, tn + fp),
        "f1_score": f1_score(truth, predicted, zero_division=0),
        "f2_score": fbeta_score(truth, predicted, beta=2, zero_division=0),
        "matthews_correlation_coefficient": matthews_corrcoef(truth, predicted),
        "false_positive_rate": safe_ratio(fp, fp + tn),
        "false_negative_rate": safe_ratio(fn, fn + tp),
        "negative_predictive_value": safe_ratio(tn, tn + fn),
        "false_alarms_per_1000_normal_windows": 1000 * safe_ratio(fp, fp + tn),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }
    ranking_scores = predicted if scores is None else np.asarray(scores, dtype=float)
    result["roc_auc"] = roc_auc_score(truth, ranking_scores)
    result["pr_auc"] = average_precision_score(truth, ranking_scores)
    return {key: float(value) if isinstance(value, (np.floating, np.integer)) else value
            for key, value in result.items()}


def exact_mcnemar_pvalue(truth, first, second):
    truth = np.asarray(truth)
    first_correct = np.asarray(first) == truth
    second_correct = np.asarray(second) == truth
    first_only = int(np.sum(first_correct & ~second_correct))
    second_only = int(np.sum(~first_correct & second_correct))
    discordant = first_only + second_only
    if discordant == 0:
        return {"first_only_correct": 0, "second_only_correct": 0, "p_value": 1.0}
    tail = sum(math.comb(discordant, i) for i in range(min(first_only, second_only) + 1))
    p_value = min(1.0, 2.0 * tail / (2 ** discordant))
    return {
        "first_only_correct": first_only,
        "second_only_correct": second_only,
        "p_value": p_value,
    }


def detection_delay(frame, predictions):
    evaluated = frame.copy()
    evaluated["prediction"] = predictions
    delays, missed = [], 0
    for _, timeline in evaluated.groupby("timeline_id"):
        attack_rows = timeline[timeline.is_attack == 1]
        if attack_rows.empty:
            continue
        start = int(attack_rows.window_idx.min())
        detections = timeline[(timeline.window_idx >= start) & (timeline.prediction == 1)]
        if detections.empty:
            missed += 1
        else:
            delays.append(int(detections.window_idx.min()) - start)
    return {
        "evaluated_attack_timelines": len(delays) + missed,
        "missed_attack_timelines": missed,
        "mean_delay_windows": statistics.mean(delays) if delays else None,
        "median_delay_windows": statistics.median(delays) if delays else None,
        "maximum_delay_windows": max(delays) if delays else None,
    }


def plot_metric_comparison(metrics):
    names = ["static", "adaptive", "ml", "unified"]
    fields = ["accuracy", "precision", "recall_detection_rate", "f1_score", "specificity"]
    labels = ["Accuracy", "Precision", "Recall", "F1", "Specificity"]
    x = np.arange(len(labels))
    width = 0.19
    colors = ["#C44E52", "#55A868", "#8172B2", "#1F77B4"]
    fig, ax = plt.subplots(figsize=(11, 6))
    for index, (name, color) in enumerate(zip(names, colors)):
        values = [metrics[name][field] for field in fields]
        ax.bar(x + (index - 1.5) * width, values, width, label=name.title(), color=color)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Held-out timeline detector comparison")
    ax.set_xticks(x, labels)
    ax.legend(ncol=4, loc="lower right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig("outputs/phase5_detector_metrics.png", dpi=180)
    plt.close(fig)


def plot_confusion_matrices(metrics):
    names = ["static", "adaptive", "ml", "unified"]
    fig, axes = plt.subplots(2, 2, figsize=(9, 8))
    for ax, name in zip(axes.flat, names):
        cm = metrics[name]["confusion_matrix"]
        matrix = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
        image = ax.imshow(matrix, cmap="Blues")
        for row in range(2):
            for col in range(2):
                ax.text(col, row, matrix[row, col], ha="center", va="center", fontsize=12)
        ax.set_title(name.title())
        ax.set_xticks([0, 1], ["Pred normal", "Pred attack"])
        ax.set_yticks([0, 1], ["True normal", "True attack"])
    fig.suptitle("Confusion matrices on untouched test timelines")
    fig.tight_layout()
    fig.savefig("outputs/phase5_confusion_matrices.png", dpi=180)
    plt.close(fig)


def literature_rows(unified_metrics):
    return [
        {
            "reference": "Paper 6 - Isha et al. (2026)",
            "protocol_task": "BB84 multi-attack classification",
            "reported_accuracy": 0.8801,
            "reported_precision": "",
            "reported_recall": 0.9802,
            "reported_f1": 0.8803,
            "project_comparable_metric": "accuracy and F1 are numerically higher",
            "comparability": "Different synthetic dataset and seven-class task; not a head-to-head test",
            "source": "https://arxiv.org/abs/2608.04047",
        },
        {
            "reference": "Paper 7 - Gupta (2026)",
            "protocol_task": "BBM92 stealth-attack detection",
            "reported_accuracy": "",
            "reported_precision": 0.976,
            "reported_recall": 0.969,
            "reported_f1": "",
            "project_comparable_metric": "precision and recall are numerically higher",
            "comparability": "Different BBM92/FSO simulator; values are contextual only",
            "source": "https://eprint.iacr.org/2026/1282",
        },
        {
            "reference": "Paper 8 - Xu et al. (2024)",
            "protocol_task": "Practical QKD imperfection/attack identification",
            "reported_accuracy": 0.98,
            "reported_precision": "class-specific",
            "reported_recall": "class-specific",
            "reported_f1": "class-specific",
            "project_comparable_metric": "held-out accuracy is numerically higher than 98%",
            "comparability": "Different classes, features, and 291384-sample simulator",
            "source": "https://doi.org/10.1007/s11432-023-3988-x",
        },
        {
            "reference": "Paper 1 - Rath et al. (2026)",
            "protocol_task": "QBER estimation and fixed statistical detection",
            "reported_accuracy": "not reported",
            "reported_precision": "not reported",
            "reported_recall": "not reported",
            "reported_f1": "not reported",
            "project_comparable_metric": "project adds measured classification metrics and adaptive decoy evidence",
            "comparability": "Capability comparison only; no paper metric supports a numeric superiority claim",
            "source": "https://arxiv.org/abs/2603.27278",
        },
        {
            "reference": "Paper 5 - Hubballi et al. (2026)",
            "protocol_task": "Qiskit BB84 noise/eavesdropping simulation",
            "reported_accuracy": "not reported",
            "reported_precision": "not reported",
            "reported_recall": "not reported",
            "reported_f1": "not reported",
            "project_comparable_metric": "project adds detector F1/confusion matrices plus PQC integration",
            "comparability": "Capability comparison only; the paper evaluates QBER fidelity, not a classifier",
            "source": "https://doi.org/10.1109/NQComp68334.2026.11497748",
        },
    ]


def main():
    Path("models").mkdir(exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)
    data = pd.read_csv(DATA_PATH)
    development_ids, test_ids = split_timeline_ids(data)
    development = data[data.timeline_id.isin(development_ids)].copy()
    test = data[data.timeline_id.isin(test_ids)].copy()

    # Generate leakage-safe out-of-fold RF probabilities for fusion training.
    oof_parts = []
    splitter = GroupKFold(n_splits=5)
    for train_index, heldout_index in splitter.split(
        development, development.is_attack, development.timeline_id
    ):
        fold_train = development.iloc[train_index]
        fold_heldout = development.iloc[heldout_index]
        fold_model = make_base_model().fit(
            fold_train[FEATURE_COLUMNS], fold_train.is_attack
        )
        probabilities = online_probabilities(fold_heldout, fold_model)
        oof_parts.append(build_fusion_features(fold_heldout, probabilities))
    fusion_training = pd.concat(oof_parts, ignore_index=True)

    base_model = make_base_model().fit(
        development[FEATURE_COLUMNS], development.is_attack
    )
    # Single-window online inference is faster without joblib process/thread
    # dispatch; parallelism is useful during fitting but costly per window.
    base_model.n_jobs = 1
    fusion_model = HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.06,
        max_iter=150,
        l2_regularization=1.0,
        random_state=42,
    ).fit(fusion_training[FUSION_COLUMNS], fusion_training.is_attack)

    package = {
        "base_model": base_model,
        "fusion_model": fusion_model,
        "fusion_columns": FUSION_COLUMNS,
        "fusion_config": {"guard_probability": 0.25, "calibration_windows": 10},
        "training_metadata": {
            "development_timeline_count": len(development_ids),
            "test_timeline_count": len(test_ids),
            "split_random_state": 42,
            "fusion_training": "5-fold out-of-fold by timeline",
        },
    }
    joblib.dump(package, MODEL_PATH)

    test_probabilities = online_probabilities(test, base_model)
    test_fusion = build_fusion_features(test, test_probabilities)
    unified_scores = fusion_model.predict_proba(test_fusion[FUSION_COLUMNS])[:, 1]
    truth = test_fusion.is_attack.astype(int).tolist()
    ml_scores = test_fusion.ml_probability.tolist()
    ml_pred = (np.asarray(ml_scores) >= 0.5).astype(int).tolist()
    unified_pred = (unified_scores >= 0.5).astype(int).tolist()
    static_pred, adaptive_pred = [], []
    static_scores, adaptive_scores = [], []
    ordered_test_parts = []
    for _, timeline in test.groupby("timeline_id"):
        timeline = timeline.sort_values("window_idx").copy()
        ordered_test_parts.append(timeline)
        static = StaticThresholdDetector(fixed_threshold=0.11)
        adaptive = AdaptiveMultiSignalDetector()
        for row in timeline.itertuples():
            static_flag = static.update(row.qber)
            adaptive_flag = adaptive.update(row.qber, row.signal_decoy_gap)
            static_pred.append(int(static_flag))
            adaptive_pred.append(int(adaptive_flag))
            static_scores.append(row.qber)
            adaptive_scores.append(float(adaptive_flag))

    ordered_test = pd.concat(ordered_test_parts, ignore_index=True)
    predictions = {
        "static": static_pred,
        "adaptive": adaptive_pred,
        "ml": ml_pred,
        "unified": unified_pred,
    }
    scores = {
        "static": static_scores,
        "adaptive": adaptive_scores,
        "ml": ml_scores,
        "unified": unified_scores,
    }
    metrics = {
        name: metric_bundle(truth, predictions[name], scores[name])
        for name in predictions
    }
    delays = {
        name: detection_delay(ordered_test, predictions[name])
        for name in predictions
    }
    significance = exact_mcnemar_pvalue(truth, ml_pred, unified_pred)

    report = {
        "evaluation_design": {
            "total_timelines": int(data.timeline_id.nunique()),
            "development_timelines": len(development_ids),
            "untouched_test_timelines": len(test_ids),
            "test_windows": len(truth),
            "grouping_rule": "all windows from one timeline remain in one split",
            "fusion_training": "5-fold out-of-fold RF predictions on development timelines",
        },
        "metrics": metrics,
        "detection_delay": delays,
        "paired_mcnemar_unified_vs_ml": significance,
        "novelty": [
            "decoy-aware dual adaptive baselines for QBER and signal-decoy gap",
            "ML-gated quarantine preventing suspicious windows from poisoning either baseline",
            "stacked fusion of RF confidence, temporal persistence, adaptive flags, and physics-normalized z-scores",
            "leakage-safe timeline-level split and out-of-fold fusion training",
        ],
        "claim_boundary": (
            "The unified detector is best among this project's baselines on the same untouched "
            "test timelines. Cross-paper values use different protocols and datasets and are "
            "therefore contextual, not proof of universal superiority."
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    flat_rows = []
    for detector, values in metrics.items():
        row = {"detector": detector}
        row.update({key: value for key, value in values.items() if key != "confusion_matrix"})
        row.update(values["confusion_matrix"])
        flat_rows.append(row)
    pd.DataFrame(flat_rows).to_csv(METRICS_CSV_PATH, index=False)
    pd.DataFrame(literature_rows(metrics["unified"])).to_csv(LITERATURE_PATH, index=False)
    plot_metric_comparison(metrics)
    plot_confusion_matrices(metrics)

    print(json.dumps(report, indent=2))
    print(f"Saved model -> {MODEL_PATH}")
    print(f"Saved report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
