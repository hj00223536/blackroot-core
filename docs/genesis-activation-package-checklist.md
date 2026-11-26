# BLACKROOT genesis activation package checklist

**Status: PROPOSED REVIEW CHECKLIST ONLY. It is not a frozen protocol specification, owner approval, issuance authorization, or launch authorization.**

## Purpose

Define the evidence that must travel together when a future BLACKROOT genesis candidate is reviewed. The package is intended to make omissions, substitutions, and mismatched artifacts detectable. It does not decide consensus constants and must not be used to activate a network while any release gate remains open.

## Proposed package contents

A reviewed package should contain these public artifacts:

1. `manifest.json`: one strictly parsed, versioned genesis manifest. Its digest must be recomputed by every verifier; a supplied digest is never trusted without recomputation.
2. `approval.json`: detached owner-approval record signing the exact manifest digest, network identifier, and narrowly defined approval scope.
3. `trust-anchors.json`: separately governed public-key trust configuration, distributed and reviewed independently of the manifest and approval record. It must define key identifiers, allowed scopes, revocation state, and the approved configuration version.
4. `checksums.txt`: optional transport-integrity index for package files. It is not an authenticity mechanism and must not replace the detached signature.
5. `verification-report.md`: reproducible results identifying verifier source revision, runtime/tool versions, exact input digests, checks performed, and pass/fail outcomes.
6. `release-approval.md`: human release decision identifying the exact manifest digest, target network, reviewed commit, outstanding exceptions, approvers, and decision date.

The package must not contain private keys, seed phrases, wallet passwords, decrypted wallet backups, or any signing secret.

## Verification order

A future activation verifier must fail closed and follow the detailed [Genesis package semantic verification plan](genesis-package-semantic-verification-plan.md). At minimum, the sequence is:

1. Validate exact package membership, simple filenames, non-empty bytes, and per-file/aggregate size limits.
2. Authenticate the external digest-pin source independently, then compare every artifact against the exact pinned inventory. A checksum file inside the package is not an external trust anchor.
3. Strictly parse every adopted artifact schema, rejecting duplicate JSON keys, unknown fields, invalid types, and ambiguous encodings.
4. Recompute the manifest's version-specific canonical digest; validate network, genesis identity, coinbase serialization/txid, founder output index/value/script, supply cap, and mining schedule against independently frozen constants.
5. Validate the separately pinned trust configuration, key identifiers, scopes, key status, sequence, predecessor, and durable anti-rollback state.
6. Verify the detached approval signature over the exact network, manifest digest, and narrow scope using only an independently trusted active key.
7. Independently validate the genesis header, Merkle commitment, proof of work, timestamp, difficulty, transaction rules, and every adopted consensus rule. Any required but unsupported check blocks release.
8. Require a separately authenticated human release decision naming the exact manifest digest, network, verifier revision, and approvers.
9. Emit a deterministic evidence report containing input digests, verifier revision, runtime versions, individual check results, and explicit authorization status.
10. Only then may a separately reviewed one-time initializer be considered. The initializer must independently repeat critical checks and atomically commit the exact genesis outputs and immutable initialization evidence.

The optional `checksums.txt` file is transport-integrity metadata only; it never replaces authenticated external pins or signatures. A successful package verification is not itself permission to launch. Testnet and mainnet require separate release decisions and their own gates.

## Reproducibility and substitution controls

- Publish the manifest digest and all artifact digests in the verification report.
- Pin verifier source revisions by immutable commit hash, not branch name alone.
- Require an independent implementation to reproduce transaction, header, proof-of-work, manifest-digest, and signature results.
- Ensure the human release decision names the exact manifest digest; approval of a repository, branch, or filename alone is insufficient.
- Treat any change to the manifest, trust anchors, verifier, network constants, or approval scope as a new review candidate.
- Reject revoked, unknown, expired-if-expiry-is-adopted, or scope-incompatible signing keys.
- Keep trust-anchor rotation and recovery procedures outside the manifest so a manifest cannot authorize its own signer.
- Retain the original package and verification report as immutable release evidence.

## Open design decisions

Before this checklist can become normative, reviewers must decide:

- The exact package container format, file naming, encoding, and canonicalization rules.
- The trust-anchor configuration schema, custody, quorum (if any), revocation, rotation, and recovery.
- Whether approval records need validity windows and how clock trust is established.
- The exact human release-approval mechanism and separation of duties.
- How testnet and mainnet packages are distinguished and how cross-network substitution is prevented.
- How verification reports are signed, retained, and independently audited.

## Current repository status

The repository currently has a v2 manifest structural-validator prototype, strict parser, Python/Node.js digest fixture, and detached Ed25519 approval-verifier prototype. These components are not wired into node startup or issuance. No production trust anchor, real owner approval record, founder output, or activation package exists. The proposed checklist does not close any protocol-freeze or launch gate.

## Stop conditions

Do not create or publish a founder output, initialize a production database, expose a public endpoint, or claim BRT is issued or spendable based on this checklist. Do not claim a market price, liquidity, exchange listing, or investment return.
## Prototype inventory-audit helper

The repository now contains `src/blackroot_genesis_package_audit.py` and regression tests in `tests/test_genesis_package_audit.py`. This helper accepts an in-memory mapping of exact file names to bytes, requires the five mandatory artifacts listed above, permits only the optional `checksums.txt`, applies per-file and aggregate size limits, and compares every artifact SHA-256 against a separately supplied external pin. It rejects missing, unexpected, substituted, malformed, and non-byte artifacts, and returns a read-only digest inventory.

This is only an inventory and transport-integrity check. It does not parse or semantically validate the files, authenticate the source of the external pins, verify signatures, establish owner identity, check consensus, or authorize database initialization or release. The package container format and independent pin-distribution mechanism remain open design decisions.
