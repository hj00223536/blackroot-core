# BLACKROOT Testnet launch gates

**Status: NOT LAUNCHED. No public Testnet endpoint or genesis block is currently published.**

This document is an engineering gate list, not a launch announcement. A testnet must use valueless test coins and must never be presented as a mainnet, investment, exchange asset, or place to deposit funds.

## What exists in this repository

- Experimental SHA-256d header, compact-target, proof-of-work, subsidy, and chainwork helpers.
- An in-memory header-chain prototype and persistent header/UTXO/block-body components.
- TCP/P2P framing, peer management, handshake, header synchronization, and block-body scheduling components.
- Unit and loopback/multi-node integration tests for selected P2P and storage paths, including TCP block-body transfer, active-chain connection, restart/reopen persistence, rejection of a bad-Merkle fork body without UTXO mutation or a leaked request assignment, removal of transaction-invalid fork bodies from the archive after failed activation, and TCP reassignment of outstanding fork-body requests when a peer disconnects.
- A node-runtime wrapper that composes persistent state and a peer manager.

These are reusable prototype components. The CLI now waits for the outbound peer's version/verack handshake before requesting headers, avoiding a startup race. CI exercises both two independent runtime/state instances in one process and a separate-process CLI smoke test: two OS processes start with isolated data directories, connect over loopback TCP, complete the handshake, and report the same genesis and best-chain tip. This is narrowly scoped integration evidence, including a SIGTERM/clean-exit assertion for both CLI processes, not proof of full consensus correctness or public-network readiness. `src/blackroot_node_config.py` now loads strict JSON settings (rejecting missing/unknown fields) and validates explicit testnet identity, message magic, protocol version, genesis header/hash, PoW limit, peer cap, and port. It rejects production-like network names, mismatched genesis hashes, invalid PoW, and non-loopback listener hosts. `python -m src.blackroot_node` opens coordinated SQLite state and starts the P2P listener on a literal loopback address only. This is a local prototype runner: it does not yet provide a complete block-sync/full-consensus node or public networking.

## Mandatory gates before a public testnet

### 1. Freeze a separate testnet protocol
- [ ] Publish a normative testnet specification and version it.
- [ ] Define a unique testnet network identifier and message-start/magic bytes, distinct from any future mainnet.
- [ ] Define testnet-only address/version prefixes, ports, protocol version, message limits, and peer policy.
- [ ] Freeze serialization, genesis transaction/header byte order, proof-of-work limit, retarget boundary behavior, timestamp rules, and all block-validation rules.
- [ ] Define reset policy: a reset creates a new network identifier/genesis and is announced as a breaking change.

### 2. Generate and independently verify genesis
- [ ] Choose and review the exact timestamp and coinbase message.
- [ ] Implement deterministic genesis coinbase serialization using the final transaction format.
- [ ] Compute and freeze the merkle root, initial target, nonce, serialized header, and block hash.
- [ ] Add immutable test vectors to CI.
- [ ] Reproduce every vector in a second independent implementation.
- [ ] Decide and test whether the genesis output is unspendable.

Do not invent or manually select a genesis hash. Until this gate passes, nodes cannot safely identify the same chain.

### 3. Build a runnable node application
- [x] Add a documented local-only CLI/entry point that constructs persistent state, peer manager, runtime, and sync services. Full chain activation remains blocked pending approved genesis/network parameters.
- [ ] Add schema versioning and migration policy to the strict JSON configuration loader; currently it rejects unknown/missing fields but has no migration framework.
- [ ] Implement supervised task lifecycle, retry scheduling, graceful shutdown, restart behavior, and useful structured logs.
- [ ] Provide a local-only status interface; bind administrative/RPC interfaces to loopback by default.
- [ ] Add data-directory locking, schema/version handling, backup/restore instructions, and safe reset commands.
- [x] Add a smoke test that starts two independent OS processes, connects them over loopback TCP, and checks matching genesis and best-chain tip. This covers CLI startup and handshake only; full block synchronization and consensus remain incomplete.

### 4. Complete and harden protocol behavior
- [ ] Finish block/header validation and ensure every state mutation follows validated best-chain selection.
- [ ] Finish side-branch body retrieval, reorganization, and recovery semantics.
- [ ] Add peer scoring, connection limits, timeouts, bans/backoff, request limits, message-size limits, and DoS protections.
- [ ] Define peer discovery and bootstrap policy; do not publish seed addresses until operators have agreed to run nodes.
- [ ] Add adversarial interoperability, fuzz, property, and long-running multi-process tests.
- [x] Enforce legacy absolute nLockTime finality and BIP68 height-based relative sequence locks using authenticated UTXO creation heights.
- [x] Persist authenticated UTXO creation MTP in schema v3 and undo records; enforce BIP68 timestamp-based relative locks at 512-second granularity, with missing metadata rejected. Schema-v2 databases require a verified reindex from genesis.
- [ ] Document unsupported transaction/script features and reject them deterministically.

### 5. Release and operate the testnet
- [ ] Pin dependencies and produce reproducible, platform-specific builds.
- [ ] Publish checksums and signed release artifacts with a documented key-verification process.
- [ ] Operate at least three independently administered nodes through a sustained public test period.
- [ ] Publish monitoring, incident response, upgrade, backup, reset, and vulnerability-reporting procedures.
- [ ] Publish a faucet only after anti-abuse controls and a no-value warning are in place.
- [ ] State clearly that testnet coins have no monetary value and must not be sold.

## Current blocker assessment

| Area | Repository evidence | Status |
|---|---|---|
| Genesis | Deterministic candidate vector and two repository-level byte/hash checks exist; no approval or external client reproduction | PARTIAL / BLOCKED |
| Network identity and parameters | Explicit in-code config validator exists; no reviewed constants or file loader | PARTIAL / BLOCKED |
| Node application/CLI | Loopback-only local CLI and strict JSON loader exist; block-body sync/full consensus and supervised retry lifecycle remain incomplete | PARTIAL / BLOCKED |
| P2P building blocks | TCP transport, peer manager, handshake and sync components exist | PROTOTYPE |
| Integration coverage | TCP loopback block-body transfer, restart/reopen persistence, bad-Merkle rejection, and separate two-process CLI handshake/genesis smoke test | PARTIAL |
| Full consensus | Several rules and script semantics remain explicitly incomplete | BLOCKED |
| Wallet/miner | No production wallet or miner application | BLOCKED |
| Public operations | No verified public nodes, seeds, monitoring or release process | BLOCKED |

## Launch decision

**Do not announce or expose a public testnet yet.** The immediate engineering sequence is: freeze a testnet-only specification; implement and independently reproduce genesis; build a runnable node CLI/configuration; then pass a multi-process network smoke test and the remaining security gates.

Passing the existing unit suite is useful regression evidence, but it does not satisfy these launch gates.
