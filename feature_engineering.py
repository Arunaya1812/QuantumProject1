"""
feature_engineering.py
------------------------
Turns the raw per-window measurements (data/bb84_windows_raw.csv) into
the TEMPORAL features the ML detector actually trains on.

Why this matters (this is the "novelty" part of the project):
A single QBER snapshot cannot reliably tell noise apart from a stealthy
attack -- a slightly elevated QBER could be either. But the PATTERN
over time usually can:
    - Natural noise fluctuates randomly around a stable baseline.
    - A real attack usually causes a sustained shift (the mean moves
      and stays moved) or a burst of consecutive high-error windows.

For each window, we compute features using only PAST and CURRENT data
in a rolling window (never future data -- this must stay realistic,
since a real detector can't see the future):

    qber_roll_mean     - rolling mean of QBER (recent baseline level)
    qber_roll_std       - rolling std of QBER (recent volatility)
    qber_slope           - short-term rate of change of QBER
    gap_roll_mean        - rolling mean of signal-decoy gap
    gap_roll_std          - rolling std of signal-decoy gap
    error_burst_count   - how many of the last N windows had QBER
                          noticeably above the timeline's OWN early
                          calibration baseline (adaptive per timeline,
                          not a single global number)

Run (after generate_timeline_dataset.py):
    python feature_engineering.py
"""

import pandas as pd
import numpy as np

RAW_PATH = "data/bb84_windows_raw.csv"
OUTPUT_PATH = "data/bb84_features_dataset.csv"

ROLL_WINDOW = 5          # rolling window size (in # of windows)
CALIBRATION_WINDOWS = 10  # how many early windows define "normal" per timeline


def engineer_features_for_timeline(df_tl: pd.DataFrame) -> pd.DataFrame:
    df_tl = df_tl.sort_values("window_idx").reset_index(drop=True)

    # Rolling statistics (min_periods=1 so early rows still get a value)
    df_tl["qber_roll_mean"] = df_tl["qber"].rolling(ROLL_WINDOW, min_periods=1).mean()
    df_tl["qber_roll_std"] = df_tl["qber"].rolling(ROLL_WINDOW, min_periods=1).std().fillna(0.0)
    df_tl["gap_roll_mean"] = df_tl["signal_decoy_gap"].rolling(ROLL_WINDOW, min_periods=1).mean()
    df_tl["gap_roll_std"] = df_tl["signal_decoy_gap"].rolling(ROLL_WINDOW, min_periods=1).std().fillna(0.0)

    # Short-term slope: current rolling mean vs rolling mean a few steps back
    df_tl["qber_slope"] = df_tl["qber_roll_mean"].diff(ROLL_WINDOW).fillna(0.0)

    # Per-timeline calibration baseline, built ONLY from the first
    # CALIBRATION_WINDOWS windows (assumed attack-free, like a warm-up
    # period when the channel is first established).
    calib = df_tl.iloc[:CALIBRATION_WINDOWS]
    baseline_mean = calib["qber"].mean()
    baseline_std = calib["qber"].std()
    if pd.isna(baseline_std) or baseline_std == 0:
        baseline_std = 1e-4  # avoid divide-by-zero for ultra-clean calib windows

    flag_threshold = baseline_mean + 3 * baseline_std
    df_tl["exceeds_calib_baseline"] = (df_tl["qber"] > flag_threshold).astype(int)
    df_tl["error_burst_count"] = (
        df_tl["exceeds_calib_baseline"].rolling(ROLL_WINDOW, min_periods=1).sum()
    )

    df_tl["calib_baseline_mean"] = baseline_mean
    df_tl["calib_baseline_std"] = baseline_std

    return df_tl


def main():
    df = pd.read_csv(RAW_PATH)

    featured = []
    for tl_id, group in df.groupby("timeline_id"):
        featured.append(engineer_features_for_timeline(group))

    result = pd.concat(featured, ignore_index=True)
    result.to_csv(OUTPUT_PATH, index=False)

    print(f"Engineered features for {result['timeline_id'].nunique()} timelines "
          f"({len(result)} windows) -> {OUTPUT_PATH}")
    print("\nFeature columns added:")
    for c in ["qber_roll_mean", "qber_roll_std", "qber_slope",
              "gap_roll_mean", "gap_roll_std", "error_burst_count"]:
        print(f"  - {c}")


if __name__ == "__main__":
    main()
