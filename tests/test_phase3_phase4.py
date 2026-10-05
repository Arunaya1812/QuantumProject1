from __future__ import annotations

import unittest

from bb84.eavesdropper import Eavesdropper
from bb84.features import FEATURE_COLUMNS, OnlineFeatureEngineer
from bb84.protocol import run_bb84
from bb84.unified_detector import UnifiedAdaptiveMLDetector


class _GapAwareModel:
    classes_ = [0, 1]

    def predict_proba(self, rows):
        if hasattr(rows, "to_dict"):
            values = rows.to_dict("records")
        else:
            values = [dict(zip(FEATURE_COLUMNS, rows[0]))]
        probability = 0.99 if values[0]["signal_decoy_gap"] > 0.1 else 0.01
        return [[1.0 - probability, probability]]


class Phase34Tests(unittest.TestCase):
    def test_online_features_have_training_schema(self):
        features = OnlineFeatureEngineer().update(0.02, 0.01)
        self.assertEqual(list(features.as_dict()), FEATURE_COLUMNS)

    def test_ml_alarm_freezes_adaptive_baseline(self):
        detector = UnifiedAdaptiveMLDetector(_GapAwareModel(), calibration_windows=2)
        detector.update(0.01, 0.01)
        detector.update(0.01, 0.01)
        decision = detector.update(0.02, 0.2)
        self.assertTrue(decision.attack_detected)
        self.assertFalse(decision.baseline_update_allowed)
        self.assertFalse(detector.adaptive.history[-1]["adapted"])

    def test_probabilistic_protocol_exposes_unrevealed_key(self):
        result = run_bb84(400, 0.0, Eavesdropper("none"), seed=4)
        self.assertEqual(len(result.raw_key_alice), result.final_key_length)
        self.assertEqual(result.raw_key_alice, result.raw_key_bob)

    def test_pqc_signatures_and_kem_when_available(self):
        try:
            from bb84.pqc import PQCAuthenticator, PQCKeyExchange
            signer = PQCAuthenticator.generate()
        except Exception as exc:
            self.skipTest(str(exc))
        message = b"basis reconciliation"
        signature = signer.sign(message)
        self.assertTrue(signer.verify(message, signature))
        self.assertFalse(signer.verify(message + b"!", signature))
        keypair = PQCKeyExchange.generate_keypair()
        ciphertext, shared_a = PQCKeyExchange.encapsulate(keypair.public_key)
        shared_b = PQCKeyExchange.decapsulate(keypair.secret_key, ciphertext)
        self.assertEqual(shared_a, shared_b)

    def test_qiskit_bb84_when_available(self):
        try:
            from bb84.qiskit_protocol import run_bb84_qiskit
            result = run_bb84_qiskit(128, 0.0, Eavesdropper("none"), seed=7)
        except Exception as exc:
            self.skipTest(str(exc))
        self.assertEqual(result.qber, 0.0)
        self.assertEqual(result.raw_key_alice, result.raw_key_bob)


if __name__ == "__main__":
    unittest.main()
