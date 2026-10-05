"""Quantum-circuit implementation of BB84 using Qiskit Aer."""

from __future__ import annotations

import random

from .eavesdropper import Eavesdropper
from .photon import BASES
from .protocol import BB84Result


class QiskitUnavailableError(RuntimeError):
    pass


def _qiskit_imports():
    try:
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator
    except ImportError as exc:
        raise QiskitUnavailableError(
            "Qiskit simulation requires 'qiskit' and 'qiskit-aer'; install requirements.txt"
        ) from exc
    return QuantumCircuit, transpile, AerSimulator


def _prepare(qc, bit: int, basis: str) -> None:
    if bit:
        qc.x(0)
    if basis == "x":
        qc.h(0)


def _logical_bit_flip(qc, basis: str) -> None:
    # X flips computational-basis bits; Z flips diagonal-basis bits.
    qc.x(0) if basis == "+" else qc.z(0)


def _measurement_circuit(bit: int, prep_basis: str, measure_basis: str, flipped: bool):
    QuantumCircuit, _, _ = _qiskit_imports()
    qc = QuantumCircuit(1, 1)
    _prepare(qc, bit, prep_basis)
    if flipped:
        _logical_bit_flip(qc, prep_basis)
    if measure_basis == "x":
        qc.h(0)
    qc.measure(0, 0)
    return qc


def _run_one_shot(circuits, seed: int | None) -> list[int]:
    _, transpile, AerSimulator = _qiskit_imports()
    backend = AerSimulator(method="stabilizer")
    compiled = transpile(circuits, backend)
    result = backend.run(compiled, shots=1, seed_simulator=seed).result()
    return [int(next(iter(result.get_counts(i)))) for i in range(len(circuits))]


def run_bb84_qiskit(
    n_photons: int = 2000,
    noise_level: float = 0.02,
    eavesdropper: Eavesdropper | None = None,
    qber_sample_fraction: float = 0.5,
    seed: int | None = None,
) -> BB84Result:
    """
    Run BB84 with actual Qiskit state-preparation and measurement circuits.

    Decoy photon-number statistics remain in ``bb84.decoy`` because a
    one-qubit gate simulator does not model weak coherent optical pulses.
    """
    if n_photons < 1:
        raise ValueError("n_photons must be positive")
    if not 0.0 <= noise_level <= 1.0:
        raise ValueError("noise_level must be between 0 and 1")
    rng = random.Random(seed)
    eve = eavesdropper or Eavesdropper("none")

    alice_bits = [rng.randint(0, 1) for _ in range(n_photons)]
    alice_bases = [rng.choice(BASES) for _ in range(n_photons)]
    bob_bases = [rng.choice(BASES) for _ in range(n_photons)]
    flips = [rng.random() < noise_level for _ in range(n_photons)]

    eve_bits: dict[int, int] = {}
    eve_bases: dict[int, str] = {}
    intercepted: list[int] = []
    if eve.attack_type == "intercept_resend":
        intercepted = [i for i in range(n_photons) if rng.random() <= eve.intensity]
        first_circuits = []
        for i in intercepted:
            eve_bases[i] = rng.choice(BASES)
            first_circuits.append(
                _measurement_circuit(alice_bits[i], alice_bases[i], eve_bases[i], flips[i])
            )
        if first_circuits:
            measured = _run_one_shot(first_circuits, seed)
            eve_bits.update(dict(zip(intercepted, measured)))

    bob_circuits = []
    for i in range(n_photons):
        if i in eve_bits:
            bob_circuits.append(
                _measurement_circuit(eve_bits[i], eve_bases[i], bob_bases[i], False)
            )
        else:
            bob_circuits.append(
                _measurement_circuit(alice_bits[i], alice_bases[i], bob_bases[i], flips[i])
            )
    bob_bits = _run_one_shot(bob_circuits, None if seed is None else seed + 1)

    matching_mask = [a == b for a, b in zip(alice_bases, bob_bases)]
    sifted_alice = [b for b, match in zip(alice_bits, matching_mask) if match]
    sifted_bob = [b for b, match in zip(bob_bits, matching_mask) if match]
    sifted_length = len(sifted_alice)
    sample_size = int(sifted_length * qber_sample_fraction)
    sample_size = max(1, min(sample_size, sifted_length)) if sifted_length else 0
    sample_indices = rng.sample(range(sifted_length), sample_size) if sample_size else []
    qber = (
        sum(sifted_alice[i] != sifted_bob[i] for i in sample_indices) / sample_size
        if sample_size
        else 0.0
    )
    revealed = set(sample_indices)

    result = BB84Result()
    result.n_photons = n_photons
    result.sifted_length = sifted_length
    result.qber_sample_size = sample_size
    result.qber = qber
    result.final_key_length = sifted_length - sample_size
    result.alice_bits = alice_bits
    result.bob_bits = bob_bits
    result.matching_bases_mask = matching_mask
    result.sifted_alice_bits = sifted_alice
    result.sifted_bob_bits = sifted_bob
    result.qber_sample_indices = sorted(sample_indices)
    result.raw_key_alice = [b for i, b in enumerate(sifted_alice) if i not in revealed]
    result.raw_key_bob = [b for i, b in enumerate(sifted_bob) if i not in revealed]
    result.backend = "qiskit-aer-stabilizer"
    result.circuit_count = n_photons + len(intercepted)
    return result
