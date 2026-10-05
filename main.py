"""
main.py
-------
Simple demo entry point. Runs a handful of BB84 sessions under
different conditions and prints the results, so you can sanity-check
the simulator before generating the full dataset or plotting graphs.

Run:
    python main.py
"""

from bb84.protocol import run_bb84
from bb84.eavesdropper import Eavesdropper
from bb84.decoy import DecoyStateSource, detection_rate_by_type, signal_decoy_gap


def demo_basic_bb84():
    print("=" * 60)
    print("1. BB84 with NO eavesdropper, low natural noise (2%)")
    print("=" * 60)
    eve = Eavesdropper(attack_type="none")
    result = run_bb84(n_photons=2000, noise_level=0.02, eavesdropper=eve, seed=1)
    print(result)
    print(f"  -> Expect QBER close to noise_level (~0.02). Got: {result.qber:.4f}\n")


def demo_intercept_resend():
    print("=" * 60)
    print("2. BB84 with FULL intercept-resend attack")
    print("=" * 60)
    eve = Eavesdropper(attack_type="intercept_resend", intensity=1.0)
    result = run_bb84(n_photons=2000, noise_level=0.02, eavesdropper=eve, seed=2)
    print(result)
    print("  -> Classic BB84 theory: full intercept-resend adds ~25% error rate")
    print(f"     on top of noise. Got QBER: {result.qber:.4f}\n")


def demo_stealthy_intercept_resend():
    print("=" * 60)
    print("3. BB84 with STEALTHY intercept-resend (20% of photons attacked)")
    print("=" * 60)
    eve = Eavesdropper(attack_type="intercept_resend", intensity=0.2)
    result = run_bb84(n_photons=2000, noise_level=0.02, eavesdropper=eve, seed=3)
    print(result)
    print("  -> Notice the QBER bump is much smaller here -- this is exactly")
    print("     the kind of stealthy attack a FIXED threshold might miss,")
    print(f"     which motivates the adaptive ML detector in Phase 2. QBER: {result.qber:.4f}\n")


def demo_decoy_states():
    print("=" * 60)
    print("4. Decoy-state statistics: normal channel vs PNS attack")
    print("=" * 60)
    source = DecoyStateSource()

    normal_pulses = source.simulate_pulses(n_pulses=3000, pns_attack=False)
    attack_pulses = source.simulate_pulses(n_pulses=3000, pns_attack=True)

    normal_rates = detection_rate_by_type(normal_pulses)
    attack_rates = detection_rate_by_type(attack_pulses)

    print(f"  Normal channel detection rates:  {normal_rates}")
    print(f"  Signal-decoy gap (normal):       {signal_decoy_gap(normal_pulses):.4f}")
    print()
    print(f"  Under PNS attack detection rates: {attack_rates}")
    print(f"  Signal-decoy gap (PNS attack):     {signal_decoy_gap(attack_pulses):.4f}")
    print("  -> Notice the gap grows sharply under PNS attack, even though")
    print("     the signal-channel QBER alone would look completely normal.")
    print("     This is exactly why decoy states are needed.\n")


if __name__ == "__main__":
    demo_basic_bb84()
    demo_intercept_resend()
    demo_stealthy_intercept_resend()
    demo_decoy_states()
