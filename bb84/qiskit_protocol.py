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


def _run_parallel_shot(
    bits: list[int],
    prep_bases: list[str],
    measure_bases: list[str],
    flips: list[bool],
    seed: int | None,
) -> list[int]:
    """Measure independent BB84 photons in one multi-qubit Aer job.

    Each qubit still represents exactly one photon.  Batching avoids the very
    large transpilation overhead of creating one Qiskit job per photon and is
    therefore suitable for windowed detector evaluation.
    """
    QuantumCircuit, transpile, AerSimulator = _qiskit_imports()
    size = len(bits)
    if not (size == len(prep_bases) == len(measure_bases) == len(flips)):
        raise ValueError("parallel circuit inputs must have equal lengths")
    if size == 0:
        return []

    circuit = QuantumCircuit(size, size)
    for index, (bit, prep_basis, measure_basis, flipped) in enumerate(
        zip(bits, prep_bases, measure_bases, flips)
    ):
        if bit:
            circuit.x(index)
        if prep_basis == "x":
            circuit.h(index)
        if flipped:
            # X flips computational-basis bits; Z flips diagonal-basis bits.
            circuit.x(index) if prep_basis == "+" else circuit.z(index)
        if measure_basis == "x":
            circuit.h(index)
        circuit.measure(index, index)

    backend = AerSimulator(method="stabilizer")
    compiled = transpile(circuit, backend)
    result = backend.run(compiled, shots=1, seed_simulator=seed).result()
    bitstring = next(iter(result.get_counts())).replace(" ", "")
    # Qiskit displays classical bits from highest to lowest index.
    return [int(value) for value in reversed(bitstring)]


def _parallel_circuit(
    bits: list[int],
    prep_bases: list[str],
    measure_bases: list[str],
    flips: list[bool],
):
    QuantumCircuit, _, _ = _qiskit_imports()
    size = len(bits)
    if not (size == len(prep_bases) == len(measure_bases) == len(flips)):
        raise ValueError("parallel circuit inputs must have equal lengths")
    circuit = QuantumCircuit(size, size)
    for index, (bit, prep_basis, measure_basis, flipped) in enumerate(
        zip(bits, prep_bases, measure_bases, flips)
    ):
        if bit:
            circuit.x(index)
        if prep_basis == "x":
            circuit.h(index)
        if flipped:
            circuit.x(index) if prep_basis == "+" else circuit.z(index)
        if measure_basis == "x":
            circuit.h(index)
        circuit.measure(index, index)
    return circuit


def _run_parallel_circuit_batch(circuits, seed: int | None) -> list[list[int]]:
    """Run multiple independent multi-qubit BB84 circuits in one Aer job."""
    if not circuits:
        return []
    _, transpile, AerSimulator = _qiskit_imports()
    backend = AerSimulator(method="stabilizer")
    compiled = transpile(circuits, backend)
    result = backend.run(compiled, shots=1, seed_simulator=seed).result()
    outputs = []
    for index in range(len(circuits)):
        bitstring = next(iter(result.get_counts(index))).replace(" ", "")
        outputs.append([int(value) for value in reversed(bitstring)])
    return outputs


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
    return run_bb84_qiskit_batch([{
        "n_photons": n_photons,
        "noise_level": noise_level,
        "eavesdropper": eavesdropper,
        "qber_sample_fraction": qber_sample_fraction,
        "seed": seed,
    }])[0]


