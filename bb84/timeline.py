"""
timeline.py
-----------
Phase 1's simulator produces ONE QBER value per full session. That's
fine for a static "is this session an attack" check, but Phase 2 needs
something richer: a CONTINUOUS STREAM of QBER/decoy-gap measurements
over time, so we can:

  1. Compute temporal features (rolling mean, rolling std, rate of
     change, error bursts) -- these need a sequence, not a single point.
  2. Simulate an attack that STARTS partway through a session (realistic:
     Eve doesn't announce herself at t=0) so we can test how fast our
     adaptive detector notices something changed.
  3. Let the adaptive threshold "learn" a baseline from the early
     (attack-free) part of the stream, then watch it react when the
     attack begins.

This module simulates a "timeline": Alice and Bob repeatedly exchange
small batches of photons (a "window") back to back. Each window
produces one row of measurements (like a heartbeat monitor sampling
every few seconds). If an attack is configured, it switches on at a
random window index partway through -- windows before that index are
labeled normal (0), windows from that index onward are labeled attack (1).
"""

import random
from .protocol import run_bb84
from .qiskit_protocol import run_bb84_qiskit_batch
from .eavesdropper import Eavesdropper
from .decoy import DecoyStateSource, signal_decoy_gap


def simulate_timeline(
    timeline_id: int,
    n_windows: int = 120,
    photons_per_window: int = 250,
    decoy_pulses_per_window: int = 250,
    noise_level: float = 0.02,
    attack_type: str = "none",       # "none" | "intercept_resend" | "pns"
    attack_intensity: float = 1.0,   # only used for intercept_resend
    attack_start_frac: float = None, # fraction (0-1) of timeline where attack begins
    seed: int = None,
    protocol_backend: str = "probabilistic",
):
    """
    Simulate one full timeline of n_windows sequential BB84 sessions.

    Returns a list of dicts, one per window, each containing the raw
    measurements for that window plus the ground-truth label.
    """
    if seed is not None:
        random.seed(seed)
    if protocol_backend not in {"probabilistic", "qiskit"}:
        raise ValueError("protocol_backend must be 'probabilistic' or 'qiskit'")

    decoy_source = DecoyStateSource()

    if attack_type == "none":
        attack_start_window = None
    else:
        if attack_start_frac is None:
            # Random start somewhere in the middle third of the timeline
            attack_start_frac = random.uniform(0.3, 0.7)
        attack_start_window = int(n_windows * attack_start_frac)

    attack_states = []
    for w in range(n_windows):
        is_attack_active = (
            attack_type != "none"
            and attack_start_window is not None
            and w >= attack_start_window
        )

        if is_attack_active:
            eve = Eavesdropper(attack_type=attack_type, intensity=attack_intensity)
        else:
            eve = Eavesdropper(attack_type="none")

        attack_states.append((is_attack_active, eve))

    if protocol_backend == "qiskit":
        requests = [
            {
                "n_photons": photons_per_window,
                "noise_level": noise_level,
                "eavesdropper": eve,
                "seed": None if seed is None else seed * 1000 + w,
            }
            for w, (_, eve) in enumerate(attack_states)
        ]
        bb84_results = run_bb84_qiskit_batch(requests)
    else:
        bb84_results = [
            run_bb84(
                n_photons=photons_per_window,
                noise_level=noise_level,
                eavesdropper=eve,
            )
            for _, eve in attack_states
        ]

    rows = []
    for w, ((is_attack_active, _), result) in enumerate(zip(attack_states, bb84_results)):
        pns_flag = is_attack_active and attack_type == "pns"
        pulses = decoy_source.simulate_pulses(
            n_pulses=decoy_pulses_per_window, pns_attack=pns_flag
        )
        gap = signal_decoy_gap(pulses)

        rows.append({
            "timeline_id": timeline_id,
            "window_idx": w,
            "noise_level": noise_level,
            "attack_type": attack_type,
            "attack_intensity": attack_intensity if is_attack_active else 0.0,
            "qber": round(result.qber, 5),
            "sifted_length": result.sifted_length,
            "signal_decoy_gap": round(gap, 5),
            "is_attack": int(is_attack_active),
            "protocol_backend": protocol_backend,
        })

    return rows
