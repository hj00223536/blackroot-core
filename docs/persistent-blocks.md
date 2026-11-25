# Persistent block connection prototype

The SQLite UTXO store persists block headers, ordered transaction bodies, UTXO snapshots, and undo data. State transitions run inside SQLite write transactions and roll back completely when validation fails.

## Block connection APIs

### `connect_block(block, height)`

This is the lower-level experimental body/storage path. It enforces sequential height and parent linkage, validates the supported block transaction rules, and updates the persistent UTXO set. It does **not** independently establish that the block header belongs to a proof-of-work-valid best chain. Do not use this API as a network-facing block acceptance boundary.

### `connect_validated_block(block, height, header_chain)`

This is the safer connection entry point for callers that maintain a `HeaderChain`. Before changing the database, it requires a real `HeaderChain`, a requested height on its selected best-chain path, an exact serialized-header match, and either genesis for an empty store or a one-height/one-parent extension of the persistent tip.

`HeaderChain` checks header linkage, proof of work, target limits, expected difficulty bits, and median-time-past. Its optional future-time bound is applied only when the caller supplies adjusted time. The header chain must itself be initialized from the intended genesis and network parameters; this wrapper does not establish independent network consensus or peer agreement.

## Body validation and persistent provenance

For connected block bodies, the store loads the complete UTXO set together with each output's creation height and coinbase flag. The block validator checks the supported legacy P2PKH authorization path, transaction value accounting, duplicate transaction IDs, merkle commitment, coinbase placement, and subsidy-plus-fees ceiling. Coinbase maturity is enforced when complete provenance is supplied. Newly created outputs receive provenance, and undo records preserve provenance for restored outputs.

The implementation remains deliberately fail-closed for unsupported script types. Its pure-Python elliptic-curve verifier is a prototype and is not appropriate for production key handling.

## Disconnection and reorganization

`disconnect_tip(expected_tip_hash)` requires an exact tip hash, removes outputs created by that block, restores only outputs that existed in the parent UTXO snapshot, and deletes the block row and associated undo records atomically.

`reorganize(disconnect_hashes, connect_blocks)` is a lower-level transactional storage primitive. Disconnect hashes must be tip-first and replacement blocks fork-first. It validates replacement block bodies, including supported legacy P2PKH
authorization and coinbase maturity, but does not independently prove that a
replacement branch has greater chainwork or valid headers.

`reorganize_to_best(header_chain, replacement_blocks)` connects the in-memory header DAG's fork-choice result to the UTXO transition. It requires the active database tip to exist at the same height in the supplied header DAG, requires the candidate best tip to have strictly greater cumulative chainwork, derives the disconnect/connect paths, and requires an exact matching body for every connecting header. The final state switch is atomic.

## Remaining consensus and operational gaps

This is not a complete node or production consensus implementation. Missing or incomplete areas include a complete Script interpreter and supported script set, independently reviewed cryptographic primitives, full block size/weight and transaction-finality rules, complete consensus test vectors, persistent header/side-branch storage and crash-recovery verification, authenticated genesis parameters, P2P protocol and DoS protections, wallet software, RPC hardening, reproducible releases, and independent security review. A successful test suite does not close these gates or authorize a public mainnet launch.

## Provisional serialized block-size bound

The `Block` model now rejects legacy serialized block bodies larger than 1,000,000 bytes, counting the 80-byte header, CompactSize transaction count, and serialized transactions. This is a provisional prototype bound, not a finalized network rule: it must be reconciled with the normative protocol specification and independent consensus test vectors before any public network launch. It does not implement SegWit weight/vsize semantics.
