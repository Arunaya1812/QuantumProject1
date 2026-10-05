"""
photon.py
---------
Represents a single photon (qubit) used in the BB84 protocol.

We simulate polarization encoding using two possible bases:
    - Rectilinear basis ('+'): 0 -> horizontal (0 deg), 1 -> vertical (90 deg)
    - Diagonal basis ('x'):    0 -> +45 deg,            1 -> -45 deg (135 deg)

We don't simulate actual photon physics (Qiskit-level quantum states).
Instead we use the well-known probabilistic measurement model that is
mathematically equivalent to how BB84 behaves:

    - If Bob measures in the SAME basis Alice used to encode -> he gets
      the correct bit (subject to channel noise).
    - If Bob measures in a DIFFERENT basis -> he gets a uniformly random
      bit (50% correct, 50% wrong), which is the standard BB84 assumption.

This is the standard simplification used in almost all BB84 simulators
and textbooks, since it reproduces the exact statistics (QBER, sifted
key rate) that a full quantum-state simulation would produce.
"""

import random

BASES = ['+', 'x']  # rectilinear and diagonal


class Photon:
    """A single transmitted photon carrying one bit encoded in one basis."""

    __slots__ = ("bit", "basis")

    def __init__(self, bit: int, basis: str):
        assert bit in (0, 1), "bit must be 0 or 1"
        assert basis in BASES, "basis must be '+' or 'x'"
        self.bit = bit
        self.basis = basis

    def __repr__(self):
        return f"Photon(bit={self.bit}, basis='{self.basis}')"


def random_bit() -> int:
    return random.randint(0, 1)


def random_basis() -> str:
    return random.choice(BASES)


def measure(photon: Photon, measurement_basis: str) -> int:
    """
    Simulate Bob measuring an incoming photon in a chosen basis.

    Returns the measured bit.
    """
    if measurement_basis == photon.basis:
        # Same basis -> deterministic correct result
        return photon.bit
    else:
        # Different basis -> random result (50/50), standard BB84 behavior
        return random_bit()
