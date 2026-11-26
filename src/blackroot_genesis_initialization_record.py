"""Pure validation for a proposed immutable genesis initialization record.

This module is deliberately non-operational: it performs no database writes,
does not create an initializer capability, and does not authorize issuance.
The record is an integrity snapshot derived from an already validated v2
manifest; owner approval and trust-anchor governance remain separate gates.
"""
from __future__ import annotations

from collections.abc import Mapping

from .blackroot_genesis_manifest import ValidatedGenesisManifest

_RECORD_VERSION = 1
_REQUIRED_FIELDS = frozenset({
    "record_version",
    "initialization_complete",
    "network_id",
    "genesis_block_hash",
    "manifest_digest",
    "genesis_coinbase_txid",
    "genesis_coinbase_tx",
    "founder_output_index",
    "founder_amount_sats",
    "founder_script_pub_key",
    "total_supply_cap_sats",
})


def build_genesis_initialization_record(
    validated_manifest: ValidatedGenesisManifest,
) -> dict[str, object]:
    """Build a deterministic integrity record; this does not initialize state."""
    if not isinstance(validated_manifest, ValidatedGenesisManifest):
        raise TypeError("validated_manifest must be a ValidatedGenesisManifest")
    tx = validated_manifest.coinbase
    return {
        "record_version": _RECORD_VERSION,
        "initialization_complete": True,
        "network_id": validated_manifest.network_id,
        "genesis_block_hash": validated_manifest.genesis_block_hash,
        "manifest_digest": validated_manifest.manifest_digest,
        "genesis_coinbase_txid": tx.display_txid,
        "genesis_coinbase_tx": tx.serialize().hex(),
        "founder_output_index": validated_manifest.founder_output_index,
        "founder_amount_sats": validated_manifest.founder_amount_sats,
        "founder_script_pub_key": validated_manifest.founder_script_pub_key.hex(),
        "total_supply_cap_sats": validated_manifest.total_supply_cap_sats,
    }


def validate_genesis_initialization_record(
    record: Mapping[str, object],
    validated_manifest: ValidatedGenesisManifest,
) -> None:
    """Fail closed unless every stored field exactly matches the validated manifest.

    This validates record integrity only. It is not a signature check, does not
    prove database atomicity or immutability, and must not be used as an
    issuance authorization or as a substitute for startup/consensus checks.
    """
    if not isinstance(validated_manifest, ValidatedGenesisManifest):
        raise TypeError("validated_manifest must be a ValidatedGenesisManifest")
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    if set(record) != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS - set(record))
        unknown = sorted(set(record) - _REQUIRED_FIELDS)
        raise ValueError(f"initialization record fields mismatch (missing={missing}, unknown={unknown})")

    expected = build_genesis_initialization_record(validated_manifest)
    for field in sorted(_REQUIRED_FIELDS):
        value = record[field]
        expected_value = expected[field]
        if type(value) is not type(expected_value) or value != expected_value:
            raise ValueError(f"initialization record {field} does not match validated genesis manifest")
