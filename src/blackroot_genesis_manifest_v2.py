"""Strict structural validator for the proposed detached-approval Genesis v2 format.

This is a validation prototype only. It does not authorize issuance, verify
owner approval, validate proof of work, or write database state.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping

from .blackroot_blocks import is_coinbase
from .blackroot_genesis_manifest import (
    ValidatedGenesisManifest,
    _jcs_encode,
    _require_lower_hex,
    _require_uint,
    parse_genesis_manifest_json,
)
from .blackroot_transactions import Transaction

_DOMAIN_SEPARATOR_V2 = b"BLACKROOT-GENESIS-MANIFEST-V2\x00"
_REQUIRED_FIELDS_V2 = frozenset({
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
})


def calculate_genesis_manifest_v2_digest(manifest: Mapping[str, object]) -> str:
    """Hash canonical v2 fields, excluding the self-referential digest."""
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    payload = dict(manifest)
    payload.pop("manifest_digest", None)
    return hashlib.sha256(_DOMAIN_SEPARATOR_V2 + _jcs_encode(payload).encode("utf-8")).hexdigest()


def validate_genesis_manifest_v2(
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
    """Validate v2 structure against independently frozen caller constants.

    Returned type is shared with the detached-approval binding prototype.
    The empty approval_record field is deliberately not an approval and is
    never read by the binding helper.
    """
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    if set(manifest) != _REQUIRED_FIELDS_V2:
        missing = sorted(_REQUIRED_FIELDS_V2 - set(manifest))
        unknown = sorted(set(manifest) - _REQUIRED_FIELDS_V2)
        raise ValueError(f"v2 manifest fields mismatch (missing={missing}, unknown={unknown})")
    if _require_uint(manifest["manifest_version"], "manifest_version") != 2:
        raise ValueError("unsupported manifest_version for v2")

    digest = _require_lower_hex(manifest["manifest_digest"], "manifest_digest", exact_length=64)
    if digest != calculate_genesis_manifest_v2_digest(manifest):
        raise ValueError("manifest_digest does not match canonical v2 contents")

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
        approval_record="",
    )
