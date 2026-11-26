# Genesis package semantic verification plan

**Status: IMPLEMENTATION PLAN ONLY. No package is approved, no owner approval exists, and no issuance or release is authorized.**

## Scope

The package inventory helper in `src/blackroot_genesis_package_audit.py` checks exact filenames, byte types, non-empty files, size limits, and externally supplied SHA-256 pins. It is a transport/inventory boundary only. It does not establish who supplied the package, parse any artifact, validate cross-file consistency, or authorize activation.

This plan records the required semantic-verification sequence without inventing unresolved schemas or treating prototypes as production controls.

## Required inputs and trust boundary

A future verifier must receive:

- The exact package artifact bytes.
- An independently authenticated pin set covering the exact artifact inventory.
- Frozen, independently reviewed network and consensus constants.
- A trust configuration obtained and pinned independently of the package.
- Durable anti-rollback state for the trust configuration.
- An explicit target network and verifier version.

No trust key, network constant, expected digest, or release decision may become trusted merely because it appears inside the package being checked. Private keys and seed phrases are never verifier inputs.

## Verification stages

| Stage | Required checks | Fail-closed condition |
|---|---|---|
| 1. Inventory | Exact required/optional names, unique names, simple filenames, non-empty bytes, per-file and aggregate limits | Missing, extra, malformed, or oversized artifact |
| 2. External pins | Authenticate pin provenance out-of-band; compare every artifact digest to the exact pinned inventory | Missing, substituted, malformed, or unauthenticated pin |
| 3. Strict parsing | Parse each adopted schema with duplicate-key rejection, no floats where prohibited, exact field sets, bounded values, and canonical encodings | Unknown fields, duplicate keys, invalid types, or ambiguous encoding |
| 4. Manifest | Recompute version-specific canonical digest; validate network, genesis identity, coinbase bytes/txid, founder output index/value/script, supply cap, and mining schedule against frozen constants | Any digest, field, or constant mismatch |
| 5. Trust configuration | Validate schema, network, key IDs, scopes, status, sequence, predecessor, independent pin, and durable anti-rollback state | Unknown/revoked key, rollback, unpinned config, or invalid governance state |
| 6. Owner approval | Verify detached signature over exact network, manifest digest, and narrow scope using only the independently trusted active key | Signature, key, scope, network, or digest mismatch |
| 7. Consensus evidence | Independently validate genesis header, Merkle commitment, proof of work, timestamp, difficulty, transaction rules, and all adopted consensus rules | Any unimplemented or failed consensus rule |
| 8. Human release decision | Verify a separately authenticated release decision naming the exact manifest digest, network, verifier revision, and approvers | Missing approval, digest/network mismatch, or unresolved exception |
| 9. Evidence output | Emit deterministic report with input digests, verifier revision, runtime versions, each check result, and explicit authorization status | Incomplete or internally inconsistent report |

A successful semantic verification report is evidence of checks performed, not a launch command. A distinct, reviewed one-time initializer must repeat critical checks and atomically persist exact genesis outputs and immutable initialization evidence. No network-facing route may mint or invoke that capability.

## Schema decisions required before implementation

The following are intentionally unresolved and must be approved before code treats them as normative:

1. The package container and canonical file encoding.
2. The authoritative external pin publication and authentication method.
3. The final v2 manifest schema and frozen network/genesis/mining constants.
4. The trust configuration governance model, including quorum/separation of duties, key rotation, revocation, recovery, and durable anti-rollback storage.
5. The exact release-approval format and authentication method.
6. The independent consensus implementation and review evidence.
7. The immutable initialization-record format and atomic database transaction boundary.

Do not silently choose defaults for these decisions in an implementation.

## Required test matrix

Before any semantic verifier can be considered reviewable, tests must cover:

- Duplicate JSON keys, invalid UTF-8, floats, invalid constants, unknown fields, wrong field types, and boundary integer values.
- Artifact substitution, package omission/addition, path-like filenames, empty artifacts, and per-file/aggregate size boundaries.
- Manifest digest, coinbase serialization, txid, Merkle root, founder output index/value/script, supply arithmetic, and network substitution.
- Trust key identifier mismatch, unknown/revoked/inactive keys, scope escalation, signature corruption, sequence rollback, predecessor substitution, and trust-file replacement.
- Release approval bound to the exact manifest digest and network, including replay against another candidate.
- Consensus failures and unsupported consensus checks; any unsupported required check must block release.
- Deterministic evidence reports and explicit negative assertions that verification alone does not authorize release or issuance.
- Initializer crash/fault injection, duplicate invocation, database rollback, and post-initialization tampering — only after the initializer design has been independently reviewed.

## Existing approval-verifier regression coverage

The standalone approval verifier already has focused negative tests in `tests/test_genesis_approval.py` for replay against a different manifest digest, cross-network substitution, scope and algorithm changes, unknown/revoked keys, key-ID mismatch, invalid signatures, non-canonical signature encoding, duplicate JSON keys, floating-point values, and non-object JSON roots. The validated-manifest binding helper is also tested to reject a detached record whose digest differs from the validated manifest.

These tests demonstrate behavior of the isolated approval-verifier prototype only. They do not prove trust-anchor provenance, durable revocation or anti-rollback, integration with package parsing, consensus validation, release authorization, or safe issuance. The semantic verifier remains an unimplemented integration gate.

## Current repository status

Existing components are prototypes: v2 manifest structural validation and strict parsing, detached Ed25519 approval verification, trust-configuration validation, a deterministic evidence report, and an inventory-only package audit. They are not an integrated semantic package verifier. The inventory audit does not authenticate its external pins. Trust-anchor sourcing and durable anti-rollback state are not implemented. The v2 manifest is not frozen. The evidence report deliberately records authorization as `not-authorized`; it does not validate full consensus or initialize a database.

## Stop conditions

Until all required schemas, independent trust sources, consensus rules, and release controls are reviewed and implemented, do not create a founder output, configure a production owner key, initialize production issuance, expose a public network endpoint, or claim that BRT is issued, spendable, priced, liquid, or listed.
