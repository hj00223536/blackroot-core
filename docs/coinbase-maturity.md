# Coinbase maturity: implementation contract

**Status: IMPLEMENTED IN THE EXPERIMENTAL UTXO BLOCK PATH; NOT MAINNET-READY.**
`src/blackroot_maturity.py` defines the 100-block rule. Schema v2 stores
`created_height` and `is_coinbase` for live UTXOs and spent-output undo records.
`connect_block` and replacement-branch connection supply complete provenance
to the shared validator, so both paths reject premature coinbase spends.
Disconnect/reorganization restore provenance. The standalone accounting-only
`apply` helper is not a consensus path. Header consensus, safe v1 replay/reindex,
and production review remain incomplete.

## Consensus rule

The proposed network constant is `COINBASE_MATURITY = 100` blocks. A coinbase
output created at height `h` may first be spent by a regular transaction in
block height `h + 100`. Equivalently, reject a spend when
`spending_height - created_height < COINBASE_MATURITY`.

The rule applies to every input in every regular transaction, including inputs
spent later in the same block. Coinbase outputs created by the block being
validated are never spendable in that block.

## Required UTXO provenance

Every live UTXO must carry:
- `created_height`: non-negative block height at which the output was created;
- `is_coinbase`: whether its creating transaction is the block coinbase.

These fields must survive SQLite close/reopen, normal block connection,
disconnect undo, and atomic reorganization. Undo records must restore the
original provenance, not infer it from the output's transaction bytes.

Trusted bootstrap outputs inserted by `add_genesis_output` must be explicitly
classified as non-coinbase or supplied with authenticated provenance. The
helper must never silently label an unknown historical output as mature.

## Schema migration safety

A schema-v1 UTXO row has no creation height or coinbase flag. It is impossible
to infer those facts from the current UTXO row alone. A v1 database with live
UTXOs must therefore not be upgraded by assigning default metadata.

A future migration must either:
1. deterministically replay a fully verified genesis-to-tip block history and
   reconstruct provenance, checking every block and the resulting UTXO set; or
2. refuse migration and require an explicitly verified reindex from genesis.

The migration must be transactional, versioned, idempotent, and tested against
interrupted migration and corrupted/incomplete block history. Never silently
discard or relabel user state.

## Completed prototype tests

The unit suite covers the height-99 rejection, height-100 acceptance, invalid
or incomplete provenance rejection, persistent coinbase-origin storage, block
connection rejection of an immature spend, reorganization rejection with full
rollback, and safe refusal of schema-v1 databases with live UTXOs.

## Remaining tests and release gates

- exercise a persistent-store spend at exact maturity height 100;
- verify provenance restoration after disconnect and after a multi-block reorganization;
- implement and test deterministic verified replay/reindex for schema v1, or continue refusing migration.

## Security boundary

Maturity enforcement must happen in the shared block-validation path used by
both `connect_block` and `reorganize`, not only in an RPC or wallet. The
standalone accounting-only transaction helper is not a consensus validator.
Independent review and consensus test vectors are required before mainnet use.
