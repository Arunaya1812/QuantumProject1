"""
channel.py
----------
Simulates the quantum channel between Alice and Bob, including natural
environmental noise (independent of any eavesdropper).

We model noise as a simple depolarizing/bit-flip channel: with some
probability `noise_level`, the bit carried by the photon gets flipped
in transit (representing fiber imperfection, detector dark counts,
polarization drift, atmospheric turbulence for free-space links, etc).

This is intentionally simple for Phase 1. Later phases can plug in more
realistic noise models if needed.
"""

import random
from .photon import Photon


class QuantumChannel:
    def __init__(self, noise_level: float = 0.02):
        """
        noise_level: probability (0-1) that a photon's bit gets flipped
                     due to natural channel noise (NOT an attack).
        """
        assert 0.0 <= noise_level <= 1.0
        self.noise_level = noise_level

    def transmit(self, photon: Photon) -> Photon:
        """Send a photon through the channel, possibly flipping its bit."""
        bit = photon.bit
        if random.random() < self.noise_level:
            bit = 1 - bit
        return Photon(bit, photon.basis)
