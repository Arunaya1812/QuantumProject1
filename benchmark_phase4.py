"""Phase 4 detector, stress, PQC latency, and Qiskit comparison benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import time

import joblib
import pandas as pd

from bb84.adaptive_threshold import AdaptiveThresholdDetector, StaticThresholdDetector
from bb84.eavesdropper import Eavesdropper
from bb84.pqc import AuthenticatedClassicalChannel, PQCAuthenticator, PQCKeyExchange
from bb84.protocol import run_bb84
from bb84.qiskit_protocol import run_bb84_qiskit
from bb84.timeline import simulate_timeline
from bb84.unified_detector import UnifiedAdaptiveMLDetector
from feature_engineering import engineer_features_for_timeline
from train_model import FEATURE_COLUMNS, MODEL_PATH

OUT_DIR = Path("outputs")


def classification_metrics(truth, predicted):
    pairs = [(int(t), int(p)) for t, p in zip(truth, predicted)]
    tp = sum(t == 1 and p == 1 for t, p in pairs)
    tn = sum(t == 0 and p == 0 for t, p in pairs)
    fp = sum(t == 0 and p == 1 for t, p in pairs)
    fn = sum(t == 1 and p == 0 for t, p in pairs)
    total = len(pairs) or 1
    return {
        "accuracy": (tp + tn) / total,
        "detection_rate": tp / (tp + fn) if tp + fn else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def benchmark_detectors(dataset_path="data/bb84_features_dataset.csv"):
    df = pd.read_csv(dataset_path)
    model = joblib.load(MODEL_PATH)
    all_outputs = {name: [] for name in ("static", "adaptive", "ml", "unified")}
    truth = []
    latency_ns = {name: [] for name in all_outputs}

    for _, timeline in df.groupby("timeline_id"):
        timeline = timeline.sort_values("window_idx")
        static = StaticThresholdDetector()
        adaptive = AdaptiveThresholdDetector()
        unified = UnifiedAdaptiveMLDetector(model)
        featured = engineer_features_for_timeline(timeline.copy())
        ml_predictions = model.predict(featured[FEATURE_COLUMNS])
        # Measure actual one-window inference rather than timing access to a
        # prediction that was already computed in a batch.
        for position in range(min(2, len(featured))):
            single = featured.iloc[[position]][FEATURE_COLUMNS]
            start = time.perf_counter_ns()
            model.predict(single)
            latency_ns["ml"].append(time.perf_counter_ns() - start)

        for row, ml_prediction in zip(timeline.to_dict("records"), ml_predictions):
            truth.append(row["is_attack"])
            start = time.perf_counter_ns()
            all_outputs["static"].append(static.update(row["qber"]))
            latency_ns["static"].append(time.perf_counter_ns() - start)
            start = time.perf_counter_ns()
            all_outputs["adaptive"].append(adaptive.update(row["qber"]))
            latency_ns["adaptive"].append(time.perf_counter_ns() - start)
            all_outputs["ml"].append(int(ml_prediction))
            start = time.perf_counter_ns()
            decision = unified.update(row["qber"], row["signal_decoy_gap"])
            all_outputs["unified"].append(decision.attack_detected)
            latency_ns["unified"].append(time.perf_counter_ns() - start)

    report = {}
    for name, output in all_outputs.items():
        report[name] = classification_metrics(truth, output)
        report[name]["median_latency_ms"] = statistics.median(latency_ns[name]) / 1e6
    return report


def stress_test(model, quick=False):
    rows_out = []
    noise_levels = [0.01, 0.03] if quick else [0.01, 0.02, 0.04, 0.06]
    scenarios = [("none", 0.0), ("pns", 1.0)]
    scenarios += [("intercept_resend", x) for x in ([0.1, 0.2, 0.5] if quick else [0.1, 0.2, 0.4, 0.7, 1.0])]
    seeds = range(2 if quick else 4)
    for noise in noise_levels:
        for attack_type, intensity in scenarios:
            truth, predicted, raw_bits = [], [], []
            for seed in seeds:
                rows = simulate_timeline(
                    timeline_id=seed,
                    n_windows=40 if quick else 80,
                    photons_per_window=160 if quick else 250,
                    decoy_pulses_per_window=160 if quick else 250,
                    noise_level=noise,
                    attack_type=attack_type,
                    attack_intensity=intensity,
                    attack_start_frac=0.5,
                    seed=10_000 + seed,
                )
                detector = UnifiedAdaptiveMLDetector(model)
                for row in rows:
                    decision = detector.update(row["qber"], row["signal_decoy_gap"])
                    truth.append(row["is_attack"])
                    predicted.append(decision.attack_detected)
                    if not decision.attack_detected:
                        raw_bits.append(row["sifted_length"] * 0.5)
            metrics = classification_metrics(truth, predicted)
            sent_photons = len(list(seeds)) * (40 if quick else 80) * (160 if quick else 250)
            rows_out.append({
                "noise_level": noise,
                "attack_type": attack_type,
                "attack_intensity": intensity,
                **metrics,
                "estimated_secure_key_bits": int(sum(raw_bits)),
                "estimated_secure_key_rate": sum(raw_bits) / sent_photons,
            })
    return rows_out


def benchmark_pqc(rounds=10):
    alice = PQCAuthenticator.generate()
    bob = PQCAuthenticator.generate()
    channel = AuthenticatedClassicalChannel("benchmark")
    channel.register("alice", alice)
    channel.register("bob", bob)
    auth_times = []
    unauthenticated_times = []
    for i in range(rounds):
        start = time.perf_counter_ns()
        json.dumps({"message_type": "benchmark", "payload": {"round": i}}, sort_keys=True)
        unauthenticated_times.append(time.perf_counter_ns() - start)
        start = time.perf_counter_ns()
        message = channel.send("alice", "benchmark", {"round": i})
        assert channel.receive(message)
        auth_times.append(time.perf_counter_ns() - start)

    kem_times = []
    for _ in range(rounds):
        start = time.perf_counter_ns()
        keypair = PQCKeyExchange.generate_keypair()
        ciphertext, shared_a = PQCKeyExchange.encapsulate(keypair.public_key)
        shared_b = PQCKeyExchange.decapsulate(keypair.secret_key, ciphertext)
        assert shared_a == shared_b
        kem_times.append(time.perf_counter_ns() - start)
    auth_ms = statistics.median(auth_times) / 1e6
    no_auth_ms = statistics.median(unauthenticated_times) / 1e6
    return {
        "without_pqc_median_ms": no_auth_ms,
        "ml_dsa_sign_verify_median_ms": statistics.median(auth_times) / 1e6,
        "pqc_authentication_overhead_ms": auth_ms - no_auth_ms,
        "ml_kem_roundtrip_median_ms": statistics.median(kem_times) / 1e6,
        "rounds": rounds,
    }


def compare_qiskit(photons=512):
    output = []
    for attack, intensity in [("none", 0.0), ("intercept_resend", 1.0)]:
        classical = run_bb84(
            photons, 0.02, Eavesdropper(attack, intensity), seed=77
        )
        quantum = run_bb84_qiskit(
            photons, 0.02, Eavesdropper(attack, intensity), seed=77
        )
        output.append({
            "attack_type": attack,
            "probabilistic_qber": classical.qber,
            "qiskit_qber": quantum.qber,
            "absolute_qber_difference": abs(classical.qber - quantum.qber),
            "qiskit_circuits": quantum.circuit_count,
        })
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--skip-qiskit", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(exist_ok=True)
    model = joblib.load(MODEL_PATH)
    report = {
        "benchmark_mode": "quick" if args.quick else "full",
        "detectors": benchmark_detectors(),
        "pqc_latency": benchmark_pqc(3 if args.quick else 10),
        "qiskit_comparison": [] if args.skip_qiskit else compare_qiskit(128 if args.quick else 512),
    }
    stress = stress_test(model, args.quick)
    with (OUT_DIR / "phase4_stress_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=stress[0].keys())
        writer.writeheader()
        writer.writerows(stress)
    report["stress_test_rows"] = len(stress)
    with (OUT_DIR / "phase4_benchmark_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
