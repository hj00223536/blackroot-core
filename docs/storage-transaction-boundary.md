# Storage Transaction Boundary Assessment

**Status: coordinated single-database mode is implemented as an opt-in prototype. Existing three-database deployments are not migrated. Mainnet readiness is not established.**

## Current architecture

The default compatibility constructor for `PersistentNodeState` continues to use separate header, UTXO, and recovery-journal databases. It is retained to avoid silently changing existing data layouts.

The opt-in `PersistentNodeState.open_coordinated(database_path, pow_limit, genesis)` lifecycle opens one node-owned `SQLiteTransactionCoordinator` and initializes the header store, UTXO store, and recovery journal on its guarded connection. Coordinated block acceptance, body archival, header persistence, and best-chain reorganization use the outer transaction. Store adapters cannot commit, roll back, or close the coordinator-owned connection. Header DAG memory is reloaded after the durable commit.

## Verified behavior and limits

Automated tests cover:

- exact shared connection use by the three stores;
- commit-on-success and rollback-on-exception;
- fault injection during block connection and reorganization;
- process termination before commit (reopens to old durable state) and immediately after commit (reopens to new durable state);
- guarded store connection ownership;
- coordinated tip-disconnect and UTXO write scopes;
- independent process writers contending for the same SQLite database, using `BEGIN IMMEDIATE`, and serialized rather than interleaved writes.

The process termination tests do not simulate physical power loss, filesystem corruption, controller-cache loss, or storage-device failure. The multi-process test demonstrates SQLite writer serialization for the tested scenario; it is not a broad stress, performance, or multi-host test. WAL is intended for local filesystem use and does not establish safe shared-network-filesystem operation.

## Safe migration requirements — not implemented

No migration from the legacy three-file layout has been performed. Do not point the coordinated mode at existing live database files or manually merge them.

A future migration must be versioned and backup-first, preserve all source files, stage copies, validate SQLite integrity and schema versions, verify header/UTXO tips and block-body/undo consistency, refuse ambiguous or corrupt inputs, and publish the destination only after complete validation. Migration tests must prove the originals remain unchanged after both success and failure. The legacy constructor remains the default until this work is independently reviewed.

## Remaining engineering work

- Implement and test a backup-first migration utility for legacy databases.
- Expand multi-process contention coverage to timeouts, rollback under contention, and repeated writer stress.
- Define operational lifecycle behavior for graceful shutdown, interrupted startup, backups, restore drills, and disk-full handling.
- Complete consensus, script/signature, networking, wallet, mining, fuzzing, independent implementation, and external security-review requirements listed in `docs/mainnet-launch-gates.md`.

**Mainnet status remains NOT READY.** Passing these tests is evidence only for the specific prototype behaviors described above, not production safety or monetary value.
