# Basis console

A web dashboard for the project: watch a BB84 link live, inject Eve, run full
secure sessions, step through the protocol photon by photon, read the evaluation
results and try the post-quantum signatures.

The console only **calls** the existing `bb84/` package and scripts. Nothing in
`bb84/` is modified.

## Run it

From the project root, with the project venv active:

```text
pip install -r requirements.txt
pip install -r ui/requirements.txt
python -m ui
```

The browser opens at http://127.0.0.1:8000. Use `python -m ui --port 8080` for a
different port, or `--no-browser` to skip opening a tab.

`models/phase5_unified.joblib` must exist (it is committed). The evaluation
pages read `outputs/`; if that folder is empty, open **Detector evaluation →
Run evaluations** to generate results from the UI.

## Pages

| Page | What it shows | Backed by |
|---|---|---|
| Link monitor | Live stream of detector windows over a WebSocket. Inject intercept-resend or PNS, change noise, switch on fibre drift, and watch QBER, decoy gap, adaptive thresholds and fusion probability. | `run_bb84`, `DecoyStateSource`, `UnifiedAdaptiveMLDetector` |
| Key sessions | One full session: screening, ML-DSA-65 signed transcript, ML-KEM-768 exchange, hybrid key fingerprint. Probabilistic or Qiskit backend. | `run_secure_session` |
| Protocol inspector | Photon tape (Alice, Eve, Bob, sifting, error check) with Bob's Qiskit circuit per photon; decoy-state detection rates clean vs PNS. | `photon`, `channel`, `qiskit_protocol._measurement_circuit`, `decoy` |
| Detector evaluation | Held-out metrics, confusion matrices, time to detect, McNemar test, literature context, Qiskit validation, model card, figures. Can re-run the scripts. | `outputs/*.json`, `outputs/*.csv`, `train_phase5_unified.py`, `evaluate_qiskit_phase5.py`, `benchmark_phase4.py` |
| Post-quantum auth | Sign a reconciliation message, tamper with it or replay it and watch Bob reject it; ML-KEM round trip and wire sizes. | `bb84/pqc.py` |

## Layout

```text
ui/
├── __main__.py        # python -m ui
├── server.py          # FastAPI app: REST + /ws/link WebSocket + static files
├── services.py        # thin layer over bb84/ (live monitor, sessions, trace, PQC, jobs)
├── requirements.txt
└── static/
    ├── index.html
    ├── css/app.css
    ├── fonts/         # Schibsted Grotesk + Geist Mono (OFL), bundled for offline demos
    └── js/            # app.js router, charts.js, fiber.js, pages/*.js
```

No Node or build step: the frontend is plain ES modules. API docs are at
http://127.0.0.1:8000/api/docs.

## Notes

- Two places record extra detail for display without changing core code:
  the photon trace re-runs BB84 with the same primitives so it can show Eve's
  basis, and the session view wraps `AuthenticatedClassicalChannel` to capture
  the signed transcript.
- "Secure key, estimated" on the monitor uses the same estimate as the Phase 4
  stress test: half the sifted bits of every window that was not flagged.
- The fibre drift switch adds a slow 0 to 1.2 percentage-point noise swing.
  The detector was trained without drift, so this is a way to probe it, not a
  claimed result.
