# Storage Transaction Boundary Assessment

**Status: design assessment only. No storage migration has been performed.**

## Current verified architecture

The node currently opens three independently managed SQLite databases:

- `PersistentHeaderStore` persists and commits header-DAG updates through its own connection.
- `UTXOStore` opens its own connections for block bodies, active-chain state, undo records, and UTXO mutations. Block connection and reorganization use explicit transactions on those connections.
- `NodeRecoveryJournal` persists and commits recovery intent through a third connection/database.

`PersistentNodeState` coordinates these stores at the Python method level. It writes a recovery intent before a UTXO transition and reconciles the observed UTXO tip afterward. This is a useful fail-closed recovery protocol, but it is not one atomic SQLite transaction across all persisted state.

## Important distinction: same file is not enough

Changing all three path arguments to the same SQLite filename would **not** establish atomicity.

The stores currently:
- create connections independently;
- enter connection context managers independently;
- issue commits inside their own methods;
- and, in some operations, explicitly begin and commit transactions.

Those boundaries cannot be composed into one caller-owned transaction merely by reusing a filename. Independent connections to one SQLite file still have independent transaction scopes. A broad path-only change could also create confusing schema ownership and locking behavior without solving partial commits. The node-state constructor now rejects path aliases among the header, UTXO, and recovery-journal stores (including normalized relative-path aliases), before creating any database files. This is a guard against accidental configuration, not an atomicity implementation.

## Recommended target design

Introduce one node-owned SQLite connection/transaction coordinator and make persistent stores operate on that caller-owned connection.

Required properties:

1. One connection owner per node-state transaction boundary.
2. Store methods accept a connection or transaction context; they do not open, commit, or close the node-owned connection during a coordinated operation.
3. Schema initialization remains explicit and idempotent, with table names and metadata keys owned by their respective stores.
4. A single block-acceptance transaction covers the intended durable effects: body/archive record, active block and transaction records, UTXO mutations, undo data, and active-tip metadata.
5. Header-DAG persistence is included in that same transaction only after header-store APIs are refactored to use the same connection. Header validation and in-memory chain publication happen only after durable commit succeeds.
6. Reorganization performs all disconnect/connect operations and active-tip updates inside one transaction.
7. Startup replay and integrity checks remain fail-closed. The recovery journal should be reconsidered after the single-database transaction boundary is proven; it must not be removed merely because the database filename is shared.

## Safe migration sequence

- **Phase A — connection ownership:** add a small connection/transaction abstraction with explicit ownership rules. Preserve the current three-file mode until tests prove the new mode.
- **Phase B — store adapters:** refactor each store to support an injected connection without internal commits or connection closure when participating in a caller-owned transaction. Keep standalone compatibility paths isolated.
- **Phase C — atomic acceptance:** implement block acceptance and reorganization through one transaction coordinator. Do not publish in-memory best-chain state before commit.
- **Phase D — fault testing:** inject exceptions at every write stage and terminate subprocesses before and after commit. Reopen the database and prove the result is either wholly old state or wholly new state, never a mixed state.
- **Phase E — migration:** define a versioned, backup-first migration from existing files. Verify row counts, hashes, active tip, archived bodies, undo records, and header replay before switching the node to the consolidated database.

## Acceptance criteria

The migration is not complete until automated tests demonstrate:

- all coordinated stores use the exact same connection object during a block-acceptance transaction;
- no participating store commits independently;
- a failed transaction leaves no partial header/UTXO/body/undo/tip update;
- a successful transaction persists all required records together;
- reorganization rollback restores the exact prior active state;
- process-crash tests pass on both sides of the commit boundary;
- migration refuses ambiguous, corrupt, or inconsistent source databases without deleting or overwriting them.

## Current safety status

The existing recovery journal and startup consistency checks remain in place. The current architecture still has separate databases and no atomic cross-database commit. This document is a design checkpoint, not evidence of an implemented atomic-storage guarantee.

**Mainnet status remains NOT READY.**

## Connection-coordinator prototype checkpoint

A first, isolated primitive now exists in `src/blackroot_sqlite.py`:

- one coordinator owns one SQLite connection and closes it on exit;
- callers receive that exact connection inside an explicit write transaction;
- successful exit commits once; any exceptional exit rolls back;
- nested or externally started transactions are rejected;
- foreign-key enforcement, WAL mode, busy timeout, and FULL synchronous mode are configured on the owned connection;
- participating stores receive a restricted connection facade that rejects store-level commit, rollback, and close calls; its context-manager exit deliberately does not commit the outer transaction.

Unit tests cover commit, rollback (including transactional DDL), connection identity and closure, nested-transaction rejection, foreign-key configuration, and attempts by a store facade to take transaction ownership.

**Integration checkpoint — UTXO adapter (partial).** `UTXOStore` accepts the coordinator's guarded connection for schema initialization, reads, block-body archival, and bootstrap-output insertion. Block connection now also runs inside the caller-owned outer transaction: it does not begin, commit, roll back, or close that transaction. The adapter requires an already-active outer transaction even during schema initialization. Tests prove successful block persistence and prove that an exception after block connection rolls back both schema creation and the complete block/UTXO update. The standalone mode retains its own transaction boundary.

The accounting-only `apply` operation, UTXO block connection, multi-block reorganization, and tip-disconnect now use a shared write-scope abstraction: in coordinator mode they require an active outer transaction and never commit, roll back, or close it; in standalone mode they preserve the store-owned transaction behavior. Tests cover coordinated accounting updates and rollback, block connection and rollback, a committed coordinated reorganization, rollback of the entire branch switch after an injected exception, and coordinated tip-disconnect. The accounting-only path remains disabled once chain block history exists.

**Header-store adapter (partial).** `PersistentHeaderStore` accepts the guarded coordinator connection for schema creation, replay, and header writes. In coordinator mode, a candidate DAG is not published to memory until the caller commits and invokes `reload()`.

**Recovery-journal adapter (partial).** `NodeRecoveryJournal` accepts the same guarded connection for schema creation, intent preparation, reconciliation, and pending-state reads. Its writes require an active outer transaction and do not commit it.

**Node lifecycle integration (opt-in prototype).** `PersistentNodeState(database_path=...)` now opens one long-lived coordinator and initializes all three stores on the same SQLite connection inside one transaction. In this mode, header additions, body archival, block connection, UTXO mutations, and journal preparation/reconciliation use the node-owned transaction boundary. Header memory is reloaded only after header commit. Block connection now commits the body, active block/transaction rows, UTXO/undo changes, and journal updates together. A fault-injection test raises after the UTXO update and journal reconciliation to verify that the whole coordinated operation rolls back. The original three-file constructor remains the default for backward compatibility.

The opt-in mode has passed the unit-test workflow for the implementation commit `3076716e7399069cbd6efe681950d2bfbeb0565f`. Additional tests for the node-level shared database and rollback are being run separately. This is not yet a migration of existing three-file databases, and no production crash-safety or mainnet guarantee is claimed. Reorganization, full process-crash coverage, backup-first migration, and operational lifecycle management remain to be completed.
