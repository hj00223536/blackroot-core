# BLACKROOT Core

**Status: experimental protocol prototype — not a launched cryptocurrency.**

BLACKROOT is an experimental independent UTXO-chain design. This repository contains reference consensus helpers and prototype components. It is not a production full node, wallet, miner, explorer, audited protocol, or public mainnet.

## Owner-approved monetary design

- Native coin name: BLACKROOT
- Ticker: BRT (provisional; availability and trademark status not established)
- UTXO transaction model
- Proof of Work using double SHA-256 (SHA-256d), subject to independent protocol review
- Target block interval: 600 seconds (provisional)
- Difficulty adjustment interval: 2,016 blocks; normative boundary behavior is not finalized
- Monetary precision: 100,000,000 atomic units per BRT
- Founder genesis allocation: 20,000,000 BRT, intended to be spendable and not time-locked
- Mining allocation: 20,000,000 BRT, scheduled at 10 BRT per block for heights 1 through 2,000,000 inclusive
- Maximum proposed supply: 40,000,000 BRT

The owner-approved subsidy schedule is integrated into the reference consensus helper and is undergoing CI validation. The founder allocation has **not** yet been created in a spendable genesis output. The 40,000,000 BRT limit is not a claim that this amount currently exists or is held in a wallet.

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

No mainnet genesis, exchange listing, market price, or launch date is established by this repository. Earlier network identity/address/port proposals remain provisional until collisions, interoperability and protocol rules are reviewed.

## Protocol freeze register

The unresolved consensus, network-identity, genesis, and independent-review decisions are tracked in the [Protocol-freeze gap register](docs/protocol-freeze-gap-register.md). The register is an engineering checklist, not an activation approval.

## Testnet launch status

BLACKROOT has **not launched a public testnet**. A loopback-only local node CLI and strict JSON configuration loader exist, but the testnet protocol and genesis are not approved/frozen, block-body sync and full consensus are incomplete, and no public operating infrastructure exists. See [Testnet launch gates](docs/testnet-launch-gates.md) for the verified blockers and required sequence. Testnet coins, if a future testnet is operated, will have no monetary value.

## Mainnet launch status

BLACKROOT is **not ready for mainnet or public sale**. The mandatory engineering, security, operational, and legal launch gates are tracked in [Mainnet launch gates](docs/mainnet-launch-gates.md). Passing unit tests does not satisfy these gates.
