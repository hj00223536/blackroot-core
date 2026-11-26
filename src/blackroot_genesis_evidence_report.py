"""Deterministic evidence report for proposed BLACKROOT genesis activation.

A successful report means only that supplied manifest, trust configuration and
detached approval evidence passed their validators. It is not a release decision,
consensus validation, owner-identity proof, or issuance authorization.
"""
from __future__ import annotations

import json

from .blackroot_genesis_approval import verify_validated_genesis_manifest_approval
from .blackroot_genesis_manifest import ValidatedGenesisManifest
from .blackroot_genesis_trust import (
    ValidatedTrustConfiguration,
    verify_approval_with_validated_trust,
)


def build_genesis_evidence_report(
    validated_manifest: ValidatedGenesisManifest,
    approval_record_json: str,
    validated_trust: ValidatedTrustConfiguration,
) -> dict[str, object]:
    """Return a deterministic, non-authorizing summary of validated evidence."""
    if not isinstance(validated_manifest, ValidatedGenesisManifest):
        raise TypeError("validated_manifest must be a ValidatedGenesisManifest")
    if not isinstance(validated_trust, ValidatedTrustConfiguration):
        raise TypeError("validated_trust must be a ValidatedTrustConfiguration")
    key_id = verify_approval_with_validated_trust(
        validated_manifest, approval_record_json, validated_trust
    )
    return {
        "report_version": 1,
        "report_kind": "genesis-evidence-verification",
        "verification_result": "passed",
        "authorization_result": "not-authorized",
        "network_id": validated_manifest.network_id,
        "manifest_digest": validated_manifest.manifest_digest,
        "genesis_block_hash": validated_manifest.genesis_block_hash,
        "trust_config_digest": validated_trust.config_digest,
        "trust_config_sequence": validated_trust.sequence,
        "approval_key_id": key_id,
        "approval_scope": "genesis-founder-allocation",
        "consensus_validation_performed": False,
        "database_initialization_performed": False,
        "issuance_performed": False,
        "public_release_authorized": False,
    }


def serialize_genesis_evidence_report(report: dict[str, object]) -> str:
    """Serialize a report deterministically; does not accept arbitrary objects."""
    if not isinstance(report, dict):
        raise TypeError("report must be a dictionary")
    return json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
