# Deterministic UTXO Replay Verification Design

**Status: PARTIAL LOCAL PROTOTYPE IMPLEMENTED — FULL DESIGN NOT IMPLEMENTED, NOT APPROVED, AND NOT A MAINNET READINESS CLAIM.**

## 1. Security objective

Provide an independent verification path that reconstructs the active UTXO state from an authenticated network identity and frozen Genesis commitment, using only the ordered active-chain block data and normative consensus rules. The verifier must compare its reconstructed state with persisted state and fail closed on any discrepancy.

A successful SQLite integrity check, a valid block index, a UTXO snapshot, or internally consistent undo rows is not a substitute for replay.

## 2. Trust inputs and forbidden trust shortcuts

The verifier may trust only inputs authenticated outside the database being checked:

- a frozen, canonical network-identity artifact and its independently pinned digest;
- the exact Genesis block/manifest commitment and approved consensus parameter set;
- a reviewed verifier build and versioned independent test vectors.

It must not treat the following database contents as self-authenticating:
- the active UTXO table or its row count;
- `bootstrap_issued_sats` or other locally editable accounting metadata;
- stored cumulative issuance values;
- undo rows;
- a database-local manifest digest or initialization marker;
- the selected tip merely because the header table names it.

The current repository has no authenticated external network-identity pin and no approved Genesis issuance package. Therefore this proposal cannot currently be used to initialize or validate a public network.

## 3. Required replay data

For each active height, the verifier needs:
1. the exact 80-byte header;
2. the exact ordered raw transaction bytes, including the coinbase;
3. a canonical height/position index with no gaps or duplicates;
4. the parent relationship and the frozen consensus parameters needed to validate the block.

The current store has active block metadata and ordered raw transaction records. Replay must verify that every height starts at zero, parent links are continuous, transaction positions are contiguous, each raw transaction parses canonically, txids match their indexed values, and the reconstructed block's header hash and Merkle commitment match the stored header/index. Missing or extra records are fatal.

Candidate-branch body archives are not a substitute for the canonical active-chain transaction records. The replay input set must be explicitly defined and authenticated.

## 4. Replay algorithm

Use a fresh, isolated in-memory UTXO map and provenance map. Never seed either from the database's current `utxos` table.

1. Verify the external network identity, Genesis digest, consensus rules, and verifier version before reading candidate state as authoritative.
2. Load active-chain records in ascending height and require exactly one Genesis at height zero, contiguous heights, and exact parent linkage.
3. Reconstruct each block from its stored header and ordered raw transactions. Check canonical transaction encodings, txids, transaction count, Merkle root, and block hash.
4. Run the same frozen consensus validation rules used for block admission: header/PoW/difficulty/time rules, transaction structure, scripts/signatures, duplicate inputs, in-block dependency order, coinbase placement/maturity, value conservation, and subsidy/fee limits. Any rule not yet fully specified or implemented is a blocker, not an invitation to skip validation.
5. Start from the exact authenticated Genesis allocation. Derive every initial outpoint from the Genesis transaction and its output index. No caller-supplied arbitrary bootstrap UTXO rows are permitted.
6. Apply each block transaction in canonical order to the private replay map. Track source txid/output index, creation height, coinbase status, and creation MTP for every live output. Track every spent outpoint so duplicate spends and impossible provenance fail.
7. Independently derive per-block subsidy, fees, cumulative issuance, and supply-cap accounting. Do not trust stored `subsidy_issued` or `total_fees` as inputs to the calculation.
8. Recreate expected undo records from replay transitions, including exact spent-output values and provenance and exact created outpoints. Compare these derived records with persisted undo tables.
9. At the active tip, compare the complete reconstructed UTXO set and every provenance field with the persisted UTXO table. Compare active tip, per-block issuance/fees, transaction indexes, and undo records as well.
10. Return a structured verification result containing the authenticated identity digest, verifier version, replayed height/tip, deterministic state commitment, and explicit success/failure reason. The result must not mutate the candidate database.

## 5. Deterministic comparison format

Before implementation, freeze a canonical UTXO commitment format. At minimum, define:
- byte order and fixed-width encoding for txid and output index;
- integer encoding and units for value and heights;
- exact script byte representation;
- nullable-MTP encoding that distinguishes unknown from zero;
- coinbase flag encoding;
- lexicographic outpoint sort order;
- domain separation, hash algorithm, and version tag.

