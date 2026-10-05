"""
visualize.py
------------
Generates simple plots from the dataset created by generate_dataset.py,
so you can visually confirm the simulator behaves as expected before
moving to Phase 2 (ML detection).

Produces:
    outputs/qber_by_scenario.png       - QBER distribution per attack type
    outputs/signal_decoy_gap.png       - decoy-gap distribution per attack type

Run (after generate_dataset.py):
    python visualize.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import os

DATA_PATH = "data/bb84_dataset.csv"
OUT_DIR = "outputs"


def main():
    if not os.path.exists(DATA_PATH):
        print(f"Dataset not found at {DATA_PATH}. Run generate_dataset.py first.")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_csv(DATA_PATH)

    # --- Plot 1: QBER by attack_type ---
    fig, ax = plt.subplots(figsize=(8, 5))
    df.boxplot(column="qber", by="attack_type", ax=ax)
    ax.set_title("QBER distribution by attack type")
    ax.set_xlabel("Attack type")
    ax.set_ylabel("QBER")
    plt.suptitle("")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "qber_by_scenario.png"))
    print(f"Saved {OUT_DIR}/qber_by_scenario.png")

    # --- Plot 2: signal-decoy gap by attack_type ---
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    df.boxplot(column="signal_decoy_gap", by="attack_type", ax=ax2)
    ax2.set_title("Signal-Decoy detection gap by attack type")
    ax2.set_xlabel("Attack type")
    ax2.set_ylabel("|signal_rate - decoy_rate|")
    plt.suptitle("")
    fig2.tight_layout()
    fig2.savefig(os.path.join(OUT_DIR, "signal_decoy_gap.png"))
    print(f"Saved {OUT_DIR}/signal_decoy_gap.png")

    print("\nSummary stats:")
    print(df.groupby("attack_type")[["qber", "signal_decoy_gap"]].mean())


if __name__ == "__main__":
    main()
