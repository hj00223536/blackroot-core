# SQLite UTXO storage prototype

**Status:** local persistence prototype only; not a consensus database.

The module `src/blackroot_utxo_db.py` stores an outpoint keyed by the raw
32-byte transaction digest and uint32 output index. Values are stored as
integer atomic units and scripts as opaque byte strings. SQLite WAL mode,
foreign-key enforcement, and a busy timeout are enabled.

`UTXOStore.apply(tx)` opens an immediate write transaction, loads referenced
outputs, checks the prototype's value-conservation rules, deletes spent
outputs, and inserts created outputs. A failure rolls the SQLite transaction
back. This gives the local database update atomicity for this narrow operation.

## Explicit limitations

- It does not execute scripts or verify ECDSA/Schnorr signatures.
- It does not validate a block, transaction inclusion, proof of work, subsidy,
  fees claimed by coinbase, maturity, locktime, or sequence rules.
- It has no block index, undo journal by block, reorganization support,
  snapshot/bootstrap verification, pruning, migration framework, or corruption
  recovery strategy.
- `add_genesis_output` is a trusted bootstrap helper; it does not verify a
  genesis block or prove that an output is authorized.
- It is not designed for concurrent network workloads or untrusted RPC access.

Do not use this store for real funds or a public node. Production requires
block-connected state transitions, deterministic undo data, crash/reorg
recovery tests, schema migration policy, fuzzing, and independent review.
