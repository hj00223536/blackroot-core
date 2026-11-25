# Legacy SQLite storage migration plan

**Status: partial tooling only. Read-only preflight and exclusive SQLite backup snapshots are implemented; table import, domain validation across snapshots, and final publication are not implemented. No existing database has been modified.**

## Purpose and safety invariants

The legacy node-state layout uses three independent SQLite files: header store, UTXO store, and recovery journal. Coordinated mode expects all participating tables in one node-owned database. A migration must never merge live files in place or overwrite a destination.

The future utility must satisfy all of these invariants:

1. Open source databases read-only and never mutate, checkpoint, rename, or delete them.
2. Require three explicitly supplied, distinct source paths and a destination path that does not exist (or is an explicitly empty directory reserved for staging).
3. Refuse source aliases, symlinks resolving to the same file, destination/source overlap, and active WAL/SHM ambiguity unless a consistent SQLite backup snapshot is obtained.
4. Create SQLite-consistent snapshots using the SQLite backup API, including committed WAL content; do not copy only the main database file while a writer may be active.
5. Perform all imports into a new temporary database in the destination directory. Never publish a partially imported file.
6. Run integrity, foreign-key, schema-version, domain consistency, and replay validations before publication.
7. Publish with an atomic same-filesystem rename only after all validations and a final close/reopen verification succeed. Preserve snapshots and source files for rollback/audit.
8. On any failure, remove only the utility-owned temporary output and leave all source files and any pre-existing destination untouched.

## Known schema inputs (must be checked against actual files)

- Header database: `header_metadata` and `headers`; schema version 1. Metadata includes the configured proof-of-work limit and genesis hash. Header rows must be replayed against the supplied genesis and validated parameters.
- UTXO database: `metadata`, `utxos`, `blocks`, `block_transactions`, `block_bodies`, `block_undo_spent`, and `block_undo_created`; current schema version 2. The current implementation explicitly refuses unsafe migration of non-empty schema-v1 state without a verified reindex.
- Recovery journal database: `recovery_intent`. A non-empty pending intent must be reconciled against the UTXO tip before migration; the utility must not silently discard it.

These names are a source-code inventory, not proof that any particular user's files have these schemas. Runtime schema inspection is mandatory.

## Implemented safety primitives

- `inspect_legacy_node_databases(...)` opens the three legacy inputs read-only and checks required tables, known schema versions, SQLite integrity, foreign keys, path aliases, and a clean recovery journal. It does not prove consensus or full domain consistency.
  It also reports deterministic `sqlite_master` DDL plus per-table columns and foreign-key definitions, so a future importer can compare actual constraints instead of assuming table names alone describe the schema.
- `create_consistent_sqlite_snapshot(source_path, snapshot_path)` opens the source read-only, reserves a new destination exclusively, copies through SQLite's backup API, validates integrity and foreign keys on the snapshot, closes the snapshot, and records its SHA-256 file digest. It removes only its own incomplete destination on failure and refuses overwrite and source/destination identity.
- `snapshot_legacy_node_databases(...)` preflights all three sources, creates three separate snapshots, re-runs preflight on the snapshots, and cleans up only snapshots created by the call if any stage fails.
- `validate_snapshot_set_consistency(...)` checks canonical network metadata, requires the declared genesis header to exist at height zero with a zero parent, and replays every stored header branch through `HeaderChain` to recheck proof of work, difficulty, timestamps, linkage, height, and cumulative work. It then checks active UTXO heights/parent linkage plus exact serialized-header agreement with the header store. This does not validate block bodies, transactions, scripts, or external network agreement, and it is not a substitute for independent consensus review.
- Tests cover committed WAL data, source-file stability, overwrite refusal, partial cleanup, clean three-store snapshots, and rejection of an active UTXO block absent from the header snapshot.
- These helpers are not a migration command. They do not import or publish a coordinated node database.

## Required validation sequence

1. Snapshot each source through SQLite's backup API and run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on each snapshot.
2. Validate required tables, columns, indexes, schema versions, and metadata. Reject unknown versions and unexpected extra tables unless explicitly allow-listed.
3. Replay the header DAG using the exact network genesis and proof-of-work limit; reject mismatched parameters or invalid header history.
4. Validate UTXO database integrity, active block linkage, block bodies, transaction records, undo records, and tip metadata using existing store validation paths.
5. Validate the recovery journal against the observed UTXO tip. A pending intent is a hard stop requiring explicit recovery, not an automatic migration choice.
6. Import tables into the staging database inside one transaction, preserving BLOB and integer values exactly. Avoid schema rewriting unless a versioned transformation is separately specified and tested.
7. Reopen the staged database using `PersistentNodeState.open_coordinated` with the exact network parameters. Run tip consistency and replay checks again.
8. Close cleanly, run SQLite integrity and foreign-key checks, reopen once more, and compare source/staged logical counts and state fingerprints.
9. Atomically publish the validated file and write a manifest containing tool version, schema versions, source hashes, logical counts, network genesis, validation results, and output hash. Do not include secrets.

