# Phase 1 — BB84 + Decoy-State Simulation

This is Phase 1 of the project:
**"Adaptive ML-Based Eavesdropper Detection in Decoy-State BB84 QKD with Post-Quantum Key Authentication"**

Phase 1 covers:
- A working BB84 protocol simulator (bit/basis generation, transmission, sifting, QBER estimation)
- A natural channel noise model
- An eavesdropper module with two attacks: intercept-resend (full + stealthy/partial) and PNS (photon-number-splitting)
- A decoy-state module that reproduces the signal-vs-decoy detection-rate gap used to catch PNS attacks
- A dataset generator that produces a labeled CSV (`data/bb84_dataset.csv`) across many noise levels and attack scenarios — this becomes the direct input for Phase 2's ML detector
- A visualization script to sanity-check the simulator's behavior

## Project Structure
```
bb84_phase1/
├── bb84/
│   ├── __init__.py
│   ├── photon.py        # photon/qubit encoding + measurement model
│   ├── channel.py        # natural channel noise
│   ├── eavesdropper.py   # intercept-resend + PNS attack models
│   ├── decoy.py           # decoy-state pulses + detection-rate statistics
│   └── protocol.py       # full BB84 run: transmit -> sift -> estimate QBER
├── main.py                # demo script (run this first)
├── generate_dataset.py    # generates data/bb84_dataset.csv
├── visualize.py           # generates plots in outputs/
├── requirements.txt
├── data/                  # dataset CSV goes here
└── outputs/               # plots go here
```

## How to Run in VS Code

### 1. Unzip and open the folder
- Unzip `bb84_phase1.zip` anywhere on your computer.
- Open VS Code → File → Open Folder... → select the unzipped `bb84_phase1` folder.

### 2. Install Python (if not already installed)
- Make sure Python 3.9+ is installed. Check in VS Code's terminal:
  ```
  python --version
  ```
  (On some systems it may be `python3 --version`.)

### 3. Install the Python extension
- In VS Code, go to Extensions (left sidebar, or Ctrl+Shift+X / Cmd+Shift+X)
- Search for "Python" (by Microsoft) and install it if not already installed.

### 4. Create a virtual environment (recommended)
Open a terminal inside VS Code (Terminal → New Terminal) and run:
```
python -m venv venv
```
Activate it:
- **Windows:** `venv\Scripts\activate`
- **Mac/Linux:** `source venv/bin/activate`

You should see `(venv)` appear at the start of your terminal prompt.

### 5. Install dependencies
```
pip install -r requirements.txt
```

