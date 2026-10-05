"""
generate_dataset.py
--------------------
Runs many BB84 + decoy-state simulations across a range of:
    - natural noise levels
    - attack types (none, intercept_resend, pns)
    - attack intensities (for stealthy partial attacks)

...and saves the results as a labeled CSV dataset in data/bb84_dataset.csv.

This dataset is the direct input for Phase 2 (ML-based adaptive
detection): each row is one "session" with QBER, decoy-signal detection
gap, and a ground-truth label (is_attack: 0 or 1) that the ML model
will later learn to predict WITHOUT being told the attack type directly.

Run:
    python generate_dataset.py
"""

import csv
import random
import numpy as np

from bb84.protocol import run_bb84
from bb84.eavesdropper import Eavesdropper
from bb84.decoy import DecoyStateSource, signal_decoy_gap

OUTPUT_PATH = "data/bb84_dataset.csv"

N_PHOTONS = 2000
N_DECOY_PULSES = 2000
SESSIONS_PER_CONFIG = 40  # repeats per configuration, for statistical variety

NOISE_LEVELS = [0.01, 0.02, 0.03, 0.05, 0.08]  # natural channel noise range

SCENARIOS = [
    # (attack_type, intensity, label)
    ("none", 0.0, 0),
    ("intercept_resend", 1.0, 1),   # full intercept-resend (easy to catch)
    ("intercept_resend", 0.5, 1),   # medium/stealthy
    ("intercept_resend", 0.2, 1),   # very stealthy (low intensity)
    ("pns", 1.0, 1),                # PNS attack (QBER stays low, decoy gap rises)
]


def generate():
    rows = []
    decoy_source = DecoyStateSource()

    for noise_level in NOISE_LEVELS:
        for attack_type, intensity, label in SCENARIOS:
            for session in range(SESSIONS_PER_CONFIG):
                eve = Eavesdropper(attack_type=attack_type, intensity=intensity)

                # Run BB84 signal-channel simulation
                result = run_bb84(
                    n_photons=N_PHOTONS,
                    noise_level=noise_level,
                    eavesdropper=eve,
                )

                # Run decoy-state pulse simulation (PNS shows up here)
                pns_flag = (attack_type == "pns")
                pulses = decoy_source.simulate_pulses(
                    n_pulses=N_DECOY_PULSES, pns_attack=pns_flag
                )
                gap = signal_decoy_gap(pulses)

                rows.append({
                    "noise_level": noise_level,
                    "attack_type": attack_type,
                    "attack_intensity": intensity,
                    "n_photons": result.n_photons,
                    "sifted_length": result.sifted_length,
                    "qber": round(result.qber, 5),
                    "final_key_length": result.final_key_length,
                    "signal_decoy_gap": round(gap, 5),
                    "is_attack": label,
                })

    # Shuffle rows so the dataset isn't grouped by scenario (more realistic
    # for later train/test splitting in Phase 2)
    random.shuffle(rows)

    fieldnames = list(rows[0].keys())
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} sessions -> {OUTPUT_PATH}")

    # Quick sanity-check summary
    qbers_normal = [r["qber"] for r in rows if r["is_attack"] == 0]
    qbers_attack = [r["qber"] for r in rows if r["is_attack"] == 1]
    print(f"Avg QBER (no attack):  {np.mean(qbers_normal):.4f}")
    print(f"Avg QBER (attack):     {np.mean(qbers_attack):.4f}")

    gaps_normal = [r["signal_decoy_gap"] for r in rows if r["is_attack"] == 0]
    gaps_attack = [r["signal_decoy_gap"] for r in rows if r["is_attack"] == 1]
    print(f"Avg signal-decoy gap (no attack): {np.mean(gaps_normal):.4f}")
    print(f"Avg signal-decoy gap (attack):    {np.mean(gaps_attack):.4f}")


if __name__ == "__main__":
    generate()
