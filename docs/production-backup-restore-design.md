# Production Backup and Restore Design

**Status: DESIGN PROPOSAL ONLY — NOT IMPLEMENTED OR APPROVED FOR PRODUCTION**

This document defines the minimum safety contract for a future node backup and
restore facility. The current SQLite online-backup tests are primitive-level
tests; they do not implement this workflow.

## 1. Scope and source of truth

A production backup must be taken from a coordinated node state while the
node's exclusive data-directory lock is held by the backup coordinator. The
backup operation must use SQLite's online backup API against the live database;
it must not copy only the main `.sqlite` file while WAL mode is active.

The backup must be a self-contained artifact in a new, private staging
directory. It must not include live lock files, open file descriptors, sockets,
or transient process state. Any future node component stored outside the
single coordinated database must be explicitly enumerated and backed up under
a documented consistency protocol; silently omitting a required artifact is a
hard failure.

## 2. Backup manifest

A canonical, versioned manifest must bind at least:
- format and manifest schema versions;
- network identifier and exact Genesis block hash;
- protocol/database schema versions;
- backup creation time and monotonic sequence/freshness metadata;
- database artifact name, byte length, and cryptographic digest;
- expected active tip height and block hash;
- required artifact inventory;
- backup tool/build identity and supported compatibility range.

The manifest must be authenticated by an independently governed signing
authority. A checksum alone detects accidental corruption but does not prove
origin or freshness. The authority, key custody, rotation, revocation, and
external pin distribution are separate unresolved governance decisions.

## 3. Backup algorithm requirements

1. Acquire and retain the node data-directory lock for the full operation.
2. Refuse backup if a state transaction is active or recovery reconciliation
   has not completed.
3. Create a new staging directory with restrictive permissions; refuse
   symlinked, hard-linked, or pre-existing destination artifacts.
4. Use SQLite's online backup API and bounded retry/progress handling.
5. Close the destination connection, fsync the artifact, and verify it using
   SQLite integrity and foreign-key checks plus application-level chain/UTXO
   checks on an isolated read-only validation copy.
6. Re-read and bind the expected network, Genesis, schema, and chain tip.
7. Generate and authenticate the canonical manifest only after all checks
   succeed.
8. fsync the staging directory and atomically publish it without replacing an
   existing backup. A failed operation leaves no artifact advertised as valid.
9. Preserve an audit record of outcome and exact manifest digest.

## 4. Restore algorithm requirements

Restore must never overwrite the active data directory in place.

1. Verify the manifest signature against externally authenticated trust
   configuration and enforce anti-rollback freshness before trusting artifact
   metadata.
2. Verify exact file inventory, sizes, and cryptographic digests.
3. Restore into a fresh, private, isolated directory.
4. Open the candidate database in a validation-only process; run SQLite
   integrity checks, schema checks, network/Genesis binding, complete
   deterministic chain/UTXO replay, and trust-state verification.
5. Compare the candidate tip and monotonic policy sequence against an
   independently stored freshness anchor. A locally restored database or
   manifest cannot authenticate its own freshness.
6. Run all startup preflight checks without serving peers, mining, accepting
   transactions, or exposing spend-capable wallet keys.
7. Require explicit operator authorization for activation, then switch the
   configured data-directory reference atomically using a platform-reviewed
   procedure. Keep the prior directory untouched and recoverable.
8. On any error, quarantine the candidate and leave the active directory and
   its configuration unchanged.

## 5. Required adversarial and fault tests

- WAL frames committed but not checkpointed are present in the backup.
- Concurrent read activity and bounded write activity produce a consistent
  SQLite snapshot or a clean, bounded failure.
- Process termination during backup never publishes a partial artifact.
- Disk-full, permission, fsync, rename, and manifest-signing failures fail
  closed.
- Modified, truncated, swapped, missing, and extra artifacts are rejected.
- Wrong network, Genesis, schema, or chain tip is rejected.
- Valid but stale backups are rejected by an external anti-rollback anchor.
- Restore interruption at every phase leaves the active directory unchanged.
- Symlink, hard-link, path alias, and pre-existing destination attacks are
  rejected.
- Full replay and trust validation failures quarantine the candidate.
- Recovery is repeatable and idempotent after process crashes.

## 6. Explicit non-goals and current limitations

The current repository does not yet implement a production backup command,
canonical authenticated backup manifest, external freshness authority,
restore staging/activation protocol, complete deterministic UTXO replay, or
production recovery runbook. The existing `tests/test_sqlite_online_backup.py`
covers SQLite backup behavior and selected application-level checks only.

This design does not authorize a Mainnet launch, trust-state activation, or
founder issuance. Implementation requires separate review of filesystem
semantics, trust governance, key management, full replay, fault injection,
and independent security assessment.
