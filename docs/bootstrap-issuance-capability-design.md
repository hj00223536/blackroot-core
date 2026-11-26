# Trusted bootstrap issuance capability design

**Status: DESIGN ONLY — NOT IMPLEMENTED. No issuance authorization is created by this document.**

## Purpose

The current `UTXOStore.add_genesis_output(outpoint, output)` method is a trusted pre-chain storage primitive. It checks that no block has been activated and that cumulative bootstrap issuance remains below the supply cap. It does **not** authenticate the caller, prove owner approval, or prove that an output belongs in the canonical genesis transaction.

The AST regression test only prevents direct references in the current `src/*.py` production tree. It is not a security boundary against external Python callers, reflection, dynamic dispatch, modified source, or direct database writes.

## Required design properties

1. **No network reachability:** P2P messages, RPC handlers, peer callbacks, wallet APIs, and ordinary transaction processing must have no route to bootstrap issuance.
2. **One-time initialization:** issuance is permitted only while initializing a fresh chain database, before any block or active-chain state exists. Reopening an initialized database must not reissue.
3. **Deterministic genesis is authoritative:** the founder allocation must be represented by the canonical serialized genesis transaction and its committed txid/Merkle root/header. A separate ad-hoc database credit must not substitute for the genesis output.
4. **Explicit authorization input:** the initialization process must verify a reviewed, immutable genesis manifest containing the network identity, genesis transaction bytes, founder output index, amount, locking script, and expected hashes. The manifest must be checked against compiled/frozen consensus parameters.
5. **Idempotence and conflict failure:** repeat initialization with the exact same manifest must leave state unchanged; any different manifest, duplicate outpoint, unexpected existing UTXO, or issuance mismatch must fail closed.
6. **Supply accounting:** founder issuance plus all scheduled mining issuance must never exceed 40,000,000 BRT. The founder output is exactly 20,000,000 BRT only if the final owner-approved monetary policy remains unchanged.
7. **No secrets in source control:** private keys and recovery phrases remain outside GitHub. The repository may contain only public locking-script material after explicit owner approval.
8. **Auditable evidence:** record the manifest digest, genesis identity, output index, amount, and initialization result. Do not log private key material.

## Preferred implementation shape (future work)

- Remove general-purpose bootstrap issuance from ordinary node-facing store APIs, or make it require an unforgeable initialization capability that is constructible only by the dedicated genesis initializer.
- Keep the initializer separate from P2P and runtime request handlers.
- Verify the exact genesis transaction and its output script before writing any UTXO rows.
- Perform genesis identity, initial UTXO insertion, issuance metadata, and initialized-state marker in one database transaction.
- On startup, verify the stored initialized-state marker and genesis identity against the frozen network configuration.
- Provide tests for fresh initialization, exact idempotent reopen, altered manifest rejection, duplicate issuance rejection, over-cap rejection, post-activation rejection, and proof that P2P/RPC/network paths cannot acquire or invoke the initialization capability.

## Required initialization state model (design constraint)

The current schema-v5 metadata contains `bootstrap_issued_sats`, but that counter is not an initialization authorization record. The implementation must not infer that a database is safely initialized merely because the counter exists or equals zero.

A future initializer should atomically persist a distinct, immutable initialization record with at least:

- schema/version identifier for the manifest format;
- frozen network identifier and genesis block hash;
- exact genesis coinbase transaction bytes (or a canonical digest plus independently checked bytes);
- founder output index, value, and locking-script bytes;
- manifest digest and explicit initialization-complete marker;
- cumulative bootstrap issuance derived from the exact committed outputs.

The record and all genesis UTXO rows must be committed in the same database transaction. Startup must fail closed if the marker exists but any committed field, genesis identity, or issuance total disagrees. If no marker exists, initialization may proceed only after proving the database has no blocks, UTXOs, bootstrap issuance, or conflicting chain metadata. A partially populated or legacy database must not be silently repaired by issuing the founder output.

The manifest is public consensus input, not a wallet backup: it must never contain a private key, seed phrase, password, or signing secret. Its digest is an integrity identifier, not proof of owner identity by itself; owner approval must be recorded through the project's reviewed release/governance process before the manifest is accepted.

## Acceptance tests required before implementation is considered complete

- A network-facing test harness cannot call or obtain the initializer capability.
- A fresh database initialized from the approved manifest contains exactly the manifest's genesis outputs and no extra founder credit.
- A second initialization with the same manifest changes no rows or issuance totals.
- A different genesis hash, locking script, output value, or manifest digest is rejected before state mutation.
- Crash injection at each write boundary leaves either the fully committed genesis state or a clean uninitialized database.
- Independent code reproduces the genesis transaction bytes, txid, Merkle root, header hash, and proof-of-work result.
- A spend test proves the founder output is spendable using the corresponding owner-held private key without ever placing that key in the repository or CI logs.

## Current release impact

This proposal does not implement a capability guard, does not create the founder output, does not alter consensus or database behavior, and does not authorize a testnet or mainnet launch. The founder allocation remains unissued until an owner-approved public locking script and deterministic genesis transaction are implemented and independently verified.
