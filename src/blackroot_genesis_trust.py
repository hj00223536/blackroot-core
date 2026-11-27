"""Fail-closed parser for a proposed, externally pinned genesis trust configuration.

This prototype validates data against caller-supplied release-policy pins. It
does not establish owner identity, provide secure storage, or authorize issuance.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .blackroot_genesis_manifest import (
    _MAX_SAFE_INTEGER,
    _jcs_encode,
    parse_genesis_manifest_json,
)

_DOMAIN = b"BLACKROOT-TRUST-CONFIG-V1\x00"
_FIELDS = frozenset({
    "config_version", "network_id", "sequence", "previous_config_digest",
    "keys", "config_digest",
})
_KEY_FIELDS = frozenset({"key_id", "public_key", "scopes", "status"})
_SCOPE = "genesis-founder-allocation"


@dataclass(frozen=True)
class ValidatedTrustKey:
    key_id: str
    public_key: bytes
    scopes: frozenset[str]
    status: str


@dataclass(frozen=True)
class ValidatedTrustConfiguration:
    network_id: str
    sequence: int
    previous_config_digest: str | None
    config_digest: str
    keys: Mapping[str, ValidatedTrustKey]


def _hex(value: object, field: str, length: int) -> str:
    if not isinstance(value, str) or len(value) != length:
        raise ValueError(f"{field} must be {length} lowercase hexadecimal characters")
    if any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be canonical lowercase hexadecimal")
    return value


def _digest_payload(config: Mapping[str, object]) -> bytes:
    payload = dict(config)
    payload.pop("config_digest", None)
    return _jcs_encode(payload).encode("utf-8")


def calculate_trust_configuration_digest(config: Mapping[str, object]) -> str:
    """Calculate the domain-separated digest, excluding config_digest itself."""
    if not isinstance(config, Mapping):
        raise TypeError("trust configuration must be a mapping")
    return hashlib.sha256(_DOMAIN + _digest_payload(config)).hexdigest()


def validate_trust_configuration(
    config: Mapping[str, object],
    *,
    expected_network_id: str,
    pinned_config_digest: str,
    expected_sequence: int,
    expected_previous_config_digest: str | None,
) -> ValidatedTrustConfiguration:
    """Validate a trust config against pins supplied outside the package.

    The pins must come from an independently reviewed release policy. This
    function cannot authenticate their provenance and never chooses defaults.
    """
    if not isinstance(config, Mapping):
        raise ValueError("trust configuration fields mismatch")
    # Snapshot the top-level mapping and its mutable nested key/scope
    # collections before validation so one call observes one stable input.
    config_snapshot = dict(config)
    raw_keys = config_snapshot.get("keys")
    if isinstance(raw_keys, list):
        copied_keys = []
        for entry in raw_keys:
            if isinstance(entry, Mapping):
                entry_snapshot = dict(entry)
                scopes_snapshot = entry_snapshot.get("scopes")
                if isinstance(scopes_snapshot, list):
                    entry_snapshot["scopes"] = list(scopes_snapshot)
                copied_keys.append(entry_snapshot)
            else:
                copied_keys.append(entry)
        config_snapshot["keys"] = copied_keys
    if set(config_snapshot) != _FIELDS:
        raise ValueError("trust configuration fields mismatch")
    if type(config_snapshot["config_version"]) is not int or config_snapshot["config_version"] != 1:
        raise ValueError("unsupported trust configuration version")
    network_id = _hex(config_snapshot["network_id"], "network_id", 64)
    expected_network = _hex(expected_network_id, "expected_network_id", 64)
    digest = _hex(config_snapshot["config_digest"], "config_digest", 64)
    pinned_digest = _hex(pinned_config_digest, "pinned_config_digest", 64)
    if network_id != expected_network:
        raise ValueError("trust configuration network mismatch")
    sequence = config_snapshot["sequence"]
    if type(sequence) is not int or sequence < 1 or sequence > _MAX_SAFE_INTEGER:
        raise ValueError("trust configuration sequence must be a positive safe integer")
    if type(expected_sequence) is not int or expected_sequence < 1:
        raise ValueError("expected_sequence must be a positive integer")
    if sequence != expected_sequence:
        raise ValueError("trust configuration sequence does not match pinned sequence")

    previous = config_snapshot["previous_config_digest"]
    if expected_sequence == 1:
        if expected_previous_config_digest is not None or previous is not None:
            raise ValueError("initial trust configuration must not name a predecessor")
    else:
        if expected_previous_config_digest is None:
            raise ValueError("later trust configurations require a pinned predecessor")
        expected_previous = _hex(
            expected_previous_config_digest, "expected_previous_config_digest", 64
        )
        previous = _hex(previous, "previous_config_digest", 64)
        if previous != expected_previous:
            raise ValueError("trust configuration predecessor mismatch")

    if not isinstance(config_snapshot["keys"], list) or not config_snapshot["keys"]:
        raise ValueError("trust configuration keys must be a non-empty array")
    keys: dict[str, ValidatedTrustKey] = {}
    public_keys: set[bytes] = set()
    for entry in config_snapshot["keys"]:
        if not isinstance(entry, Mapping) or set(entry) != _KEY_FIELDS:
            raise ValueError("trust key fields mismatch")
        public_hex = _hex(entry["public_key"], "public_key", 64)
        public_bytes = bytes.fromhex(public_hex)
        key_id = _hex(entry["key_id"], "key_id", 64)
        if hashlib.sha256(public_bytes).hexdigest() != key_id:
            raise ValueError("trust key identifier mismatch")
        if key_id in keys or public_bytes in public_keys:
            raise ValueError("duplicate trust key identifier or public key")
        scopes = entry["scopes"]
        if (not isinstance(scopes, list) or not scopes
                or any(not isinstance(scope, str) for scope in scopes)
                or len(set(scopes)) != len(scopes)):
            raise ValueError("trust key scopes must be unique non-empty strings")
        if any(scope != _SCOPE for scope in scopes):
            raise ValueError("unsupported or overbroad trust key scope")
        status = entry["status"]
        if status not in ("active", "revoked"):
            raise ValueError("trust key status must be active or revoked")
        keys[key_id] = ValidatedTrustKey(
            key_id=key_id, public_key=public_bytes,
            scopes=frozenset(scopes), status=status,
        )
        public_keys.add(public_bytes)

    calculated = calculate_trust_configuration_digest(config_snapshot)
    if digest != calculated:
        raise ValueError("trust configuration digest mismatch")
    if digest != pinned_digest:
        raise ValueError("trust configuration digest does not match external pin")
    return ValidatedTrustConfiguration(
        network_id=network_id, sequence=sequence,
        previous_config_digest=previous, config_digest=digest, keys=MappingProxyType(keys),
    )


def parse_trust_configuration_json(raw: str) -> dict[str, object]:
    """Strict JSON parser rejecting duplicate keys, floats and non-object roots."""
    return parse_genesis_manifest_json(raw)

def verify_approval_with_validated_trust(
    validated_manifest,
    approval_record_json: str,
    trust_configuration: ValidatedTrustConfiguration,
) -> str:
    """Verify manifest approval using only active keys from validated trust data.

    The trust configuration must already have passed validation against
    independently supplied network, digest, sequence, and predecessor pins.
    This helper does not authenticate those pins or authorize issuance.
    """
    from .blackroot_genesis_manifest import ValidatedGenesisManifest
    from .blackroot_genesis_approval import verify_validated_genesis_manifest_approval

    if not isinstance(validated_manifest, ValidatedGenesisManifest):
        raise TypeError("validated_manifest must be a ValidatedGenesisManifest")
    if not isinstance(trust_configuration, ValidatedTrustConfiguration):
        raise TypeError("trust_configuration must be a ValidatedTrustConfiguration")
    if trust_configuration.network_id != validated_manifest.network_id:
        raise ValueError("trust configuration network does not match validated manifest")
    active = {
        key_id: key.public_key
        for key_id, key in trust_configuration.keys.items()
        if key.status == "active" and _SCOPE in key.scopes
    }
    revoked = frozenset(
        key_id for key_id, key in trust_configuration.keys.items()
        if key.status == "revoked"
    )
    return verify_validated_genesis_manifest_approval(
        validated_manifest,
        approval_record_json,
        trusted_public_keys=active,
        revoked_key_ids=revoked,
    )
