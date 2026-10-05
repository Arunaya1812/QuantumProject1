"""
generate_timeline_dataset.py
-----------------------------
Runs many simulated timelines (continuous streams of BB84 windows)
across a mix of:
    - natural noise levels
    - attack types: none, intercept-resend (full + stealthy), PNS
    - random attack start points

Saves the raw per-window measurements to data/bb84_windows_raw.csv.
This is the RAW data -- feature_engineering.py turns it into the
rolling/temporal features used for ML training.

Run:
    python generate_timeline_dataset.py
"""

import csv
import random

from bb84.timeline import simulate_timeline

OUTPUT_PATH = "data/bb84_windows_raw.csv"

N_WINDOWS = 120
PHOTONS_PER_WINDOW = 250

NOISE_LEVELS = [0.01, 0.02, 0.03, 0.05]

# (attack_type, intensity, repeats_per_noise_level)
SCENARIOS = [
    ("none", 0.0, 6),                     # no-attack baseline timelines
    ("intercept_resend", 1.0, 4),         # full, easy-to-catch attack
    ("intercept_resend", 0.5, 4),         # medium stealth
    ("intercept_resend", 0.2, 4),         # very stealthy, low intensity
    ("pns", 1.0, 4),                      # PNS attack (QBER barely moves)
]


def generate():
    all_rows = []
    timeline_id = 0

    for noise_level in NOISE_LEVELS:
        for attack_type, intensity, repeats in SCENARIOS:
            for _ in range(repeats):
                rows = simulate_timeline(
                    timeline_id=timeline_id,
                    n_windows=N_WINDOWS,
                    photons_per_window=PHOTONS_PER_WINDOW,
                    decoy_pulses_per_window=PHOTONS_PER_WINDOW,
                    noise_level=noise_level,
                    attack_type=attack_type,
                    attack_intensity=intensity,
                    attack_start_frac=None if attack_type != "none" else None,
                )
                all_rows.extend(rows)
                timeline_id += 1

    fieldnames = list(all_rows[0].keys())
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    n_timelines = timeline_id
    n_attack_windows = sum(r["is_attack"] for r in all_rows)
    print(f"Generated {n_timelines} timelines, {len(all_rows)} total windows -> {OUTPUT_PATH}")
    print(f"Attack windows: {n_attack_windows} ({100*n_attack_windows/len(all_rows):.1f}%)")


if __name__ == "__main__":
    generate()
