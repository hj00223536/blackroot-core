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

- The standalone `UTXOStore.apply(tx)` helper is accounting-only and does not
  execute scripts or verify spend authorization. Block connection and
  replacement-block validation invoke the current fail-closed legacy P2PKH
  signature verifier; this is not a general Script engine.
- Block connection validates transaction inclusion, subsidy and fee ceilings,
  but does not validate header proof of work, difficulty, timestamps, coinbase
  maturity, locktime, or sequence rules.
- It has a block index, undo journal, and atomic suffix reorganization support,
  but no verified snapshot/bootstrap procedure, pruning, safe provenance
  migration, or corruption recovery strategy.
- `add_genesis_output` is a trusted bootstrap helper; it does not verify a
  genesis block or prove that an output is authorized.
- It is not designed for concurrent network workloads or untrusted RPC access.

Do not use this store for real funds or a public node. Production still requires complete consensus validation, persisted UTXO
creation-height/coinbase provenance, safe schema migration or verified reindex,
coinbase maturity, deterministic undo data, crash/reorg recovery tests,
fuzzing, and independent review. See `docs/coinbase-maturity.md`.
