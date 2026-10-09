"""End-to-end Phase 3 pipeline: detect, authenticate, and derive a key."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from .decoy import DecoyStateSource, signal_decoy_gap
from .eavesdropper import Eavesdropper
from .pqc import (
    AuthenticatedClassicalChannel,
    PQCAuthenticator,
    PQCKeyExchange,
    derive_hybrid_key,
)
from .protocol import run_bb84
from .qiskit_protocol import run_bb84_qiskit
from .timeline import simulate_timeline
from .unified_detector import UnifiedAdaptiveMLDetector


@dataclass
class SecureSessionResult:
    accepted: bool
    reason: str
    protocol_backend: str
    windows_processed: int
    attack_windows_flagged: int
    qber: float | None = None
    qkd_key_bits: int = 0
    final_key: bytes | None = None
    final_key_fingerprint: str | None = None
    authenticated_messages: int = 0
    simulated_attack_start_fraction: float | None = None
    simulated_attack_start_window: int | None = None
    detector_history: list[dict[str, Any]] | None = None


def _authenticated_exchange(channel, sender, message_type, payload):
    envelope = channel.send(sender, message_type, payload)
    if not channel.receive(envelope):
        raise RuntimeError(f"authentication failed for {message_type}")


def run_secure_session(
    *,
    model_path: str | Path = "models/phase5_unified.joblib",
    protocol_backend: str = "probabilistic",
    attack_type: str = "none",
    attack_intensity: float = 1.0,
    attack_start_fraction: float = 0.5,
    noise_level: float = 0.02,
    n_windows: int = 40,
    photons_per_window: int = 250,
    final_key_photons: int = 2000,
    seed: int = 2026,
) -> SecureSessionResult:
    if not 0.0 <= attack_start_fraction < 1.0:
        raise ValueError("attack_start_fraction must be at least 0.0 and less than 1.0")

    attack_start_window = (
        int(n_windows * attack_start_fraction) if attack_type != "none" else None
    )
    detector = UnifiedAdaptiveMLDetector.from_joblib(model_path)
    rows = simulate_timeline(
        timeline_id=1,
        n_windows=n_windows,
        photons_per_window=photons_per_window,
        decoy_pulses_per_window=photons_per_window,
        noise_level=noise_level,
        attack_type=attack_type,
        attack_intensity=attack_intensity,
        attack_start_frac=attack_start_fraction,
        seed=seed,
    )
    decisions = [
        detector.update(row["qber"], row["signal_decoy_gap"]) for row in rows
    ]
    flagged = sum(d.attack_detected for d in decisions)
    # Require two detections to avoid aborting a key exchange on one isolated
    # noisy window while still reacting quickly to a sustained attack.
    if flagged >= 2:
        return SecureSessionResult(
            accepted=False,
            reason="eavesdropping_detected",
            protocol_backend=protocol_backend,
            windows_processed=len(rows),
            attack_windows_flagged=flagged,
            simulated_attack_start_fraction=(
                attack_start_fraction if attack_type != "none" else None
            ),
            simulated_attack_start_window=attack_start_window,
            detector_history=[d.as_dict() for d in decisions],
        )

    alice_auth = PQCAuthenticator.generate()
    bob_auth = PQCAuthenticator.generate()
    channel = AuthenticatedClassicalChannel()
    channel.register("alice", alice_auth)
    channel.register("bob", bob_auth)

    runner = run_bb84_qiskit if protocol_backend == "qiskit" else run_bb84
    if protocol_backend not in {"probabilistic", "qiskit"}:
        raise ValueError("protocol_backend must be 'probabilistic' or 'qiskit'")
    bb84 = runner(
        n_photons=final_key_photons,
        noise_level=noise_level,
        eavesdropper=Eavesdropper("none"),
        seed=seed + 1,
    )
    if not bb84.raw_key_alice:
        return SecureSessionResult(
            accepted=False,
            reason="insufficient_qkd_key_material",
            protocol_backend=protocol_backend,
            windows_processed=len(rows),
            attack_windows_flagged=flagged,
            qber=bb84.qber,
            simulated_attack_start_fraction=(
                attack_start_fraction if attack_type != "none" else None
            ),
            simulated_attack_start_window=attack_start_window,
        )

    _authenticated_exchange(
        channel,
        "alice",
        "basis_reconciliation",
        {"photons": bb84.n_photons, "matching_bases": bb84.sifted_length},
    )
    _authenticated_exchange(
        channel,
        "bob",
        "qber_estimate",
        {"sample_size": bb84.qber_sample_size, "qber": round(bb84.qber, 8)},
    )
    # Error correction is represented at protocol level: Bob accepts Alice's
    # reconciled raw bits after an authenticated syndrome exchange. A real
    # deployment would replace this with Cascade or LDPC reconciliation.
    corrected_bits = list(bb84.raw_key_alice)
    _authenticated_exchange(
        channel,
        "alice",
        "error_correction_syndrome",
        {
            "algorithm": "simulated-reconciliation",
            "raw_bits": len(corrected_bits),
            "bob_pre_correction_errors": sum(
                a != b for a, b in zip(bb84.raw_key_alice, bb84.raw_key_bob)
            ),
        },
    )

    bob_kem = PQCKeyExchange.generate_keypair()
    ciphertext, alice_pqc_secret = PQCKeyExchange.encapsulate(bob_kem.public_key)
    bob_pqc_secret = PQCKeyExchange.decapsulate(bob_kem.secret_key, ciphertext)
    if alice_pqc_secret != bob_pqc_secret:
        raise RuntimeError("ML-KEM shared-secret agreement failed")
    _authenticated_exchange(
        channel,
        "bob",
        "ml_kem_public_key",
        {"algorithm": "ML-KEM-768", "public_key_sha256": hashlib.sha256(bob_kem.public_key).hexdigest()},
    )
    _authenticated_exchange(
        channel,
        "alice",
        "ml_kem_ciphertext",
        {"ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest()},
    )
    _authenticated_exchange(
        channel,
        "alice",
        "privacy_amplification",
        {"kdf": "HKDF-SHA-256", "output_bytes": 32},
    )

    final_key = derive_hybrid_key(
        corrected_bits,
        alice_pqc_secret,
        transcript_hash=channel.transcript_hash(),
    )
    return SecureSessionResult(
        accepted=True,
        reason="authenticated_key_established",
        protocol_backend=protocol_backend,
        windows_processed=len(rows),
        attack_windows_flagged=flagged,
        qber=bb84.qber,
        qkd_key_bits=len(corrected_bits),
        final_key=final_key,
        final_key_fingerprint=hashlib.sha256(final_key).hexdigest()[:16],
        authenticated_messages=len(channel.transcript),
        simulated_attack_start_fraction=(
            attack_start_fraction if attack_type != "none" else None
        ),
        simulated_attack_start_window=attack_start_window,
        detector_history=[d.as_dict() for d in decisions],
    )
