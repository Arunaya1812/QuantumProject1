"""
Service layer for the Basis console.

Everything here *calls* the project's existing ``bb84`` package; nothing in
``bb84/`` is modified. Where the UI needs data the core functions do not
return (Eve's basis per photon, the signed classical transcript), this module
records it with thin instrumentation that mirrors the core logic.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import math
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PRIMARY_MODEL = MODELS_DIR / "phase5_unified.joblib"
FALLBACK_MODEL = MODELS_DIR / "rf_detector.joblib"

ATTACK_TYPES = ("none", "intercept_resend", "pns")


# --------------------------------------------------------------------------
# Capabilities and model metadata
# --------------------------------------------------------------------------

def _probe_qiskit() -> bool:
    try:
        import qiskit  # noqa: F401
        import qiskit_aer  # noqa: F401
        return True
    except Exception:
        return False


def _probe_pqc() -> bool:
    try:
        from pqcrypto.sign import ml_dsa_65  # noqa: F401
        from pqcrypto.kem import ml_kem_768  # noqa: F401
        return True
    except Exception:
        return False


_capabilities: dict[str, bool] | None = None


def capabilities() -> dict[str, bool]:
    global _capabilities
    if _capabilities is None:
        _capabilities = {"qiskit": _probe_qiskit(), "pqc": _probe_pqc()}
    return _capabilities


def model_path() -> Path:
    return PRIMARY_MODEL if PRIMARY_MODEL.exists() else FALLBACK_MODEL


_model_cache: dict[str, Any] = {}
_model_lock = threading.Lock()


def load_model_package():
    """Return the raw joblib object (cached by path + mtime)."""
    import joblib

    path = model_path()
    if not path.exists():
        raise FileNotFoundError(
            "No trained detector found in models/. Run train_phase5_unified.py first."
        )
    key = f"{path}:{path.stat().st_mtime_ns}"
    with _model_lock:
        if key not in _model_cache:
            _model_cache.clear()
            _model_cache[key] = joblib.load(path)
        return _model_cache[key]


def new_detector():
    """A fresh UnifiedAdaptiveMLDetector built from the cached package."""
    from bb84.unified_detector import UnifiedAdaptiveMLDetector

    loaded = load_model_package()
    if isinstance(loaded, dict) and "base_model" in loaded:
        config = loaded.get("fusion_config", {})
        return UnifiedAdaptiveMLDetector(
            loaded["base_model"],
            fusion_model=loaded.get("fusion_model"),
            fusion_columns=loaded.get("fusion_columns"),
            fusion_guard_probability=config.get("guard_probability", 0.25),
        )
    model = loaded.get("model") if isinstance(loaded, dict) and "model" in loaded else loaded
    return UnifiedAdaptiveMLDetector(model)


def model_card() -> dict[str, Any]:
    from bb84.features import FEATURE_COLUMNS

    path = model_path()
    card: dict[str, Any] = {
        "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() else None,
        "available": path.exists(),
    }
    if not path.exists():
        return card
    loaded = load_model_package()
    stacked = isinstance(loaded, dict) and "base_model" in loaded
    base = loaded["base_model"] if stacked else (
        loaded.get("model") if isinstance(loaded, dict) else loaded
    )
    card["kind"] = "stacked_fusion" if stacked else "random_forest"
    card["base_model"] = {
        "type": type(base).__name__,
        "n_estimators": getattr(base, "n_estimators", None),
        "max_depth": getattr(base, "max_depth", None),
    }
    importances = getattr(base, "feature_importances_", None)
    names = list(getattr(base, "feature_names_in_", FEATURE_COLUMNS))
    if importances is not None:
        card["feature_importances"] = sorted(
            [{"feature": n, "importance": float(v)} for n, v in zip(names, importances)],
            key=lambda r: r["importance"],
            reverse=True,
        )
    if stacked:
        fusion = loaded.get("fusion_model")
        card["fusion_model"] = {
            "type": type(fusion).__name__ if fusion is not None else None,
            "columns": loaded.get("fusion_columns"),
            "config": loaded.get("fusion_config"),
        }
        card["training_metadata"] = loaded.get("training_metadata")
    card["modified"] = time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)
    )
    return card


# --------------------------------------------------------------------------
# Live link monitor
# --------------------------------------------------------------------------

@dataclass
class LinkSettings:
    attack_type: str = "none"
    intensity: float = 0.3
    noise: float = 0.02
    drift: bool = False
    photons: int = 250
    interval_ms: int = 450


@dataclass
class LinkMonitor:
    """One monitored Alice-Bob link. Produces one detector window per step."""

    settings: LinkSettings = field(default_factory=LinkSettings)
    window: int = 0
    secure_bits: float = 0.0
    alarms: int = 0
    attack_since: int | None = None

    def __post_init__(self):
        from bb84.decoy import DecoyStateSource

        self.detector = new_detector()
        self.decoy = DecoyStateSource()
        self._rng = random.Random()
        self._drift_phase = 0.0

    def reset(self):
        settings = self.settings
        self.__init__(settings=settings)  # type: ignore[misc]

    def effective_noise(self) -> float:
        base = self.settings.noise
        if not self.settings.drift:
            return base
        # Slow, bounded environmental drift (e.g. temperature cycling on fibre).
        # Noise oscillates between base and base + 1.2 percentage points.
        self._drift_phase += 0.045
        swing = 0.012 * (1 - math.cos(self._drift_phase)) / 2
        return max(0.0, min(0.2, base + swing))

    def step(self) -> dict[str, Any]:
        from bb84.decoy import signal_decoy_gap
        from bb84.eavesdropper import Eavesdropper
        from bb84.protocol import run_bb84

        s = self.settings
        active = s.attack_type != "none"
        eve = Eavesdropper(s.attack_type, s.intensity) if active else Eavesdropper("none")
        noise = self.effective_noise()
        result = run_bb84(n_photons=s.photons, noise_level=noise, eavesdropper=eve)
        pulses = self.decoy.simulate_pulses(
            n_pulses=s.photons, pns_attack=(active and s.attack_type == "pns")
        )
        gap = signal_decoy_gap(pulses)
        decision = self.detector.update(result.qber, gap)

        adaptive_state = self.detector.multi_adaptive.history[-1]
        if decision.attack_detected:
            self.alarms += 1
        elif decision.reason != "calibrating":
            # Same estimate the Phase 4 stress test uses: half the sifted bits
            # survive error estimation in a window that was not flagged.
            self.secure_bits += result.sifted_length * 0.5

        payload = {
            "window": self.window,
            "qber": result.qber,
            "gap": gap,
            "sifted": result.sifted_length,
            "noise": noise,
            "attack_active": active,
            "attack_type": s.attack_type,
            "intensity": s.intensity if active else 0.0,
            "detected": decision.attack_detected,
            "reason": decision.reason,
            "ml_probability": decision.ml_probability,
            "fusion_probability": decision.fusion_probability,
            "qber_threshold": adaptive_state.get("qber_threshold"),
            "gap_threshold": adaptive_state.get("gap_threshold"),
            "qber_flag": decision.qber_adaptive_flag,
            "gap_flag": decision.gap_adaptive_flag,
            "baseline_update_allowed": decision.baseline_update_allowed,
            "calibrating": decision.reason == "calibrating",
            "calibration_target": self.detector._calibration_windows,
            "secure_bits": self.secure_bits,
            "alarms": self.alarms,
        }
        self.window += 1
        return payload


# --------------------------------------------------------------------------
# End-to-end secure session (with transcript instrumentation)
# --------------------------------------------------------------------------

_session_lock = threading.Lock()
_session_history: list[dict[str, Any]] = []


@contextlib.contextmanager
def _record_transcripts():
    """Swap in a channel subclass that remembers every instance it creates."""
    import bb84.secure_session as secure_session
    from bb84.pqc import AuthenticatedClassicalChannel

    created: list[Any] = []

    class RecordingChannel(AuthenticatedClassicalChannel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    original = secure_session.AuthenticatedClassicalChannel
    secure_session.AuthenticatedClassicalChannel = RecordingChannel
    try:
        yield created
    finally:
        secure_session.AuthenticatedClassicalChannel = original


def _summarise_payload(payload: dict[str, Any]) -> str:
    parts = []
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 20:
            value = value[:12] + "…"
        parts.append(f"{key}={value}")
    return ", ".join(parts)


def run_session(params: dict[str, Any]) -> dict[str, Any]:
    from bb84.secure_session import run_secure_session

    attack = params.get("attack", "none")
    if attack not in ATTACK_TYPES:
        raise ValueError("attack must be none, intercept_resend or pns")
    backend = params.get("backend", "probabilistic")
    if backend == "qiskit" and not capabilities()["qiskit"]:
        raise ValueError("Qiskit is not installed in this environment")
    if not capabilities()["pqc"]:
        raise ValueError("pqcrypto is not installed; post-quantum authentication is unavailable")

    kwargs = dict(
        model_path=model_path(),
        protocol_backend=backend,
        attack_type=attack,
        attack_intensity=float(params.get("intensity", 1.0)),
        attack_start_fraction=float(params.get("attack_start", 0.5)),
        noise_level=float(params.get("noise", 0.02)),
        n_windows=int(params.get("windows", 40)),
        final_key_photons=int(params.get("photons", 2000)),
        seed=int(params.get("seed", 2026)),
    )
    if kwargs["n_windows"] < 12:
        raise ValueError("Use at least 12 monitoring windows (10 are used for calibration)")

    with _session_lock:
        started = time.perf_counter()
        with _record_transcripts() as channels:
            result = run_secure_session(**kwargs)
        elapsed_ms = (time.perf_counter() - started) * 1000

    transcript = []
    if channels:
        for env in channels[0].transcript:
            transcript.append({
                "sequence": env.sequence,
                "sender": env.sender,
                "type": env.message_type,
                "payload": env.payload,
                "summary": _summarise_payload(env.payload),
                "signature_bytes": len(env.signature),
                "signature_prefix": env.signature[:6].hex(),
                "verified": True,
            })
        transcript_hash = channels[0].transcript_hash().hex()[:16]
    else:
        transcript_hash = None

    start_window = result.simulated_attack_start_window
    history = []
    for d in result.detector_history or []:
        w = d["window_index"]
        history.append({
            "window": w,
            "qber": d["features"]["qber"],
            "gap": d["features"]["signal_decoy_gap"],
            "ml_probability": d["ml_probability"],
            "fusion_probability": d["fusion_probability"],
            "threshold": d["adaptive_threshold"],
            "detected": d["attack_detected"],
            "reason": d["reason"],
            "truth": int(start_window is not None and w >= start_window),
        })

    first_alarm = next((h["window"] for h in history if h["detected"]), None)
    record = {
        "id": hashlib.sha1(f"{time.time_ns()}".encode()).hexdigest()[:8],
        "created": time.strftime("%H:%M:%S"),
        "params": {**{k: v for k, v in kwargs.items() if k != "model_path"}},
        "accepted": result.accepted,
        "reason": result.reason,
        "qber": result.qber,
        "qkd_key_bits": result.qkd_key_bits,
        "fingerprint": result.final_key_fingerprint,
        "authenticated_messages": result.authenticated_messages,
        "windows": result.windows_processed,
        "flagged": result.attack_windows_flagged,
        "attack_start_window": start_window,
        "first_alarm_window": first_alarm,
        "detection_delay": (
            None if first_alarm is None or start_window is None
            else max(0, first_alarm - start_window)
        ),
        "elapsed_ms": elapsed_ms,
        "transcript": transcript,
        "transcript_hash": transcript_hash,
        "history": history,
    }
    _session_history.insert(0, {k: v for k, v in record.items() if k not in ("history", "transcript")})
    del _session_history[30:]
    return record


def session_history() -> list[dict[str, Any]]:
    return list(_session_history)


# --------------------------------------------------------------------------
# Protocol inspector: photon-by-photon BB84 trace
# --------------------------------------------------------------------------

POLARISATION = {("+", 0): "0°", ("+", 1): "90°", ("x", 0): "45°", ("x", 1): "135°"}


def trace_bb84(params: dict[str, Any]) -> dict[str, Any]:
    """
    Step through BB84 one photon at a time, recording every intermediate value.

    Mirrors bb84.protocol.run_bb84 (channel noise, then Eve, then Bob) using
    the same primitives, but keeps Eve's basis and bit so they can be shown.
    """
    from bb84.channel import QuantumChannel
    from bb84.photon import Photon, measure, random_basis, random_bit

    n = max(8, min(96, int(params.get("photons", 32))))
    noise = float(params.get("noise", 0.02))
    attack = params.get("attack", "none")
    intensity = float(params.get("intensity", 1.0))
    seed = params.get("seed")
    sample_fraction = float(params.get("sample_fraction", 0.5))
    if attack not in ATTACK_TYPES:
        raise ValueError("unknown attack type")

    state = random.getstate()
    if seed is not None:
        random.seed(int(seed))
    try:
        channel = QuantumChannel(noise_level=noise)
        rows = []
        for i in range(n):
            bit, basis = random_bit(), random_basis()
            sent = Photon(bit, basis)
            after_noise = channel.transmit(sent)
            noise_flip = after_noise.bit != sent.bit
            eve_basis = eve_bit = None
            in_flight = after_noise
            if attack == "intercept_resend" and random.random() <= intensity:
                eve_basis = random_basis()
                eve_bit = measure(after_noise, eve_basis)
                in_flight = Photon(eve_bit, eve_basis)
            bob_basis = random_basis()
            bob_bit = measure(in_flight, bob_basis)
            rows.append({
                "index": i,
                "alice_bit": bit,
                "alice_basis": basis,
                "polarisation": POLARISATION[(basis, bit)],
                "noise_flip": noise_flip,
                "eve_basis": eve_basis,
                "eve_bit": eve_bit,
                "bob_basis": bob_basis,
                "bob_bit": bob_bit,
                "kept": basis == bob_basis,
            })
        kept = [r for r in rows if r["kept"]]
        k = len(kept)
        sample_size = max(1, min(k, int(k * sample_fraction))) if k else 0
        sampled = set(random.sample(range(k), sample_size)) if sample_size else set()
    finally:
        random.setstate(state)

    errors = 0
    for pos, r in enumerate(kept):
        r["sifted_position"] = pos
        r["sampled"] = pos in sampled
        r["error"] = r["alice_bit"] != r["bob_bit"]
        if r["sampled"] and r["error"]:
            errors += 1
    for r in rows:
        r.setdefault("sifted_position", None)
        r.setdefault("sampled", False)
        r.setdefault("error", False)

    key_alice = "".join(str(r["alice_bit"]) for r in kept if not r["sampled"])
    key_bob = "".join(str(r["bob_bit"]) for r in kept if not r["sampled"])
    return {
        "rows": rows,
        "summary": {
            "photons": n,
            "sifted": k,
            "sample_size": sample_size,
            "sample_errors": errors,
            "qber": errors / sample_size if sample_size else 0.0,
            "key_alice": key_alice,
            "key_bob": key_bob,
            "key_mismatches": sum(a != b for a, b in zip(key_alice, key_bob)),
            "intercepted": sum(r["eve_basis"] is not None for r in rows),
        },
    }


def circuit_for(bit: int, prep: str, measure_basis: str, flipped: bool) -> dict[str, Any]:
    if not capabilities()["qiskit"]:
        return {"available": False}
    from bb84.qiskit_protocol import _measurement_circuit

    qc = _measurement_circuit(int(bit), prep, measure_basis, bool(flipped))
    ops = [instr.operation.name for instr in qc.data]
    return {"available": True, "text": str(qc.draw(output="text")), "ops": ops}


# --------------------------------------------------------------------------
# Decoy-state statistics
# --------------------------------------------------------------------------

def decoy_stats(params: dict[str, Any]) -> dict[str, Any]:
    from bb84.decoy import DecoyStateSource, detection_rate_by_type, signal_decoy_gap

    distance = float(params.get("distance", 25))
    pulses = max(2000, min(200000, int(params.get("pulses", 40000))))
    seed = params.get("seed", 7)
    state = random.getstate()
    random.seed(int(seed))
    try:
        source = DecoyStateSource(distance_km=distance)
        normal = source.simulate_pulses(pulses, pns_attack=False)
        attacked = source.simulate_pulses(pulses, pns_attack=True)
    finally:
        random.setstate(state)
    theory = {
        t: {
            "normal": float(source.detection_probability(t, False)),
            "pns": float(source.detection_probability(t, True)),
        }
        for t in ("signal", "decoy", "vacuum")
    }
    return {
        "distance_km": distance,
        "pulses": pulses,
        "transmittance": source.eta,
        "normal": {"rates": detection_rate_by_type(normal), "gap": signal_decoy_gap(normal)},
        "pns": {"rates": detection_rate_by_type(attacked), "gap": signal_decoy_gap(attacked)},
        "theory": theory,
        "mu": source.mu,
    }


# --------------------------------------------------------------------------
# Post-quantum lab
# --------------------------------------------------------------------------

def _ms(start: int) -> float:
    return (time.perf_counter_ns() - start) / 1e6


def pqc_signature(params: dict[str, Any]) -> dict[str, Any]:
    from bb84.pqc import AuthenticatedClassicalChannel, PQCAuthenticator

    message_type = params.get("message_type", "basis_reconciliation")
    payload = params.get("payload") or {"photons": 2000, "matching_bases": 1004}
    tamper = bool(params.get("tamper"))
    replay = bool(params.get("replay"))

    t = time.perf_counter_ns()
    alice = PQCAuthenticator.generate()
    keygen_ms = _ms(t)
    bob = PQCAuthenticator.generate()
    channel = AuthenticatedClassicalChannel()
    channel.register("alice", alice)
    channel.register("bob", bob)

    t = time.perf_counter_ns()
    envelope = channel.send("alice", message_type, payload)
    sign_ms = _ms(t)

    delivered = envelope
    tamper_note = None
    if tamper:
        from dataclasses import replace

        forged = dict(payload)
        first = next(iter(forged), None)
        if first is not None and isinstance(forged[first], (int, float)):
            forged[first] = forged[first] + 1
        else:
            forged["forged"] = True
        delivered = replace(envelope, payload=forged)
        tamper_note = f"payload changed in transit: {_summarise_payload(forged)}"

    t = time.perf_counter_ns()
    accepted = channel.receive(delivered)
    verify_ms = _ms(t)

    replay_accepted = None
    if replay and accepted:
        replay_accepted = channel.receive(envelope)

    return {
        "algorithm": PQCAuthenticator.algorithm,
        "public_key_bytes": len(alice.public_key),
        "signature_bytes": len(envelope.signature),
        "signed_bytes": len(envelope.signed_bytes()),
        "public_key_fingerprint": hashlib.sha256(alice.public_key).hexdigest()[:16],
        "signature_preview": envelope.signature[:24].hex(),
        "session_id": channel.session_id,
        "sequence": envelope.sequence,
        "canonical_message": envelope.signed_bytes().decode(),
        "keygen_ms": keygen_ms,
        "sign_ms": sign_ms,
        "verify_ms": verify_ms,
        "tampered": tamper,
        "tamper_note": tamper_note,
        "accepted": accepted,
        "replay_attempted": replay and accepted,
        "replay_accepted": replay_accepted,
    }


def pqc_kem() -> dict[str, Any]:
    from bb84.pqc import PQCKeyExchange, derive_hybrid_key

    t = time.perf_counter_ns()
    pair = PQCKeyExchange.generate_keypair()
    keygen_ms = _ms(t)
    t = time.perf_counter_ns()
    ciphertext, alice_secret = PQCKeyExchange.encapsulate(pair.public_key)
    encaps_ms = _ms(t)
    t = time.perf_counter_ns()
    bob_secret = PQCKeyExchange.decapsulate(pair.secret_key, ciphertext)
    decaps_ms = _ms(t)

    qkd_bits = [random.randint(0, 1) for _ in range(256)]
    transcript_hash = hashlib.sha256(b"basis-console-demo-transcript").digest()
    hybrid = derive_hybrid_key(qkd_bits, alice_secret, transcript_hash=transcript_hash)
    return {
        "algorithm": PQCKeyExchange.algorithm,
        "public_key_bytes": len(pair.public_key),
        "ciphertext_bytes": len(ciphertext),
        "shared_secret_bytes": len(alice_secret),
        "secrets_match": alice_secret == bob_secret,
        "shared_secret_fingerprint": hashlib.sha256(alice_secret).hexdigest()[:16],
        "hybrid_key_fingerprint": hashlib.sha256(hybrid).hexdigest()[:16],
        "keygen_ms": keygen_ms,
        "encaps_ms": encaps_ms,
        "decaps_ms": decaps_ms,
    }


# --------------------------------------------------------------------------
# Evaluation artifacts (read from outputs/)
# --------------------------------------------------------------------------

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_csv(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return None


def _mtime(path: Path):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)) if path.exists() else None


def evaluation_bundle() -> dict[str, Any]:
    o = OUTPUTS_DIR
    figures = sorted(p.name for p in o.glob("*.png")) if o.exists() else []
    return {
        "phase5": _read_json(o / "phase5_evaluation_report.json"),
        "phase5_updated": _mtime(o / "phase5_evaluation_report.json"),
        "literature": _read_csv(o / "phase5_literature_comparison.csv"),
        "qiskit": _read_json(o / "phase5_qiskit_evaluation.json"),
        "qiskit_updated": _mtime(o / "phase5_qiskit_evaluation.json"),
        "phase4": _read_json(o / "phase4_benchmark_report.json"),
        "stress": _read_csv(o / "phase4_stress_results.csv"),
        "figures": figures,
    }


# --------------------------------------------------------------------------
# Background jobs (re-run the project's own scripts)
# --------------------------------------------------------------------------

JOB_RECIPES: dict[str, dict[str, Any]] = {
    "phase5": {
        "label": "Retrain and evaluate the unified detector",
        "steps": [
            (["generate_timeline_dataset.py"], "data/bb84_windows_raw.csv"),
            (["feature_engineering.py"], "data/bb84_features_dataset.csv"),
            (["train_phase5_unified.py"], None),
        ],
        "note": "Overwrites models/phase5_unified.joblib",
    },
    "qiskit": {
        "label": "Run the Qiskit backend comparison",
        "steps": [(["evaluate_qiskit_phase5.py"], None)],
        "note": "About 30 seconds on a laptop",
    },
    "phase4": {
        "label": "Run the Phase 4 quick benchmark",
        "steps": [
            (["generate_timeline_dataset.py"], "data/bb84_windows_raw.csv"),
            (["feature_engineering.py"], "data/bb84_features_dataset.csv"),
            (["benchmark_phase4.py", "--quick"], None),
        ],
        "note": "Uses models/rf_detector.joblib",
    },
}

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def start_job(kind: str) -> dict[str, Any]:
    import subprocess
    import sys

    if kind not in JOB_RECIPES:
        raise ValueError("unknown job")
    with _jobs_lock:
        if any(j["status"] == "running" for j in _jobs.values()):
            raise RuntimeError("Another evaluation job is still running")
        job_id = hashlib.sha1(f"{kind}{time.time_ns()}".encode()).hexdigest()[:8]
        job = {"id": job_id, "kind": kind, "label": JOB_RECIPES[kind]["label"],
               "status": "running", "log": [], "started": time.strftime("%H:%M:%S"),
               "step": None}
        _jobs[job_id] = job

    def worker():
        try:
            for args, skip_if_exists in JOB_RECIPES[kind]["steps"]:
                if skip_if_exists and (PROJECT_ROOT / skip_if_exists).exists():
                    job["log"].append(f"Skipping {args[0]} ({skip_if_exists} already exists)")
                    continue
                job["step"] = args[0]
                job["log"].append(f"$ python {' '.join(args)}")
                (PROJECT_ROOT / "data").mkdir(exist_ok=True)
                (PROJECT_ROOT / "outputs").mkdir(exist_ok=True)
                proc = subprocess.Popen(
                    [sys.executable, "-u", *args], cwd=PROJECT_ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace",
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    job["log"].append(line.rstrip())
                    del job["log"][:-400]
                if proc.wait() != 0:
                    job["status"] = "failed"
                    job["log"].append(f"{args[0]} exited with code {proc.returncode}")
                    return
            job["status"] = "done"
        except Exception as exc:  # pragma: no cover - surfaced to UI
            job["status"] = "failed"
            job["log"].append(str(exc))
        finally:
            job["step"] = None
            job["finished"] = time.strftime("%H:%M:%S")
            if kind == "phase5":
                with _model_lock:
                    _model_cache.clear()

    threading.Thread(target=worker, daemon=True).start()
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    return {**job, "log": job["log"][-200:]}


def job_catalog() -> list[dict[str, Any]]:
    running = [j for j in _jobs.values() if j["status"] == "running"]
    return [
        {"kind": k, "label": v["label"], "note": v["note"],
         "running": any(j["kind"] == k for j in running),
         "job_id": next((j["id"] for j in running if j["kind"] == k), None)}
        for k, v in JOB_RECIPES.items()
    ]
