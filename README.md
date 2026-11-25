# BLACKROOT Core

**Status: experimental protocol prototype — not a launched cryptocurrency.**

BLACKROOT is an experimental independent UTXO-chain design. This repository contains reference consensus helpers and prototype components. It is not a production full node, wallet, miner, explorer, audited protocol, or public mainnet.

## Proposed monetary and consensus parameters

- Native coin name: BLACKROOT
- Ticker: BRT (provisional; availability and trademark status not established)
- UTXO transaction model
- Proof of Work using double SHA-256 (SHA-256d)
- Target block interval: 600 seconds
- Proposed difficulty adjustment interval: 2,016 blocks; normative boundary behavior is not finalized
- Initial block subsidy: 50 BROOT
- Halving interval: 210,000 blocks
- Monetary precision: 100,000,000 atomic units per BROOT
- No premine or founder allocation is proposed
- Maximum supply ceiling: 21,000,000 BROOT

With integer atomic-unit halving, total issuance is slightly below 21 million BROOT. These are design proposals, not yet frozen mainnet parameters or a promise of value.

## Repository map

- `src/blackroot_consensus.py`: subsidy, SHA-256d, header serialization, compact target, proof-of-work, and chainwork reference helpers.
- `src/blackroot_chain.py`: in-memory header DAG, proof-of-work checks, median-time-past, difficulty expectations, and cumulative-work fork choice prototype.
- `src/blackroot_header_store.py`: separate SQLite header-DAG persistence prototype with replay verification on reopen.
- `src/blackroot_transactions.py`: legacy transaction serialization, txids, merkle-root helper, and UTXO accounting.
- `src/blackroot_script.py`: limited legacy P2PKH ECDSA validation prototype; not a complete Script interpreter and not production cryptography.
- `src/blackroot_blocks.py`: supported block-body validation prototype, including coinbase placement/reward limits and supported script checks.
- `src/blackroot_maturity.py`: coinbase maturity rule prototype.
- `src/blackroot_utxo_db.py`: SQLite UTXO persistence, provenance, undo, and transactional reorganization prototype.
- `tests/`: unit tests for the above experimental components.
- `docs/`: protocol design, storage behavior, security limitations, and launch gates.

## Run reference tests

Requires Python 3.10+.

    python -m unittest discover -s tests -v

## Important safety notice

Do not use this prototype to store value, accept deposits, advertise an investment, or mine a public network. It is not a functioning public cryptocurrency network. A secure launch requires a complete and frozen protocol, independently reviewed full-node implementation, interoperable consensus tests, secure wallet and key management, P2P and DoS protections, reproducible signed releases, external security review, public testnet operation, incident response, and jurisdiction-specific legal clearance.

No genesis hash, network identifier, address prefix, ports, DNS seeds, exchange listing, market price, or launch date is established by this repository.

## Testnet launch status

BLACKROOT has **not launched a public testnet**. A loopback-only local node CLI and strict JSON configuration loader now exist, but the testnet protocol and genesis are not approved/frozen, block-body sync and full consensus are incomplete, and no public operating infrastructure exists. See [Testnet launch gates](docs/testnet-launch-gates.md) for the verified blockers and required sequence. Testnet coins, if a future testnet is operated, will have no monetary value.

## Mainnet launch status

BLACKROOT is **not ready for mainnet or public sale**. The mandatory engineering, security, operational, and legal launch gates are tracked in [Mainnet launch gates](docs/mainnet-launch-gates.md). Passing unit tests does not satisfy these gates.
