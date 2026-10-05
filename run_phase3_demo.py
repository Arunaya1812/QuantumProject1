"""Run the integrated Phase 3 detector, PQC authentication, and key flow."""

from __future__ import annotations

import argparse
import json

from bb84.secure_session import run_secure_session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["probabilistic", "qiskit"], default="probabilistic")
    parser.add_argument("--attack", choices=["none", "intercept_resend", "pns"], default="none")
    parser.add_argument("--intensity", type=float, default=1.0)
    parser.add_argument("--noise", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--windows", type=int, default=40)
    parser.add_argument("--photons", type=int, default=2000, help="final key-exchange photons")
    args = parser.parse_args()

    result = run_secure_session(
        protocol_backend=args.backend,
        attack_type=args.attack,
        attack_intensity=args.intensity,
        noise_level=args.noise,
        n_windows=args.windows,
        final_key_photons=args.photons,
        seed=args.seed,
    )
    public_result = {
        key: value
        for key, value in vars(result).items()
        if key not in {"final_key", "detector_history"}
    }
    print(json.dumps(public_result, indent=2))
    raise SystemExit(0 if result.accepted or result.reason == "eavesdropping_detected" else 1)


if __name__ == "__main__":
    main()
