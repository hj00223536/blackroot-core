"""One-shot, verification-only composition of proposed Genesis authorization evidence.

This module joins the existing manifest, trust-anchor and detached-signature
validators. It does not establish the provenance of caller-supplied pins,
write persistent state, or authorize issuance.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blackroot_genesis_manifest_v2 import (
    parse_genesis_manifest_v2_json,
    validate_genesis_manifest_v2,
)
from .blackroot_genesis_trust import (
    parse_trust_configuration_json,
    validate_trust_configuration,
    verify_approval_with_validated_trust,
)


@dataclass(frozen=True)
class VerifiedGenesisAuthorization:
    """Immutable result of successful evidence verification; not an issuance token."""

    manifest_digest: str
    network_id: str
    genesis_block_hash: str
    trust_config_digest: str
    trust_config_sequence: int
    approving_key_id: str


def verify_genesis_authorization_package(
    manifest_json: str,
    approval_json: str,
    trust_configuration_json: str,
    *,
    expected_network_id: str,
    expected_genesis_block_hash: str,
    expected_genesis_txid: str,
    expected_founder_amount_sats: int,
    expected_total_supply_cap_sats: int,
    expected_mining_schedule_id: str,
    maximum_mining_issuance_sats: int,
    pinned_trust_config_digest: str,
    expected_trust_config_sequence: int,
    expected_previous_trust_config_digest: str | None,
) -> VerifiedGenesisAuthorization:
    """Verify manifest structure, pinned trust config, and detached Ed25519 approval.

    All expected chain constants and trust pins must be delivered by an
    independently reviewed release process. A successful result only means
    these three evidence documents agree with those caller-supplied values.
    """
    manifest_data = parse_genesis_manifest_v2_json(manifest_json)
    validated_manifest = validate_genesis_manifest_v2(
        manifest_data,
        expected_network_id=expected_network_id,
        expected_genesis_block_hash=expected_genesis_block_hash,
        expected_genesis_txid=expected_genesis_txid,
        expected_founder_amount_sats=expected_founder_amount_sats,
        expected_total_supply_cap_sats=expected_total_supply_cap_sats,
        expected_mining_schedule_id=expected_mining_schedule_id,
        maximum_mining_issuance_sats=maximum_mining_issuance_sats,
    )

    trust_data = parse_trust_configuration_json(trust_configuration_json)
    validated_trust = validate_trust_configuration(
        trust_data,
        expected_network_id=validated_manifest.network_id,
        pinned_config_digest=pinned_trust_config_digest,
        expected_sequence=expected_trust_config_sequence,
        expected_previous_config_digest=expected_previous_trust_config_digest,
    )
    approving_key_id = verify_approval_with_validated_trust(
        validated_manifest,
        approval_json,
        validated_trust,
    )
    return VerifiedGenesisAuthorization(
        manifest_digest=validated_manifest.manifest_digest,
        network_id=validated_manifest.network_id,
        genesis_block_hash=validated_manifest.genesis_block_hash,
        trust_config_digest=validated_trust.config_digest,
        trust_config_sequence=validated_trust.sequence,
        approving_key_id=approving_key_id,
    )
