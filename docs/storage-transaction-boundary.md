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
- independent process writers contending for the same SQLite database, using `BEGIN IMMEDIATE`, and serialized rather than interleaved writes;
- four independent processes each committing 12 transactions (48 writes total), with no missing rows;
- concurrent first-open WAL initialization, including retrying a transient lock while another process enables WAL.

The process termination tests do not simulate physical power loss, filesystem corruption, controller-cache loss, or storage-device failure. The multi-process test demonstrates SQLite writer serialization for the tested scenario; it is not a broad stress, performance, or multi-host test. WAL is intended for local filesystem use and does not establish safe shared-network-filesystem operation.

## Safe migration tooling — staging only

The repository now contains read-only legacy-store preflight, WAL-consistent SQLite snapshots, cross-store header/UTXO consistency checks, a fail-closed schema merge planner, a staging importer, and a validator that reopens the staged database through the coordinated node stores. An end-to-end fixture verifies a synthetic one-block legacy store can be snapshotted, imported, and reopened. No production cutover has been performed. Do not point coordinated mode at existing live database files or manually merge them.

The migration tooling still needs long-chain and large-dataset coverage, backup restoration drills, broader fault injection, disk-full and interrupted-copy tests, operational cutover/rollback procedures, and independent review. Source databases are preserved by the current snapshot/import path; the legacy constructor remains the default.

## Remaining engineering work

- Expand migration coverage to multi-block histories, large datasets, backup restoration, interrupted copies, and disk-full fault injection.
- Expand multi-process contention coverage to timeout handling, rollback under contention, and longer stress runs.
- Define operational lifecycle behavior for graceful shutdown, interrupted startup, backups, restore drills, and disk-full handling.
- Complete consensus, script/signature, networking, wallet, mining, fuzzing, independent implementation, and external security-review requirements listed in `docs/mainnet-launch-gates.md`.

**Mainnet status remains NOT READY.** Passing these tests is evidence only for the specific prototype behaviors described above, not production safety or monetary value.
