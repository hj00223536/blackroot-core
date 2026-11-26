"""Fail-closed structural checks for a proposed public genesis manifest.

This module is NOT an issuance initializer or an approval/authentication system.
It calculates the restricted JCS digest, but does not authenticate approval,
freeze network constants, or write database state.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .blackroot_blocks import is_coinbase
from .blackroot_transactions import Transaction



_DOMAIN_SEPARATOR = b"BLACKROOT-GENESIS-MANIFEST-V1\x00"
_MAX_SAFE_INTEGER = (1 << 53) - 1


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def parse_genesis_manifest_json(raw: str) -> dict[str, object]:
    """Parse strict JSON text, rejecting duplicate keys and floating-point values."""
    if not isinstance(raw, str):
        raise TypeError("manifest JSON must be text")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=lambda _value: (_ for _ in ()).throw(ValueError("floating-point values are forbidden")),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("manifest JSON is invalid") from exc
    if not isinstance(parsed, dict):
        raise ValueError("manifest JSON root must be an object")
    return parsed


def _jcs_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _jcs_encode(value: object) -> str:
    """Encode the manifest's restricted JCS data model (no floating-point numbers)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("manifest integer exceeds the interoperable JCS safe range")
        return str(value)
    if isinstance(value, float):
        raise ValueError("floating-point values are forbidden in the manifest")
    if isinstance(value, str):
        return _jcs_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_jcs_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("manifest object keys must be strings")
        keys = sorted(value, key=lambda item: item.encode("utf-16-be"))
        return "{" + ",".join(_jcs_string(key) + ":" + _jcs_encode(value[key]) for key in keys) + "}"
    raise ValueError(f"unsupported manifest JSON value type: {type(value).__name__}")


def canonicalize_genesis_manifest(manifest: Mapping[str, object]) -> bytes:
    """Return UTF-8 JCS bytes after excluding the self-referential digest."""
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    payload = dict(manifest)
    payload.pop("manifest_digest", None)
    return _jcs_encode(payload).encode("utf-8")


def calculate_genesis_manifest_digest(manifest: Mapping[str, object]) -> str:
    """Calculate the domain-separated SHA-256 digest of a manifest."""
    return hashlib.sha256(_DOMAIN_SEPARATOR + canonicalize_genesis_manifest(manifest)).hexdigest()


_REQUIRED_FIELDS = frozenset({
    "manifest_version",
    "manifest_digest",
    "network_id",
    "genesis_block_hash",
    "genesis_coinbase_tx",
    "founder_output_index",
    "founder_amount_sats",
    "founder_script_pub_key",
    "total_supply_cap_sats",
    "mining_schedule_id",
    "approval_record",
})


@dataclass(frozen=True)
class ValidatedGenesisManifest:
    """Decoded public data after structural checks; not issuance authorization."""

    manifest_digest: str
    network_id: str
    genesis_block_hash: str
    coinbase: Transaction
    founder_output_index: int
    founder_amount_sats: int
    founder_script_pub_key: bytes
    total_supply_cap_sats: int
    mining_schedule_id: str
    approval_record: str


