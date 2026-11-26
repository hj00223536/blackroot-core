"""Detached Ed25519 approval verification for proposed BLACKROOT genesis manifests.

This module verifies evidence against a caller-supplied trust anchor. It does
not establish who owns that anchor, create keys, or authorize database writes.
"""
from __future__ import annotations

import hashlib
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_DOMAIN = b"BLACKROOT-GENESIS-APPROVAL-V1\x00"
_SCOPE = "genesis-founder-allocation"
_FIELDS = frozenset({
    "record_version", "network_id", "manifest_digest", "approval_scope",
    "signing_key_id", "signature_algorithm", "signature",
})


def _hex32(value: object, field: str) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be 64 lowercase hexadecimal characters")
    if any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{field} must be canonical lowercase hexadecimal")
    return bytes.fromhex(value)


def approval_message(network_id: str, manifest_digest: str) -> bytes:
    """Return the exact domain-separated message that the owner approves."""
    network = _hex32(network_id, "network_id")
    digest = _hex32(manifest_digest, "manifest_digest")
    return _DOMAIN + network + digest + _SCOPE.encode("utf-8")


def verify_genesis_approval_record(
    record: Mapping[str, object],
    *,
    expected_network_id: str,
    expected_manifest_digest: str,
    trusted_public_keys: Mapping[str, bytes],
    revoked_key_ids: frozenset[str] = frozenset(),
) -> str:
    """Verify detached approval against independently pinned raw Ed25519 keys.

    trusted_public_keys maps SHA-256(raw 32-byte public key) hex identifiers
    to raw 32-byte public keys. Trust-anchor governance remains external.
    Returns the verified key id; raises ValueError on every invalid condition.
    """
    if not isinstance(record, Mapping) or set(record) != _FIELDS:
        raise ValueError("approval record fields mismatch")
    if type(record["record_version"]) is not int or record["record_version"] != 1:
        raise ValueError("unsupported approval record version")
    network = _hex32(record["network_id"], "network_id")
    digest = _hex32(record["manifest_digest"], "manifest_digest")
    expected_network = _hex32(expected_network_id, "expected_network_id")
    expected_digest = _hex32(expected_manifest_digest, "expected_manifest_digest")
    if network != expected_network:
        raise ValueError("approval network_id does not match manifest")
    if digest != expected_digest:
        raise ValueError("approval manifest_digest does not match manifest")
    if record["approval_scope"] != _SCOPE:
        raise ValueError("approval scope mismatch")
    if record["signature_algorithm"] != "Ed25519":
        raise ValueError("unsupported approval signature algorithm")

    key_id = record["signing_key_id"]
    _hex32(key_id, "signing_key_id")
    if key_id in revoked_key_ids:
        raise ValueError("approval signing key is revoked")
    public_bytes = trusted_public_keys.get(key_id)
    if not isinstance(public_bytes, bytes) or len(public_bytes) != 32:
        raise ValueError("approval key is not present in trusted public-key configuration")
    if hashlib.sha256(public_bytes).hexdigest() != key_id:
        raise ValueError("trusted public-key identifier mismatch")

    signature_hex = record["signature"]
    if not isinstance(signature_hex, str) or len(signature_hex) != 128:
        raise ValueError("Ed25519 signature must be 128 lowercase hexadecimal characters")
    if any(c not in "0123456789abcdef" for c in signature_hex):
        raise ValueError("signature must be canonical lowercase hexadecimal")
    signature = bytes.fromhex(signature_hex)
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature, _DOMAIN + network + digest + _SCOPE.encode("utf-8")
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("genesis approval signature verification failed") from exc
    return key_id
