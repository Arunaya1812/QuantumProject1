"""Post-quantum authentication, key establishment, and hybrid derivation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import secrets
from typing import Any


class PQCBackendUnavailable(RuntimeError):
    """Raised when the optional PQC implementation is not installed."""


def _load_signature_backend():
    try:
        from pqcrypto.sign import ml_dsa_65
    except ImportError as exc:
        raise PQCBackendUnavailable(
            "ML-DSA-65 requires the 'pqcrypto' package; install requirements.txt"
        ) from exc
    return ml_dsa_65


def _load_kem_backend():
    try:
        from pqcrypto.kem import ml_kem_768
    except ImportError as exc:
        raise PQCBackendUnavailable(
            "ML-KEM-768 requires the 'pqcrypto' package; install requirements.txt"
        ) from exc
    return ml_kem_768


@dataclass(frozen=True)
class MLDSAKeyPair:
    public_key: bytes
    secret_key: bytes


class PQCAuthenticator:
    """ML-DSA-65 signer/verifier for authenticated classical QKD traffic."""

    algorithm = "ML-DSA-65"

    def __init__(self, public_key: bytes, secret_key: bytes | None = None):
        self.public_key = bytes(public_key)
        self._secret_key = bytes(secret_key) if secret_key is not None else None

    @classmethod
    def generate(cls) -> "PQCAuthenticator":
        backend = _load_signature_backend()
        public_key, secret_key = backend.keygen()
        return cls(public_key, secret_key)

    def sign(self, message: bytes) -> bytes:
        if self._secret_key is None:
            raise ValueError("this authenticator does not contain a secret signing key")
        return bytes(_load_signature_backend().sign(self._secret_key, bytes(message)))

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            _load_signature_backend().verify(
                self.public_key, bytes(message), bytes(signature)
            )
            return True
        except Exception:
            return False


@dataclass(frozen=True)
class AuthenticatedMessage:
    session_id: str
    sequence: int
    sender: str
    message_type: str
    payload: dict[str, Any]
    signature: bytes

    def signed_bytes(self) -> bytes:
        body = {
            "message_type": self.message_type,
            "payload": self.payload,
            "sender": self.sender,
            "sequence": self.sequence,
            "session_id": self.session_id,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuthenticatedClassicalChannel:
    """Canonical ML-DSA envelopes with sender identity and replay protection."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or secrets.token_hex(16)
        self._signers: dict[str, PQCAuthenticator] = {}
        self._verifiers: dict[str, PQCAuthenticator] = {}
        self._send_sequences: dict[str, int] = {}
        self._receive_sequences: dict[str, int] = {}
        self.transcript: list[AuthenticatedMessage] = []

    def register(self, name: str, signer: PQCAuthenticator) -> None:
        self._signers[name] = signer
        self._verifiers[name] = PQCAuthenticator(signer.public_key)
        self._send_sequences.setdefault(name, 0)
        self._receive_sequences.setdefault(name, 0)

    @staticmethod
    def _unsigned_bytes(
        session_id: str,
        sequence: int,
        sender: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> bytes:
        body = {
            "message_type": message_type,
            "payload": payload,
            "sender": sender,
            "sequence": sequence,
            "session_id": session_id,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def send(self, sender: str, message_type: str, payload: dict[str, Any]) -> AuthenticatedMessage:
        if sender not in self._signers:
            raise KeyError(f"unknown channel participant: {sender}")
        sequence = self._send_sequences[sender]
        body = self._unsigned_bytes(
            self.session_id, sequence, sender, message_type, payload
        )
        envelope = AuthenticatedMessage(
            session_id=self.session_id,
            sequence=sequence,
            sender=sender,
            message_type=message_type,
            payload=payload,
            signature=self._signers[sender].sign(body),
        )
        self._send_sequences[sender] += 1
        return envelope

    def receive(self, envelope: AuthenticatedMessage) -> bool:
        if envelope.session_id != self.session_id or envelope.sender not in self._verifiers:
            return False
        expected = self._receive_sequences[envelope.sender]
        if envelope.sequence != expected:
            return False
        if not self._verifiers[envelope.sender].verify(
            envelope.signed_bytes(), envelope.signature
        ):
            return False
        self._receive_sequences[envelope.sender] += 1
        self.transcript.append(envelope)
        return True

    def transcript_hash(self) -> bytes:
        digest = hashlib.sha256()
        for message in self.transcript:
            digest.update(message.signed_bytes())
            digest.update(message.signature)
        return digest.digest()


@dataclass(frozen=True)
class MLKEMKeyPair:
    public_key: bytes
    secret_key: bytes


class PQCKeyExchange:
    """ML-KEM-768 encapsulation used as the PQC half of hybrid keying."""

    algorithm = "ML-KEM-768"

    @staticmethod
    def generate_keypair() -> MLKEMKeyPair:
        public_key, secret_key = _load_kem_backend().keygen()
        return MLKEMKeyPair(bytes(public_key), bytes(secret_key))

    @staticmethod
    def encapsulate(public_key: bytes) -> tuple[bytes, bytes]:
        ciphertext, shared_secret = _load_kem_backend().encaps(bytes(public_key))
        return bytes(ciphertext), bytes(shared_secret)

    @staticmethod
    def decapsulate(secret_key: bytes, ciphertext: bytes) -> bytes:
        return bytes(_load_kem_backend().decaps(bytes(secret_key), bytes(ciphertext)))


def bits_to_bytes(bits: list[int]) -> bytes:
    """Encode a bit list unambiguously, retaining the original bit length."""
    if any(bit not in (0, 1) for bit in bits):
        raise ValueError("QKD key material must contain only 0 and 1")
    packed = bytearray((len(bits) + 7) // 8)
    for index, bit in enumerate(bits):
        if bit:
            packed[index // 8] |= 1 << (7 - index % 8)
    return len(bits).to_bytes(4, "big") + bytes(packed)


def derive_hybrid_key(
    qkd_bits: list[int],
    pqc_shared_secret: bytes,
    *,
    transcript_hash: bytes,
    length: int = 32,
) -> bytes:
    """Combine QKD and ML-KEM entropy with HKDF-SHA-256 domain separation."""
    if not qkd_bits:
        raise ValueError("cannot derive a hybrid key from empty QKD material")
    if not pqc_shared_secret:
        raise ValueError("PQC shared secret cannot be empty")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    ikm = bits_to_bytes(qkd_bits) + bytes(pqc_shared_secret)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=bytes(transcript_hash),
        info=b"bb84-project/hybrid-qkd-ml-kem/v1",
    ).derive(ikm)