The verifier must compare full rows, not only aggregate balances or a row count. A cryptographic state root may accelerate comparison only after its canonical encoding and independent vectors are frozen; it does not replace row-level diagnostics.

## 6. Bootstrap and historical-state boundary

The current pre-activation `add_genesis_output()` path inserts caller-supplied outputs and increments `bootstrap_issued_sats`; it does not authenticate a Genesis manifest. The pre-activation `apply()` path does not retain raw transaction history. Such databases do not contain enough authenticated history for deterministic replay.

The same trust gap affects reorganization undo for a bootstrap-origin output: when its source transaction is absent from persisted active-chain history, the current reorganization path cannot independently derive the original value and script from a block. It can check that an undo row exists for the input, but that row is not an authenticated source of truth. A reorganization that restores such an output is therefore only a local prototype behavior, not evidence of tamper-resistant recovery. Before production use, either prohibit spending bootstrap-origin outputs or introduce and independently authenticate a canonical bootstrap/Genesis commitment and verify each restored outpoint against it.

Until an authenticated one-time Genesis initializer exists:
- reject replay mode for any state containing unauthenticated bootstrap issuance;
- do not infer founder ownership or allocation from a UTXO row;
- do not invent creation MTP for bootstrap-origin outputs;
- require a fresh, isolated rebuild from an authenticated Genesis package to migrate to replay-verifiable state;
- preserve the original database as evidence and never overwrite it in place.

A migration must be a separately reviewed backup-first workflow with an exact source snapshot, manifest, dry-run comparison, atomic activation, and rollback plan.

## 7. Failure atomicity and operational isolation

Replay is read-only with respect to the candidate database and runs before networking, mining, transaction admission, or spend-capable wallet operations. On any parse, consensus, provenance, identity, or comparison error, it reports failure and leaves the candidate and active data directory unchanged.

Do not automatically repair or rewrite a mismatching database from the replay result. Quarantine and investigate instead. Any future repair/import operation is a distinct privileged workflow requiring its own manifest, operator approval, backup, and audit trail.

## 8. Required test and review programme

- Independent replay implementation reproduces byte-identical results from the same frozen vectors.
- Corrupt or delete each block, transaction, txid index, UTXO row, provenance field, issuance field, and undo row; replay must reject.
- Alter the network identity, Genesis digest, protocol parameter, active tip, and transaction ordering; replay must reject.
- Test duplicate spends, same-block dependency ordering, coinbase maturity, MTP boundaries, retarget boundaries, reorgs, and issuance-cap edges.
- Test empty, truncated, non-canonical, oversized, and trailing-byte encodings.
- Run replay after crash/recovery and from independently restored backups.
- Prove replay is read-only and bounded in memory/disk/time for supported chain sizes.
- Obtain independent consensus/security review and cross-client reproduction before closing the launch gate.

## 9. Implemented local prototype boundary

`UTXOStore.verify_active_chain_replay()` now provides a read-only local consistency replay from an empty in-memory UTXO/provenance state. It checks the caller-supplied `HeaderChain` against a caller-supplied expected Genesis hash, reconstructs active blocks from stored headers and ordered raw transactions, validates transaction transitions through the repository's existing block validator, derives subsidy/fees and undo records, compares the live UTXO/provenance rows, and rejects extra transaction/undo rows outside the active replay.

Focused tests currently cover a Genesis-only replay, live-UTXO tampering, non-zero bootstrap rejection, and orphan transaction/undo rows. These are local regression tests, not independent consensus verification.

The prototype does **not** authenticate a network identity or manifest, pin a trusted Genesis digest outside the caller, freeze consensus parameters, independently implement consensus/script validation, prove all header-chain rules, freeze a canonical UTXO commitment, or provide an external client. Multi-block spends/reorganizations, adversarial corruption coverage, resource bounds, crash/backup replay, and independent security review remain open.

## 10. Current decision

The repository has a limited local replay prototype, but not the complete authenticated deterministic replay system specified in this document. **Keep deterministic UTXO replay and bootstrap provenance OPEN. No Testnet/Mainnet launch or issuance is authorized.**
