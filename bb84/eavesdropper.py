"""
eavesdropper.py
---------------
Models Eve, the eavesdropper, and her possible attack strategies.

Two classic attacks are implemented:

1. Intercept-Resend Attack:
   Eve intercepts every photon, measures it in a randomly chosen basis,
   then re-sends a new photon prepared in the basis she measured with
   the bit she got. If her basis guess is wrong (50% of the time), she
   introduces errors that raise the QBER on Bob's side. This is the
   most basic and easiest-to-detect attack.

2. Photon-Number-Splitting (PNS) style attack (simplified):
   Real PNS attacks exploit weak coherent pulses that occasionally
   contain more than one photon. Eve splits off an extra photon,
   keeps it, and forwards the rest undisturbed -- this attack does NOT
   raise the QBER on Bob's side, which is exactly why decoy states were
   invented: decoy pulses (sent at a different mean photon number) let
   Alice and Bob detect the abnormal transmittance signature that a PNS
   attack leaves behind, even though the QBER alone looks normal.

   For Phase 1 we simulate this at the STATISTICS level (per decoy.py):
   we don't do full multi-photon quantum optics, we instead reproduce
   the key observable signature: under a PNS attack, decoy-state
   detection rates diverge from signal-state detection rates, while
   signal-only QBER stays low.

3. Partial / stealthy intercept-resend (attack intensity < 1.0):
   Eve only intercepts a FRACTION of photons instead of all of them.
   This produces a smaller, harder-to-detect QBER bump -- useful later
   for testing whether the adaptive ML detector (Phase 2) can catch
   stealthy attacks that a static threshold would miss.
"""

import random
from .photon import Photon, random_basis, measure


class Eavesdropper:
    def __init__(self, attack_type: str = "none", intensity: float = 1.0):
        """
        attack_type: "none" | "intercept_resend" | "pns"
        intensity:   fraction of photons Eve attacks (0.0 - 1.0).
                     1.0 = full attack, 0.3 = stealthy partial attack.
        """
        assert attack_type in ("none", "intercept_resend", "pns")
        assert 0.0 <= intensity <= 1.0
        self.attack_type = attack_type
        self.intensity = intensity

    def intercept(self, photon: Photon) -> Photon:
        """
        Eve intercepts a photon on the quantum channel. Returns the
        (possibly tampered) photon that continues on to Bob.

        Note: PNS-style attacks are NOT applied here on the qubit level
        (they don't disturb the signal channel's QBER by design) -- their
        effect is instead modeled in decoy.py at the detection-rate level.
        """
        if self.attack_type == "none":
            return photon

        if self.attack_type == "pns":
            # PNS attack, by design, does not touch signal-state qubits
            return photon

        if self.attack_type == "intercept_resend":
            if random.random() > self.intensity:
                # This particular photon is not attacked (stealthy mode)
                return photon
            eve_basis = random_basis()
            eve_bit = measure(photon, eve_basis)
            # Eve resends a fresh photon prepared in her guessed basis
            return Photon(eve_bit, eve_basis)

        return photon
