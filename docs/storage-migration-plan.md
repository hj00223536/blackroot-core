# Legacy SQLite storage migration plan

**Status: design only. No migration utility is implemented and no existing database has been modified.**

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
