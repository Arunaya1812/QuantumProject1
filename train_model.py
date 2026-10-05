"""
train_model.py
----------------
Trains a lightweight ML classifier (Random Forest) to distinguish
attack windows from normal windows, using the temporal features built
by feature_engineering.py.

Why Random Forest and not deep learning:
Recent QKD-security research shows that once you engineer good temporal
features (rolling mean/std, slope, burst counts), simple classifiers
perform close to state-of-the-art -- the novelty is in the FEATURES,
not a heavier model. Random Forest is also easy to explain to a guide
("it's basically many small decision rules combined"), fast to train,
and gives feature importances for free, which strengthens the report.

IMPORTANT: we split TRAIN/TEST by timeline_id, not by row. If we split
by row, windows from the same timeline would leak into both train and
test (they're highly correlated), giving misleadingly perfect accuracy.
Splitting by timeline is the honest way to evaluate this.

Run (after feature_engineering.py):
    python train_model.py
"""

import pandas as pd
import numpy as np
import joblib
import os

from bb84.features import FEATURE_COLUMNS

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score,
    precision_score, recall_score, f1_score
)

FEATURES_PATH = "data/bb84_features_dataset.csv"
MODEL_PATH = "models/rf_detector.joblib"
REPORT_PATH = "outputs/phase2_classification_report.txt"

LABEL_COLUMN = "is_attack"


def main():
    df = pd.read_csv(FEATURES_PATH)

    # --- split by timeline_id to avoid data leakage ---
    timeline_ids = df["timeline_id"].unique()
    train_ids, test_ids = train_test_split(timeline_ids, test_size=0.25, random_state=42)

    train_df = df[df["timeline_id"].isin(train_ids)]
    test_df = df[df["timeline_id"].isin(test_ids)]

    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[LABEL_COLUMN]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[LABEL_COLUMN]

    print(f"Train windows: {len(X_train)} (from {len(train_ids)} timelines)")
    print(f"Test windows:  {len(X_test)} (from {len(test_ids)} timelines)")

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        random_state=42,
        class_weight="balanced",  # dataset has more normal windows than attack windows
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    rec = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)
    report = classification_report(y_test, y_pred, target_names=["normal", "attack"])

    print("\n=== Overall performance (held-out timelines) ===")
    print(f"Accuracy:  {acc:.4f}")
    print(f"Precision: {prec:.4f}")
    print(f"Recall:    {rec:.4f}")
    print(f"F1 score:  {f1:.4f}")
    print("\nConfusion matrix:")
    print("            pred_normal  pred_attack")
    print(f"true_normal   {cm[0][0]:8d}     {cm[0][1]:8d}")
    print(f"true_attack   {cm[1][0]:8d}     {cm[1][1]:8d}")
    print("\n" + report)

    # --- Recall breakdown by attack type -- this shows whether stealthy
    #     attacks (the hard case) are actually being caught, not just
    #     the easy full-intensity ones. ---
    print("=== Recall by attack scenario (the important comparison) ===")
    test_df = test_df.copy()
    test_df["pred"] = y_pred
    for attack_type in test_df["attack_type"].unique():
        subset = test_df[(test_df["attack_type"] == attack_type) & (test_df["is_attack"] == 1)]
        if len(subset) == 0:
            continue
        if attack_type == "intercept_resend":
            for intensity in sorted(subset["attack_intensity"].unique()):
                sub2 = subset[subset["attack_intensity"] == intensity]
                caught = (sub2["pred"] == 1).mean()
                print(f"  intercept_resend (intensity={intensity}): recall = {caught:.3f} "
                      f"({len(sub2)} attack windows)")
        else:
            caught = (subset["pred"] == 1).mean()
            print(f"  {attack_type}: recall = {caught:.3f} ({len(subset)} attack windows)")

    # --- Feature importances ---
    importances = pd.Series(clf.feature_importances_, index=FEATURE_COLUMNS)
    importances = importances.sort_values(ascending=False)
    print("\n=== Feature importances ===")
    print(importances.to_string())

    # --- Save model and report ---
    os.makedirs("models", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    print(f"\nSaved trained model -> {MODEL_PATH}")

    with open(REPORT_PATH, "w") as f:
        f.write("Phase 2 - Random Forest Attack Detector - Evaluation Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Accuracy:  {acc:.4f}\n")
        f.write(f"Precision: {prec:.4f}\n")
        f.write(f"Recall:    {rec:.4f}\n")
        f.write(f"F1 score:  {f1:.4f}\n\n")
        f.write("Confusion matrix:\n")
        f.write("            pred_normal  pred_attack\n")
        f.write(f"true_normal   {cm[0][0]:8d}     {cm[0][1]:8d}\n")
        f.write(f"true_attack   {cm[1][0]:8d}     {cm[1][1]:8d}\n\n")
        f.write(report + "\n\n")
        f.write("Feature importances:\n")
        f.write(importances.to_string() + "\n")
    print(f"Saved full report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
