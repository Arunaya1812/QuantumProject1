"""
decoy.py
--------
Implements the decoy-state method (Hwang, 2003 / Lo-Ma-Chen 2005 idea),
simplified for simulation purposes.

WHY DECOY STATES EXIST:
Real weak coherent pulse (WCP) sources sometimes emit more than one
photon per pulse. An eavesdropper can silently split off the extra
photon (Photon-Number-Splitting attack) without disturbing the QBER at
all, making a pure QBER-based check blind to this attack.

THE FIX:
Alice randomly sends pulses at different mean photon numbers (intensities):
    - "signal" state  (mu_signal, e.g. 0.5)  -> used for actual key
    - "decoy" state   (mu_decoy,  e.g. 0.1)  -> a trap, NOT used for key
    - "vacuum" state  (mu = 0)                -> optional, for calibration

Under normal (no-attack) conditions, the channel transmittance
(probability a pulse leads to a detection at Bob's side) should be
approximately THE SAME for signal and decoy pulses, since the channel
loss doesn't care what mean photon number Alice used.

Under a PNS attack, Eve tends to block/attenuate low-photon-number
pulses more (since decoys have fewer multi-photon pulses to exploit)
distorting the decoy vs. signal detection-rate ratio. That mismatch is
the tell-tale signature Alice and Bob check for.

This module simulates:
    - random assignment of each pulse to signal/decoy/vacuum
    - a simplified detection probability model per pulse type
    - the resulting detection-rate statistics Alice/Bob can compare
"""

import random
import numpy as np

PULSE_TYPES = ["signal", "decoy", "vacuum"]

class DecoyStateSource:
    def __init__(self,
                 mu_signal: float = 0.5,
                 mu_decoy: float = 0.1,
                 mu_vacuum: float = 0.0,
                 p_signal: float = 0.7,
                 p_decoy: float = 0.25,
                 p_vacuum: float = 0.05,
                 fiber_loss_db_per_km: float = 0.21,   # GYS 2004 fiber
                 detector_efficiency: float = 0.045,   # GYS 2004 detector
                 dark_count_rate: float = 1.7e-6,      # GYS 2004 dark counts
                 distance_km: float = 25):
        self.mu = {"signal": mu_signal, "decoy": mu_decoy, "vacuum": mu_vacuum}
        self.p = {"signal": p_signal, "decoy": p_decoy, "vacuum": p_vacuum}
        self.Y0 = dark_count_rate
        self.eta = detector_efficiency * (10 ** (-fiber_loss_db_per_km * distance_km / 10))

    def choose_pulse_type(self) -> str:
        return random.choices(
            PULSE_TYPES,
            weights=[self.p["signal"], self.p["decoy"], self.p["vacuum"]],
            k=1,
        )[0]

    def detection_probability(self, pulse_type, pns_attack):
        mu = self.mu[pulse_type]

        if not pns_attack:
            # Ma et al. 2005, Eq. 2 - normal channel gain
            return self.Y0 + 1 - np.exp(-self.eta * mu)

        # Idealized PNS attack: Eve perfectly identifies photon number.
        # She blocks vacuum (n=0) and single-photon (n=1) pulses,
        # forwards all multi-photon (n>=2) pulses with certainty
        # (this is the standard simplified PNS model used to justify
        # decoy states, e.g. Lo-Ma-Chen 2005, PRL 94, 230504)
        p0 = np.exp(-mu)
        p1 = mu * np.exp(-mu)
        p_multiphoton = 1 - p0 - p1
        return self.Y0 + p_multiphoton



    
    def simulate_pulses(self, n_pulses: int, pns_attack: bool = False):
        """
        Simulate n_pulses sent by Alice. Returns a list of dicts:
            {"type": "signal"/"decoy"/"vacuum", "detected": bool}
        """
        results = []
        for _ in range(n_pulses):
            pulse_type = self.choose_pulse_type()
            p_detect = self.detection_probability(pulse_type, pns_attack)
            detected = random.random() < p_detect
            results.append({"type": pulse_type, "detected": detected})
        return results


def detection_rate_by_type(pulse_results):
    """
    Given simulate_pulses() output, compute the detection rate
    (fraction detected) separately for each pulse type.
    """
    rates = {}
    for ptype in PULSE_TYPES:
        subset = [r["detected"] for r in pulse_results if r["type"] == ptype]
        rates[ptype] = float(np.mean(subset)) if subset else None
    return rates


def signal_decoy_gap(pulse_results) -> float:
    """
    Returns |signal_detection_rate - decoy_detection_rate|.
    Under normal conditions this gap should be small.
    Under a PNS attack this gap becomes large -- this is the key
    statistic used later (Phase 2) as an ML input feature.
    """
    rates = detection_rate_by_type(pulse_results)
    if rates["signal"] is None or rates["decoy"] is None:
        return 0.0
    return abs(rates["signal"] - rates["decoy"])
