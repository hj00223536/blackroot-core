# BLACKROOT Testnet launch gates

**Status: NOT LAUNCHED. No public Testnet endpoint or genesis block is currently published.**

This document is an engineering gate list, not a launch announcement. A testnet must use valueless test coins and must never be presented as a mainnet, investment, exchange asset, or place to deposit funds.

## What exists in this repository

- Experimental SHA-256d header, compact-target, proof-of-work, subsidy, and chainwork helpers.
- An in-memory header-chain prototype and persistent header/UTXO/block-body components.
- TCP/P2P framing, peer management, handshake, header synchronization, and block-body scheduling components.
- Unit and loopback/multi-node integration tests for selected P2P and storage paths.
- A node-runtime wrapper that composes persistent state and a peer manager.

These are reusable prototype components. They do not, by themselves, constitute a runnable, interoperable public full node.

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
- [ ] Add a documented CLI/entry point that constructs the testnet chain, persistent state, peer manager, runtime, and sync services.
- [ ] Add explicit testnet configuration loading and reject unknown or mainnet-like network settings.
- [ ] Implement supervised task lifecycle, retry scheduling, graceful shutdown, restart behavior, and useful structured logs.
- [ ] Provide a local-only status interface; bind administrative/RPC interfaces to loopback by default.
- [ ] Add data-directory locking, schema/version handling, backup/restore instructions, and safe reset commands.
- [ ] Add a smoke test that starts two independent processes, connects them over TCP, and proves they converge on the same genesis and best-chain tip.

### 4. Complete and harden protocol behavior
- [ ] Finish block/header validation and ensure every state mutation follows validated best-chain selection.
- [ ] Finish side-branch body retrieval, reorganization, and recovery semantics.
- [ ] Add peer scoring, connection limits, timeouts, bans/backoff, request limits, message-size limits, and DoS protections.
- [ ] Define peer discovery and bootstrap policy; do not publish seed addresses until operators have agreed to run nodes.
- [ ] Add adversarial interoperability, fuzz, property, and long-running multi-process tests.
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
| Genesis | `docs/genesis.md` says it has not been generated | BLOCKED |
| Network identity and parameters | No frozen testnet constants/configuration | BLOCKED |
| Node application/CLI | Runtime building block exists; no runnable application entry point is present in the repository tree | BLOCKED |
| P2P building blocks | TCP transport, peer manager, handshake and sync components exist | PROTOTYPE |
| Integration coverage | Loopback and multi-node tests exist | PARTIAL |
| Full consensus | Several rules and script semantics remain explicitly incomplete | BLOCKED |
| Wallet/miner | No production wallet or miner application | BLOCKED |
| Public operations | No verified public nodes, seeds, monitoring or release process | BLOCKED |

## Launch decision

**Do not announce or expose a public testnet yet.** The immediate engineering sequence is: freeze a testnet-only specification; implement and independently reproduce genesis; build a runnable node CLI/configuration; then pass a multi-process network smoke test and the remaining security gates.

Passing the existing unit suite is useful regression evidence, but it does not satisfy these launch gates.