## Required automated tests before implementation is trusted

- successful migration preserves header DAG, active UTXO tip, block bodies, undo data, and journal cleanliness;
- each source remains byte-for-byte unchanged on success and on every injected failure;
- invalid/corrupt source, unknown schema version, wrong genesis, mismatched active tip, and unresolved journal intent are rejected;
- destination exists / path aliases / symlink aliases / active writer / WAL snapshot scenarios are handled safely;
- failure at each import and validation stage leaves no published destination;
- interruption before atomic rename leaves sources intact and no accepted partial destination;
- successful output can be reopened and used for a subsequent coordinated block operation;
- migration is idempotently refused when the destination already exists; no implicit overwrite mode.

## Explicit non-goals

This migration does not validate consensus correctness, create a wallet, upgrade protocol rules, or make BLACKROOT production-ready. It does not authorize mainnet launch or handling funds.

## Read-only coordinated schema merge planning

The migration preflight now exposes a deterministic schema merge plan. It checks
global SQLite schema-object name collisions, rejects views/triggers and unknown
object types, verifies that foreign-key parents exist in the same source store,
and orders tables before their FK dependants. Explicit indexes are listed after
tables. The planner is read-only: it does not execute DDL, copy rows, publish a
destination database, or alter snapshots.

This is a planning gate only. The next importer must preserve the original
CREATE statements and row values, execute in an exclusively-created staging
database, verify row counts and integrity, reopen through
`PersistentNodeState.open_coordinated`, and retain all source snapshots. No
production migration is authorized by the planner result.

## Exclusive staged import (not production cutover)

A guarded importer now accepts a previously validated three-snapshot set and an
unused destination path. It reserves the destination with exclusive creation,
recreates the original table DDL in dependency order, copies rows in bounded
batches, recreates explicit indexes, and checks row counts, SQLite integrity,
and foreign keys. It records SHA-256 digests for each source and the completed
staging database. On failure it removes only the destination file it created;
source snapshots remain read-only.

The importer currently rejects schema features that the planner cannot safely
reproduce (including views and triggers). The importer opens source snapshots incrementally. If a later source
cannot be opened, already-open read-only handles are closed and the exclusively
reserved destination plus its SQLite sidecars are removed. A fault-injection
test verifies this path and confirms all source snapshot bytes remain unchanged.

The resulting file is a staging
artifact, not a migrated production database. It must still be reopened using
the exact network genesis and proof-of-work limit through
`PersistentNodeState.open_coordinated`, then pass node-level recovery,
transaction, script, and independent consensus review. No automatic cutover,
legacy-source deletion, wallet release, or mainnet launch occurs.

## Coordinated node reopen validation

A separate validator now reopens a staging database using
`PersistentNodeState.open_coordinated` with caller-supplied trusted
`pow_limit` and genesis parameters. It checks coordinated mode, UTXO
integrity, replayed header/active-tip agreement, and absence of pending
recovery intents, then closes the node-owned connection. The validator does
not infer or rewrite network parameters from the candidate database.

Passing this check establishes only that the current prototype stores can
reopen this database under the supplied network parameters. It does not prove
full consensus correctness, script completeness, transaction-history
completeness, peer-network agreement, operational resilience, or production
readiness. No cutover is performed.

### End-to-end prototype fixture coverage

The test suite now builds the three legacy stores using the actual node
constructors, connects a valid mined three-block active chain, snapshots those
stores, imports the snapshots into a new coordinated staging database, and
reopens that imported database through `validate_coordinated_staging_database`.
The test asserts that the height-two active UTXO tip and best header hash
survive the round trip and that no production cutover occurs.

This is a synthetic three-block fixture. It does not establish safety for
arbitrary historical databases, long chains, competing branches within a
legacy migration, large datasets, interrupted filesystem operations, or live
network cutover. Those remain separate migration and operational test gates.

### Competing-branch reorganization and restart test

A coordinated-node test now activates a two-block branch, constructs a
three-block competing branch from genesis, archives its bodies, and asks the
header DAG to select the greater-work branch. It verifies that reorganization
disconnects the former active suffix, connects the replacement branch, leaves
the recovery journal clear, and preserves the selected header/UTXO tip and
UTXO integrity after closing and reopening the node.

This is a synthetic equal-difficulty fork-choice fixture. It does not test
mainnet difficulty parameters, adversarial network timing, script/signature
authorization, transaction relay, or crash injection at every filesystem
boundary.

A companion fault-injection test forces an exception after the UTXO layer has
written a complete multi-block replacement branch but before the outer
coordinated transaction can commit. It checks that the previous active tip,
UTXO count, integrity, and empty recovery-journal state are restored, then
retries the same reorganization successfully. This tests application-level
transaction rollback, not sudden power loss or storage-device failure.

The schema planner also rejects SQLite virtual tables explicitly. Their
implementation depends on virtual-table modules and hidden/shadow-table
semantics that a generic table-and-index copier cannot safely preserve.