### 6. Run the demo
```
python main.py
```
This runs 4 quick demonstrations and prints results directly in the terminal:
1. Normal BB84 (no attack) — QBER should be close to the noise level
2. Full intercept-resend attack — QBER jumps up noticeably
3. Stealthy partial intercept-resend — smaller QBER bump (motivates Phase 2's adaptive detection)
4. Decoy-state statistics — shows the signal-vs-decoy detection gap under a PNS attack

### 7. Generate the full labeled dataset
```
python generate_dataset.py
```
This creates `data/bb84_dataset.csv` — hundreds of simulated sessions across different noise levels and attack types, each labeled `is_attack: 0` or `1`. This is what you'll feed into the ML model in Phase 2.

### 8. Visualize the results
```
python visualize.py
```
This creates two plots in the `outputs/` folder:
- `qber_by_scenario.png` — shows QBER is higher under attack conditions
- `signal_decoy_gap.png` — shows the decoy-signal gap spikes specifically under PNS attacks

Open these PNG files directly in VS Code (click on them in the file explorer) to view them.

## What to Check/Understand for Your Report
- Run `main.py` and note down the QBER values printed for each scenario — this is your baseline evidence that natural noise, intercept-resend, and stealthy attacks behave as expected.
- Open `data/bb84_dataset.csv` in VS Code (or Excel) and confirm you can see rows with different noise levels, attack types, and QBER/gap values.
- Look at the two plots — they visually prove why a single fixed QBER threshold would struggle: stealthy attacks and PNS attacks don't always push QBER up cleanly, which is your justification for Phase 2 (adaptive ML detection using QBER + decoy-gap + more features together).

---

# Phase 2 — Adaptive Threshold + ML-Based Attack Detection

Phase 2 builds directly on Phase 1's simulator and adds:
- A **windowed timeline simulator** (`bb84/timeline.py`) — instead of one QBER number per session, this produces a continuous stream of QBER/decoy-gap measurements over time, with an attack that switches on partway through (realistic: Eve doesn't announce herself at t=0).
- **Temporal feature engineering** (`feature_engineering.py`) — rolling mean/std, rate-of-change, and error-burst-count features computed per timeline, using only past+current data (never future data, to stay realistic).
- An **Adaptive Threshold Detector** (`bb84/adaptive_threshold.py`) — a self-updating statistical threshold (calibrates from early data, then tracks drift via EMA), compared against a naive fixed **Static Threshold Detector**.
- A **Random Forest classifier** (`train_model.py`) trained on the temporal features to flag attack windows.
- A **side-by-side comparison script** (`compare_detectors.py`) that plots Static vs Adaptive vs ML detection on three key scenarios and produces the core evidence for your report.

## New Files (Phase 2)
```
bb84_project/
├── bb84/
│   ├── timeline.py             # windowed continuous-time BB84 simulator
│   └── adaptive_threshold.py   # AdaptiveThresholdDetector + StaticThresholdDetector
├── generate_timeline_dataset.py  # generates data/bb84_windows_raw.csv
├── feature_engineering.py        # generates data/bb84_features_dataset.csv
├── train_model.py                # trains models/rf_detector.joblib
├── compare_detectors.py          # generates outputs/comparison_*.png
├── models/                       # trained model saved here
```

## How to Run Phase 2 (in order)

Make sure you've already run `pip install -r requirements.txt` (it now includes `scikit-learn` and `joblib` — reinstall if you set up your venv before Phase 2).

### 1. Generate the raw timeline dataset
```
python generate_timeline_dataset.py
```
Simulates ~88 timelines (120 windows each) across different noise levels and attack types (none, intercept-resend at full/medium/stealthy intensity, PNS), saving raw per-window data to `data/bb84_windows_raw.csv`.

### 2. Engineer temporal features
```
python feature_engineering.py
```
Computes rolling-window features (mean, std, slope, error-burst-count) per timeline, saving to `data/bb84_features_dataset.csv`. This is what makes the detector "temporal" rather than single-snapshot.

### 3. Train the ML model
```
python train_model.py
```
Trains a Random Forest classifier (train/test split done **by timeline**, not by row, to avoid data leakage). Prints accuracy/precision/recall/F1, a confusion matrix, **recall broken down by attack intensity** (the important number — shows whether stealthy attacks are actually caught), and feature importances. Saves the model to `models/rf_detector.joblib` and a text report to `outputs/phase2_classification_report.txt`.

Expect roughly: ~98% overall accuracy, ~100% recall on full-intensity and PNS attacks, but noticeably lower recall (~60%) on the most stealthy (intensity 0.2) intercept-resend attacks — this is an honest, realistic result and a good discussion point (the hardest attacks are still hard; that's expected and worth explaining to your guide rather than hiding).

### 4. Run the Static vs Adaptive vs ML comparison
```
python compare_detectors.py
```
Generates three plots in `outputs/`:
- `comparison_no_attack_drift.png` — pure noise, no attack: check both threshold detectors stay quiet
- `comparison_stealthy_intercept.png` — **the key result**: shows the adaptive threshold slowly getting dragged upward by the sustained attack itself (a real, known weakness of naive adaptive thresholds — it's not a bug, it's the actual justification for combining adaptive thresholding with ML), while the ML model locks on immediately and stays locked
- `comparison_pns_attack.png` — **the cleanest exhibit**: QBER barely moves, so both QBER-only detectors (static and adaptive) never fire, but the ML model catches it instantly because it also uses the signal-decoy detection gap as a feature

## The Narrative For Your Report/Defense
1. A single fixed QBER threshold misses stealthy attacks and is blind to PNS attacks entirely (QBER doesn't rise).
2. A naive adaptive threshold fixes some of this (tracks environmental drift, fewer false alarms) but has its own real weakness: a slow, sustained attack can drag the baseline itself upward over time, gradually desensitizing the detector — this was actually observed empirically in our simulation, not just a theoretical concern.
3. Combining rolling temporal features (mean, std, slope, burst-count) **and** decoy-state statistics into a single ML classifier avoids both weaknesses — it doesn't rely on one number's absolute level, and it isn't fooled by attacks that specifically avoid disturbing QBER.

## Next Steps (Phase 3 preview)
Phase 3 adds Post-Quantum Cryptography (PQC) key authentication (e.g. Kyber/Dilithium) for the classical channel, and combines the QKD-derived key with a PQC-derived key for defense-in-depth.

---

# Phase 3 - Unified Detection and Post-Quantum Authentication

Phase 3 is implemented in the following modules:

- `bb84/features.py` computes the Phase 2 temporal feature schema online, one window at a time.
- `bb84/unified_detector.py` fuses the adaptive QBER rule with the Random Forest probability. An ML-suspicious window is not allowed to update the adaptive baseline, limiting baseline-poisoning attacks.
- `bb84/pqc.py` authenticates canonical classical-channel messages with standardized ML-DSA-65, adds session/sequence replay protection, establishes an independent secret with ML-KEM-768, and combines it with QKD bits using HKDF-SHA-256.
- `bb84/secure_session.py` joins detection, authenticated basis reconciliation, authenticated error-correction metadata, privacy amplification metadata, and hybrid final-key derivation.
- `run_phase3_demo.py` is the command-line end-to-end demonstration.

Install all dependencies in an activated Python 3.9+ environment:

```text
pip install -r requirements.txt
```

Run a clean session:

```text
python run_phase3_demo.py --attack none
```

Verify attack rejection:

```text
python run_phase3_demo.py --attack pns
python run_phase3_demo.py --attack intercept_resend --intensity 0.2
```

The command prints only a final-key fingerprint, never the key itself. Classical-message signatures use ML-DSA-65 (FIPS 204), while hybrid key establishment uses ML-KEM-768. These library-backed primitives are appropriate for a research prototype; this project is not a production cryptographic implementation or a formal security proof.

# Phase 4 - Qiskit Refinement and Benchmarking

`bb84/qiskit_protocol.py` prepares and measures actual one-qubit BB84 circuits with Qiskit Aer. A full intercept-resend attack is represented by Eve's measurement circuit followed by a separate state-preparation circuit sent to Bob. The statistical decoy-state model remains in `bb84/decoy.py`, because a gate-level one-qubit simulator does not model weak coherent optical pulse photon counts.

Run the end-to-end pipeline with the Qiskit backend:

```text
python run_phase3_demo.py --backend qiskit --attack none
```

Run Phase 4 benchmarking:

```text
python benchmark_phase4.py
```

For a shorter development run:

```text
python benchmark_phase4.py --quick
```

The benchmark writes:

- `outputs/phase4_benchmark_report.json`: static, adaptive, ML, and unified detector accuracy, detection rate, false-positive rate, precision, latency, PQC overhead, and Qiskit comparison.
- `outputs/phase4_stress_results.csv`: noise/attack-intensity stress results with estimated secure key bits and secure key rate.

Run the automated tests with:

```text
python -m unittest discover -s tests -v
```

## Simulation boundaries

- The current error-correction stage is a clearly labeled simulated reconciliation step. Replace it with Cascade or an LDPC implementation before treating key-rate figures as protocol-grade results.
- Decoy-state behavior is modeled statistically and is not an optical multi-photon Qiskit simulation.
- The benchmark measures a software simulator on the local machine; it does not claim hardware QKD throughput.
