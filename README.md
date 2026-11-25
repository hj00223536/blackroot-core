# BLACKROOT Core

**Status: protocol prototype — not a launched cryptocurrency.**

BLACKROOT is an experimental independent UTXO-chain design. This repository contains a documented consensus reference module and unit tests. It is not a production full node, wallet, miner, explorer, audited protocol, or public mainnet.

## Current design targets

- Native coin: BROOT (ticker is provisional and not reserved)
- UTXO transaction model
- Proof of Work using double SHA-256 (SHA-256d)
- Target block interval: 600 seconds
- Difficulty adjustment interval: 2,016 blocks; exact retarget rules remain to be specified
- Initial block subsidy: 50 BROOT
- Halving interval: 210,000 blocks
- Monetary precision: 100,000,000 atomic units per BROOT
- No premine or founder allocation in the proposed design
- Maximum supply ceiling: 21,000,000 BROOT

With integer atomic-unit halving, the emitted total is slightly below 21 million BROOT; 21 million is a ceiling, not a promise that every unit will be issued.

## Repository map

- src/blackroot_consensus.py: reference helpers for subsidy, block-header hashing, compact target decoding, and proof-of-work checks.
- src/blackroot_chain.py: in-memory header-linkage, proof-of-work, and cumulative-work accounting prototype (not competing-branch selection).
- src/blackroot_transactions.py: transaction serialization, merkle-root helper, and basic in-memory UTXO value accounting; no script/signature validation.
- src/blackroot_utxo_db.py: SQLite-backed UTXO persistence prototype with atomic spend/create updates; no script/signature validation.
- tests/test_utxo_db.py: persistence, atomicity, rollback, and duplicate-outpoint tests.
- docs/transactions.md: transaction format and explicit security omissions.
- docs/difficulty-and-chainwork.md: proposed retarget arithmetic, chainwork, and unresolved boundary rules.
- docs/utxo-storage.md: SQLite persistence behavior and production limitations.
- tests/: unit tests for reference helpers, header linkage, transaction encoding, merkle roots, and UTXO accounting.
- docs/: protocol, genesis, monetary policy, security, and launch-readiness notes.

## Run reference tests

Requires Python 3.10+.

    python -m unittest discover -s tests -v

## Important

Do not use this prototype to store value, mine a public network, or accept deposits. A secure cryptocurrency requires a complete independently reviewed implementation: script execution and signature verification, coinbase and subsidy validation, mempool policy, peer-to-peer protocol, cumulative-chainwork selection, difficulty retargeting, persistent storage and reorg recovery, wallet key management, denial-of-service defenses, reproducible releases, and sustained adversarial testing. The new transaction module checks serialization and value accounting only; it does not authenticate spenders.

No genesis hash, network identifier, address prefix, ports, DNS seeds, exchange listing, market price, or launch date is claimed by this repository.


## Block validation prototype

`src/blackroot_blocks.py` now validates the block transaction list, coinbase
placement and reward ceiling, transaction IDs, merkle-root commitment, UTXO
value accounting, and aggregate fees against a parent UTXO snapshot. This is
still an accounting prototype: it does not verify scripts/signatures, enforce
coinbase maturity, validate proof of work or timestamps, or persist block and
UTXO state atomically. See [block validation notes](docs/block-validation.md).


## Persistent block connection prototype

The SQLite UTXO store can atomically connect a block, persist its header and
ordered transactions, update the UTXO snapshot, and expose the stored tip.
See [persistent block notes](docs/persistent-blocks.md). This supports only
linear extension; it does not implement proof-of-work validation, script or
signature checks, undo data, side branches, or reorganizations.