def run_bb84_qiskit_batch(requests: list[dict]) -> list[BB84Result]:
    """Run many independent BB84 windows using two batched Aer submissions.

    The first submission contains Eve's intercept measurements (when needed),
    and the second contains Bob's measurements.  Batching changes performance,
    not protocol semantics.
    """
    contexts = []
    eve_circuits = []
    eve_context_indices = []
    for request_index, request in enumerate(requests):
        n_photons = int(request.get("n_photons", 2000))
        noise_level = float(request.get("noise_level", 0.02))
        qber_sample_fraction = float(request.get("qber_sample_fraction", 0.5))
        seed = request.get("seed")
        if n_photons < 1:
            raise ValueError("n_photons must be positive")
        if not 0.0 <= noise_level <= 1.0:
            raise ValueError("noise_level must be between 0 and 1")
        rng = random.Random(seed)
        eve = request.get("eavesdropper") or Eavesdropper("none")
        alice_bits = [rng.randint(0, 1) for _ in range(n_photons)]
        alice_bases = [rng.choice(BASES) for _ in range(n_photons)]
        bob_bases = [rng.choice(BASES) for _ in range(n_photons)]
        flips = [rng.random() < noise_level for _ in range(n_photons)]
        intercepted = []
        eve_bases = {}
        if eve.attack_type == "intercept_resend":
            intercepted = [i for i in range(n_photons) if rng.random() <= eve.intensity]
            eve_bases = {i: rng.choice(BASES) for i in intercepted}
            if intercepted:
                eve_circuits.append(_parallel_circuit(
                    [alice_bits[i] for i in intercepted],
                    [alice_bases[i] for i in intercepted],
                    [eve_bases[i] for i in intercepted],
                    [flips[i] for i in intercepted],
                ))
                eve_context_indices.append(request_index)
        contexts.append({
            "n_photons": n_photons,
            "qber_sample_fraction": qber_sample_fraction,
            "rng": rng,
            "alice_bits": alice_bits,
            "alice_bases": alice_bases,
            "bob_bases": bob_bases,
            "flips": flips,
            "intercepted": intercepted,
            "eve_bases": eve_bases,
            "eve_bits": {},
        })

    batch_seed = next((request.get("seed") for request in requests
                       if request.get("seed") is not None), None)
    eve_outputs = _run_parallel_circuit_batch(eve_circuits, batch_seed)
    for context_index, measured in zip(eve_context_indices, eve_outputs):
        context = contexts[context_index]
        context["eve_bits"] = dict(zip(context["intercepted"], measured))

    bob_circuits = []
    for context in contexts:
        bob_input_bits, bob_input_bases, bob_flips = [], [], []
        for i in range(context["n_photons"]):
            if i in context["eve_bits"]:
                bob_input_bits.append(context["eve_bits"][i])
                bob_input_bases.append(context["eve_bases"][i])
                bob_flips.append(False)
            else:
                bob_input_bits.append(context["alice_bits"][i])
                bob_input_bases.append(context["alice_bases"][i])
                bob_flips.append(context["flips"][i])
        bob_circuits.append(_parallel_circuit(
            bob_input_bits, bob_input_bases, context["bob_bases"], bob_flips
        ))
    bob_outputs = _run_parallel_circuit_batch(
        bob_circuits, None if batch_seed is None else batch_seed + 1
    )

    results = []
    for context, bob_bits in zip(contexts, bob_outputs):
        matching_mask = [
            a == b for a, b in zip(context["alice_bases"], context["bob_bases"])
        ]
        sifted_alice = [
            b for b, match in zip(context["alice_bits"], matching_mask) if match
        ]
        sifted_bob = [b for b, match in zip(bob_bits, matching_mask) if match]
        sifted_length = len(sifted_alice)
        sample_size = int(sifted_length * context["qber_sample_fraction"])
        sample_size = max(1, min(sample_size, sifted_length)) if sifted_length else 0
        sample_indices = (
            context["rng"].sample(range(sifted_length), sample_size)
            if sample_size else []
        )
        qber = (
            sum(sifted_alice[i] != sifted_bob[i] for i in sample_indices) / sample_size
            if sample_size else 0.0
        )
        revealed = set(sample_indices)
        result = BB84Result()
        result.n_photons = context["n_photons"]
        result.sifted_length = sifted_length
        result.qber_sample_size = sample_size
        result.qber = qber
        result.final_key_length = sifted_length - sample_size
        result.alice_bits = context["alice_bits"]
        result.bob_bits = bob_bits
        result.matching_bases_mask = matching_mask
        result.sifted_alice_bits = sifted_alice
        result.sifted_bob_bits = sifted_bob
        result.qber_sample_indices = sorted(sample_indices)
        result.raw_key_alice = [
            b for i, b in enumerate(sifted_alice) if i not in revealed
        ]
        result.raw_key_bob = [
            b for i, b in enumerate(sifted_bob) if i not in revealed
        ]
        result.backend = "qiskit-aer-stabilizer-batched"
        result.circuit_count = 1 + int(bool(context["intercepted"]))
        result.photon_qubit_count = context["n_photons"] + len(context["intercepted"])
        results.append(result)
    return results
