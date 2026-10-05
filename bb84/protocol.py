"""
protocol.py
-----------
Orchestrates a full BB84 run:

  1. Alice generates random bits and random bases, encodes photons.
  2. Photons pass through the quantum channel (natural noise applied).
  3. Eve optionally intercepts (intercept-resend attack).
  4. Bob randomly chooses measurement bases and measures each photon.
  5. Alice and Bob publicly compare (a sample of) their bases -> sifting:
     they keep only positions where their bases matched.
  6. From the sifted key, they publicly reveal a random subset of bits
     to estimate the Quantum Bit Error Rate (QBER). Those revealed bits
     are discarded; the rest becomes the raw secret key.

This module returns a rich result dictionary so Phase 2 (ML detection)
can later use the same simulator to generate labeled training data.
"""

import random
from .photon import Photon, random_bit, random_basis, measure
from .channel import QuantumChannel
from .eavesdropper import Eavesdropper


class BB84Result:
    def __init__(self):
        self.n_photons = 0
        self.sifted_length = 0
        self.qber_sample_size = 0
        self.qber = 0.0
        self.final_key_length = 0
        self.alice_bits = []
        self.bob_bits = []
        self.matching_bases_mask = []
        self.sifted_alice_bits = []
        self.sifted_bob_bits = []
        self.qber_sample_indices = []
        self.raw_key_alice = []
        self.raw_key_bob = []

    def as_dict(self):
        return {
            "n_photons": self.n_photons,
            "sifted_length": self.sifted_length,
            "qber_sample_size": self.qber_sample_size,
            "qber": self.qber,
            "final_key_length": self.final_key_length,
        }

    def __repr__(self):
        return (f"BB84Result(n_photons={self.n_photons}, "
                f"sifted_length={self.sifted_length}, "
                f"qber={self.qber:.4f}, "
                f"final_key_length={self.final_key_length})")


def run_bb84(
    n_photons: int = 2000,
    noise_level: float = 0.02,
    eavesdropper: Eavesdropper = None,
    qber_sample_fraction: float = 0.5,
    seed: int = None,
) -> BB84Result:
    """
    Run one full BB84 session.

    n_photons:            number of photons Alice sends
    noise_level:          natural channel noise probability
    eavesdropper:         an Eavesdropper instance (or None / "none" type)
    qber_sample_fraction: fraction of the sifted key publicly revealed
                          to estimate QBER (the rest becomes the secret key)
    seed:                 optional random seed for reproducibility
    """
    if seed is not None:
        random.seed(seed)

    if eavesdropper is None:
        eavesdropper = Eavesdropper(attack_type="none")

    channel = QuantumChannel(noise_level=noise_level)

    alice_bits = []
    alice_bases = []
    bob_bases = []
    bob_bits = []

    for _ in range(n_photons):
        bit = random_bit()
        basis = random_basis()
        alice_bits.append(bit)
        alice_bases.append(basis)

        photon = Photon(bit, basis)

        # 1. Channel noise
        photon = channel.transmit(photon)

        # 2. Eve's interception (if any)
        photon = eavesdropper.intercept(photon)

        # 3. Bob measures in his own randomly chosen basis
        b_basis = random_basis()
        bob_bases.append(b_basis)
        b_bit = measure(photon, b_basis)
        bob_bits.append(b_bit)

    # --- Sifting: keep only positions where bases matched ---
    sifted_alice = []
    sifted_bob = []
    matching_mask = []
    for i in range(n_photons):
        match = alice_bases[i] == bob_bases[i]
        matching_mask.append(match)
        if match:
            sifted_alice.append(alice_bits[i])
            sifted_bob.append(bob_bits[i])

    sifted_length = len(sifted_alice)

    # --- QBER estimation on a random public sample of the sifted key ---
    sample_size = int(sifted_length * qber_sample_fraction)
    sample_size = max(1, min(sample_size, sifted_length)) if sifted_length > 0 else 0

    if sample_size > 0:
        sample_indices = random.sample(range(sifted_length), sample_size)
        mismatches = sum(
            1 for i in sample_indices if sifted_alice[i] != sifted_bob[i]
        )
        qber = mismatches / sample_size
    else:
        sample_indices = []
        qber = 0.0

    final_key_length = sifted_length - sample_size

    result = BB84Result()
    result.n_photons = n_photons
    result.sifted_length = sifted_length
    result.qber_sample_size = sample_size
    result.qber = qber
    result.final_key_length = max(0, final_key_length)
    result.alice_bits = alice_bits
    result.bob_bits = bob_bits
    result.matching_bases_mask = matching_mask
    result.sifted_alice_bits = sifted_alice
    result.sifted_bob_bits = sifted_bob
    result.qber_sample_indices = sorted(sample_indices)
    revealed = set(sample_indices)
    result.raw_key_alice = [bit for i, bit in enumerate(sifted_alice) if i not in revealed]
    result.raw_key_bob = [bit for i, bit in enumerate(sifted_bob) if i not in revealed]

    return result
