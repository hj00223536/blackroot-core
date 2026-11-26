# BLACKROOT genesis approval record specification

**Status: PROPOSAL ONLY — no owner signing key is configured, no approval signature exists, and no issuance is authorized.**

## Related governance and activation documents

This verifier proposal must be read together with the [trust-anchor governance proposal](genesis-trust-anchor-governance-proposal.md), which defines how a public key could become trusted, and the [genesis activation package checklist](genesis-activation-package-checklist.md), which separates manifest approval from release authorization. Neither linked proposal is an approved trust configuration or launch decision.

## Purpose

A manifest digest proves only that a particular byte-level manifest was presented. It does not prove who approved it. A text value such as \`approval_record: "approved"\` is not authentication and must never authorize founder issuance.

This document defines the minimum shape of a future detached approval record. It does not create keys, signatures, or a founder output.

## Proposed record

The approval record should be a separately versioned, detached document with exactly these fields:

| Field | Type | Requirement |
|---|---|---|
| \`record_version\` | integer | Exactly 1 |
| \`network_id\` | lowercase 64-character hex | Must match the manifest |
| \`manifest_digest\` | lowercase 64-character hex | Must match the verified manifest digest |
| \`approval_scope\` | string | Exactly \`genesis-founder-allocation\` |
| \`signing_key_id\` | lowercase 64-character hex | SHA-256 identifier of the approved public key bytes |
| \`signature_algorithm\` | string | Exactly \`Ed25519\` for this proposal |
| \`signature\` | lowercase hex | Detached signature over the canonical approval message |

The signature message is:

\`UTF8("BLACKROOT-GENESIS-APPROVAL-V1") || 0x00 || raw_32_byte_network_id || raw_32_byte_manifest_digest || UTF8("genesis-founder-allocation")\`

The signing key must be an explicitly approved owner-controlled public key. Its trust anchor, key identifier, activation time, revocation procedure, and replacement process must be published in a separately reviewed governance record. Never infer the trusted key from the signature itself or accept a key supplied only by the manifest.

## Verification requirements

A future issuance implementation must:

1. Verify the manifest schema and canonical digest first.
2. Load the owner public key from a separately pinned, reviewed trust configuration.
3. Recompute and compare the signing key identifier.
4. Verify the Ed25519 signature over the exact domain-separated message.
5. Reject unknown algorithms, duplicate JSON keys, unknown fields, malformed encodings, revoked keys, and network/digest/scope mismatches.
6. Require explicit human review of the displayed network, founder amount, locking script, and manifest digest before approval is signed.
7. Persist the exact approval record, trusted key identifier, and manifest digest atomically with genesis initialization.
8. On reopen, re-verify the same record and trust configuration; never silently replace or downgrade approval evidence.

A plain GitHub commit, issue comment, label, text string, or hash is not a cryptographic owner approval. Repository history can preserve evidence but is not itself the trust anchor.

## Key custody

- Generate and protect the owner signing key outside GitHub, CI, chat, and source control.
- Keep only the public trust anchor in the reviewed configuration.
- Never request or accept the private signing key, wallet private key, seed phrase, or password in chat or repository files.
- Prefer an offline signing workflow and a separately verified public-key fingerprint.
- Define recovery, rotation, compromise response, and revocation before relying on the key.

## Current implementation boundary

The repository now contains a standalone Ed25519 detached-record verifier in `src/blackroot_genesis_approval.py` and regression tests in `tests/test_genesis_approval.py`. It verifies exact record fields, network ID, manifest digest, fixed scope, algorithm, key identifier, revocation list, and signature against caller-supplied trusted raw public keys. The test key is public RFC 8032 test material only. The verifier now has a separate `verify_validated_genesis_manifest_approval()` binding helper that takes the network ID and manifest digest only from a `ValidatedGenesisManifest`, plus regression tests for valid binding and digest mismatch. It remains a separate explicit validation step: it is not automatically invoked by `validate_genesis_manifest_structure()` or any node startup/initializer. The existing manifest `approval_record` remains a text placeholder/reference. No owner trust anchor is configured, no real approval exists, and no issuance is authorized. The test suite also includes the published RFC 8032 empty-message Ed25519 verification vector, in addition to BLACKROOT-specific positive and negative cases.

## Release gate

This proposal remains OPEN until the owner explicitly approves the trust model, a real public key is pinned through a separately reviewed process, independent signature vectors pass, the detached record is integrated into a versioned manifest/initializer design, and the verifier is independently reviewed. The current verifier is a prototype requiring external review. No founder allocation or network launch may depend on this proposal alone.