def _require_lower_hex(value: object, field: str, *, exact_length: int | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty lowercase hex string")
    if len(value) % 2 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be canonical lowercase hexadecimal")
    if exact_length is not None and len(value) != exact_length:
        raise ValueError(f"{field} must contain exactly {exact_length} hex characters")
    return value


def _require_uint(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > _MAX_SAFE_INTEGER:
        raise ValueError(f"{field} must be a non-negative safe integer")
    return value


def validate_genesis_manifest_structure(
    manifest: Mapping[str, object],
    *,
    expected_network_id: str,
    expected_genesis_block_hash: str,
    expected_genesis_txid: str,
    expected_founder_amount_sats: int,
    expected_total_supply_cap_sats: int,
    expected_mining_schedule_id: str,
    maximum_mining_issuance_sats: int,
) -> ValidatedGenesisManifest:
    """Validate schema and transaction bytes against caller-supplied frozen constants.

    The expected values must come from independently reviewed, frozen network
    configuration. This function does not authenticate that configuration,
    authenticate approval_record, validate a genesis header/Merkle commitment,
    or authorize a database write.
    """
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    if set(manifest) != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS - set(manifest))
        unknown = sorted(set(manifest) - _REQUIRED_FIELDS)
        raise ValueError(f"manifest fields mismatch (missing={missing}, unknown={unknown})")
    if _require_uint(manifest["manifest_version"], "manifest_version") != 1:
        raise ValueError("unsupported manifest_version")

    digest = _require_lower_hex(manifest["manifest_digest"], "manifest_digest", exact_length=64)
    calculated_digest = calculate_genesis_manifest_digest(manifest)
    if digest != calculated_digest:
        raise ValueError("manifest_digest does not match canonical manifest contents")
    network_id = _require_lower_hex(manifest["network_id"], "network_id", exact_length=64)
    block_hash = _require_lower_hex(manifest["genesis_block_hash"], "genesis_block_hash", exact_length=64)
    tx_hex = _require_lower_hex(manifest["genesis_coinbase_tx"], "genesis_coinbase_tx")
    schedule_id = _require_lower_hex(manifest["mining_schedule_id"], "mining_schedule_id", exact_length=64)
    script_hex = _require_lower_hex(manifest["founder_script_pub_key"], "founder_script_pub_key")

    if network_id != expected_network_id:
        raise ValueError("manifest network_id does not match frozen configuration")
    if block_hash != expected_genesis_block_hash:
        raise ValueError("manifest genesis_block_hash does not match frozen configuration")
    if schedule_id != expected_mining_schedule_id:
        raise ValueError("manifest mining_schedule_id does not match frozen configuration")

    tx_bytes = bytes.fromhex(tx_hex)
    coinbase = Transaction.deserialize(tx_bytes)
    if coinbase.serialize() != tx_bytes:
        raise ValueError("genesis coinbase transaction is not canonically serialized")
    if not is_coinbase(coinbase):
        raise ValueError("genesis transaction is not a coinbase transaction")
    if coinbase.display_txid != expected_genesis_txid:
        raise ValueError("genesis coinbase txid does not match frozen configuration")

    output_index = _require_uint(manifest["founder_output_index"], "founder_output_index")
    if output_index >= len(coinbase.outputs):
        raise ValueError("founder_output_index is outside the coinbase outputs")
    amount = _require_uint(manifest["founder_amount_sats"], "founder_amount_sats")
    if amount != expected_founder_amount_sats:
        raise ValueError("founder amount does not match frozen monetary policy")
    script = bytes.fromhex(script_hex)
    output = coinbase.outputs[output_index]
    if output.value != amount or output.script_pubkey != script:
        raise ValueError("founder output value or locking script does not match manifest")

    supply_cap = _require_uint(manifest["total_supply_cap_sats"], "total_supply_cap_sats")
    if supply_cap != expected_total_supply_cap_sats:
        raise ValueError("manifest supply cap does not match frozen monetary policy")
    mining_max = _require_uint(maximum_mining_issuance_sats, "maximum_mining_issuance_sats")
    if amount + mining_max != supply_cap:
        raise ValueError("founder allocation plus maximum mining issuance must equal supply cap")

    approval_record = manifest["approval_record"]
    if not isinstance(approval_record, str) or not approval_record.strip() or len(approval_record) > 512:
        raise ValueError("approval_record must be a non-empty reviewed-record reference")

    return ValidatedGenesisManifest(
        manifest_digest=digest,
        network_id=network_id,
        genesis_block_hash=block_hash,
        coinbase=coinbase,
        founder_output_index=output_index,
        founder_amount_sats=amount,
        founder_script_pub_key=script,
        total_supply_cap_sats=supply_cap,
        mining_schedule_id=schedule_id,
        approval_record=approval_record,
    )
