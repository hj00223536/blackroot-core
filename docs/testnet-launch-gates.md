# BLACKROOT Testnet launch gates

**Status: NOT LAUNCHED. No public Testnet endpoint or genesis block is currently published.**

The [protocol-freeze gap register](protocol-freeze-gap-register.md) is the controlling checklist for unresolved consensus and network-identity decisions. Every applicable item must be resolved and independently verified before this gate list can be considered complete.

This document is an engineering gate list, not a launch announcement. A testnet must use valueless test coins and must never be presented as a mainnet, investment, exchange asset, or place to deposit funds.

## What exists in this repository

- Experimental SHA-256d header, compact-target, proof-of-work, subsidy, and chainwork helpers.
- An in-memory header-chain prototype and persistent header/UTXO/block-body components.
- TCP/P2P framing, peer management, handshake, header synchronization, and block-body scheduling components.
- Unit and loopback/multi-node integration tests for selected P2P and storage paths, including TCP block-body transfer, active-chain connection, restart/reopen persistence, rejection of a bad-Merkle fork body without UTXO mutation or a leaked request assignment, removal of transaction-invalid fork bodies from the archive after failed activation, and TCP reassignment of outstanding fork-body requests when a peer disconnects.
- A node-runtime wrapper that composes persistent state and a peer manager.

These are reusable prototype components. The CLI now waits for the outbound peer's version/verack handshake before requesting headers, avoiding a startup race. CI exercises both two independent runtime/state instances in one process and a separate-process CLI smoke test: two OS processes start with isolated data directories, connect over loopback TCP, complete the handshake, and report the same genesis and best-chain tip. This is narrowly scoped integration evidence, including a SIGTERM/clean-exit assertion for both CLI processes, not proof of full consensus correctness or public-network readiness. `src/blackroot_node_config.py` now loads strict JSON settings (rejecting missing/unknown fields) and validates explicit testnet identity, message magic, protocol version, genesis header/hash, PoW limit, peer cap, and port. It rejects production-like network names, mismatched genesis hashes, invalid PoW, and non-loopback listener hosts. `python -m src.blackroot_node` opens coordinated SQLite state and starts the P2P listener on a literal loopback address only. This is a local prototype runner: it does not yet provide a complete block-sync/full-consensus node or public networking.

## Verified SQLite recovery evidence

Distinct tests now cover transaction-level rollback on an invalid replacement branch (`tests/test_reorg_atomicity.py`); abrupt child-process exit with an uncommitted SQLite transaction and recovery of the last committed state (`tests/test_sqlite_crash_recovery.py`); abrupt exit during the real `UTXOStore.reorganize_to_best()` path, followed by exact row comparisons across `blocks`, `block_transactions`, `block_undo_spent`, `block_undo_created`, `utxos`, `block_bodies`, and `metadata`, plus `verify_integrity()` (`tests/test_reorg_process_crash_recovery.py`); and SQLite online backup/restore validation (`tests/test_sqlite_online_backup.py`).

The process-crash reorganization test passed in [GitHub Actions run 45650626286](https://github.com/hj00223536/blackroot-core/actions/runs/45650626286), with 373 unit tests reported. This is evidence for these local SQLite failure cases only; it does not prove power-loss durability across filesystems, backup scheduling/retention, disaster-recovery operations, or production database safety. The later cross-version regression run [45719548101](https://github.com/hj00223536/blackroot-core/actions/runs/45719548101) completed successfully on Python 3.12 and 3.13 with 382 tests on each interpreter, including rejection of a coinbase overpayment before persistent state mutation; its full job logs contain no `ResourceWarning` or `unclosed database` matches. This remains CI evidence for the tested paths, not a completed independent audit or public-network release gate. The separate three-node TCP body-sync test in [run 45720357124](https://github.com/hj00223536/blackroot-core/actions/runs/45720357124) also completed successfully on Python 3.12 and 3.13 with 382 tests per interpreter. It uses three independent persistent node states, checks identical UTXO rows after synchronization, then reopens both destination databases and verifies their active tips and stored block bodies. This is focused loopback integration evidence, not a complete adversarial network or consensus audit. A subsequent TCP reorganization regression test constructs a higher-work fork whose height-3 coinbase claims one atomic unit above the allowed subsidy, requests all fork bodies over the peer service, and verifies rejection leaves the active tip and exact UTXO rows unchanged, removes the invalid fork bodies from the archive, and passes the store integrity check. [GitHub Actions run 45720525461](https://github.com/hj00223536/blackroot-core/actions/runs/45720525461) completed successfully on Python 3.12 and 3.13 with 383 tests on each; the SQLite resource-warning check exited 0 on both jobs. This is a targeted local regression test, not proof against all malformed blocks, network attacks, or consensus failures. A first attempt to replace a fixed sleep with an assertion that all three bodies were simultaneously archived failed on both Python versions: the implementation validates the final body synchronously and discards the invalid branch before the test can observe all bodies archived together. The test was corrected in [commit da41762](https://github.com/hj00223536/blackroot-core/commit/da4176280290d15a912817550545ba5a6f427169) to wait until all three block bodies have actually been served over TCP, then observe request release and archive cleanup. The same test module also exercises reassignment of outstanding fork-body requests after a peer disconnects, followed by successful activation of the downloaded branch. The corrected code passed CI in [run 45721377676](https://github.com/hj00223536/blackroot-core/actions/runs/45721377676) on Python 3.12 and 3.13: 383 tests on each interpreter, both jobs successful, and SQLite resource-warning checks exited 0. The subsequent current-main documentation/denomination commit was also tested in [run 45721544090](https://github.com/hj00223536/blackroot-core/actions/runs/45721544090), with 383 tests and a zero SQLite resource-warning-check exit code on each interpreter. This confirms the tested regression paths only; it is not proof against all malformed blocks, network attacks, or consensus failures.

A further persistent-state regression test now activates one branch, stores a competing greater-work branch, closes the coordinated SQLite state, reopens it, and verifies the selected header tip, UTXO tip/count, integrity check, and cleared recovery journal. The accompanying three-independent-header-chain convergence test was corrected to add side branches through `add_to_branch()` rather than the best-tip-only `add()` method. [GitHub Actions run 45726797882](https://github.com/hj00223536/blackroot-core/actions/runs/45726797882) completed successfully on Python 3.12 and 3.13 with 395 tests on each interpreter; both SQLite resource-warning checks exited 0. The Node.js 22 genesis, transaction-serialization, and P2PKH signature vectors also passed. This is additional regression evidence for the covered local restart/reorganization and header-convergence paths, not an external audit or proof of public-network safety.

## Provisional consensus decisions

The current helper and header-chain behavior, including retarget boundaries, compact-target precision, timestamp handling, branch tie-breaks, subsidy arithmetic, and unsupported script scope, is recorded in [docs/consensus-decisions.md](consensus-decisions.md). These are implementation observations and unresolved protocol choices, not frozen network rules. Resolve and independently test them before activating a testnet.

## Independent retarget arithmetic regression evidence

A standalone Node.js 22 verifier now checks compact-target retarget arithmetic against fixed clamp vectors and the current first-boundary convention. The test runs in CI independently of Python. This is useful cross-language regression coverage, but it does not freeze the first-period consensus rule or satisfy the separately maintained external-client requirement below.

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
- [x] Reproduce the current candidate transaction/header/hash/PoW vector in a separate Node.js implementation using only built-in crypto and byte primitives; CI runs it independently of the Python reference code. This is cross-language repository evidence, not an external client or audit.
- [x] Add a Node.js 22 cross-language legacy transaction vector check for serialization, txid, CompactSize canonicality, truncation, and trailing-byte rejection. This is in-repository regression evidence only.
- [x] Add a Node.js P2PKH/SIGHASH_ALL regression vector checking HASH160, low-S DER ECDSA verification, modified-transaction rejection, and high-S rejection. This is in-repository cross-language evidence only; it is not a production cryptographic implementation or external audit.
- [ ] Reproduce every final, frozen vector in a separately maintained external client.
- [ ] Decide and test whether the genesis output is unspendable.

Do not invent or manually select a genesis hash. Until this gate passes, nodes cannot safely identify the same chain.

### 3. Build a runnable node application
- [x] Add a documented local-only CLI/entry point that constructs persistent state, peer manager, runtime, and sync services. Full chain activation remains blocked pending approved genesis/network parameters.
- [ ] Add schema versioning and migration policy to the strict JSON configuration loader; currently it rejects unknown/missing fields but has no migration framework.
- [ ] Implement supervised task lifecycle, retry scheduling, graceful shutdown, restart behavior, and useful structured logs.
- [ ] Provide a local-only status interface; bind administrative/RPC interfaces to loopback by default.
- [x] Add exclusive POSIX data-directory process locking to the loopback CLI; automated tests cover contention, release, abrupt owner termination, and CLI-level rejection of a second process. Schema/version handling, backup/restore operations, and safe reset commands remain separate work.
- [x] Add a smoke test that starts two independent OS processes, connects them over loopback TCP, and checks matching genesis and best-chain tip. This covers CLI startup and handshake only; full block synchronization and consensus remain incomplete.

### 4. Complete and harden protocol behavior
- [ ] Finish block/header validation and ensure every state mutation follows validated best-chain selection.
- [x] Header synchronization fails closed if no clock provider is configured; the local CLI explicitly supplies its system UTC clock as a provisional future-time bound. A public network still needs a reviewed network-adjusted peer-time policy.
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
| Genesis | Deterministic candidate vector is checked by Python tests and a separate Node.js verifier in CI; no approval, frozen network parameters, or separately maintained external client reproduction | PARTIAL / BLOCKED |
| Network identity and parameters | Explicit in-code config validator exists; no reviewed constants or file loader | PARTIAL / BLOCKED |
| Node application/CLI | Loopback-only local CLI and strict JSON loader exist; block-body sync/full consensus and supervised retry lifecycle remain incomplete | PARTIAL / BLOCKED |
| P2P building blocks | TCP transport, peer manager, handshake and sync components exist | PROTOTYPE |
| Integration coverage | Three independent persistent nodes sync a block over TCP, compare UTXO rows and survive destination restart; separate two-process CLI handshake/genesis smoke test | PARTIAL |
| Full consensus | Several rules and script semantics remain explicitly incomplete | BLOCKED |
| Wallet/miner | No production wallet or miner application | BLOCKED |
| Public operations | No verified public nodes, seeds, monitoring or release process | BLOCKED |

## Launch decision

**Do not announce or expose a public testnet yet.** The immediate engineering sequence is: freeze a testnet-only specification; implement and independently reproduce genesis; build a runnable node CLI/configuration; then pass a multi-process network smoke test and the remaining security gates.

Passing the existing unit suite is useful regression evidence, but it does not satisfy these launch gates.


## Node data-directory process lock

The loopback CLI now acquires an exclusive POSIX `flock` on
`.blackroot-node.lock` inside its resolved data directory before opening the
coordinated SQLite database. A second CLI process using the same directory is
rejected; the kernel releases the advisory lock when the owner exits, including
after abrupt process termination. The lock file is intentionally retained to
avoid unlink/recreate races. Automated tests cover competing owners, clean
release, and kernel release after killing the owner process. This protects the
CLI entry point only: callers that construct persistent stores directly must
provide their own single-writer discipline, and this mechanism has not been
validated on non-POSIX platforms. The end-to-end CLI contention regression
passed in [GitHub Actions run 45724969798](https://github.com/hj00223536/blackroot-core/actions/runs/45724969798): Python 3.12 and 3.13 each ran 388 tests successfully, and the Node.js 22 genesis, transaction, and P2PKH vectors passed.

## Latest cross-version CI verification (2026-11-26)

The documentation/evidence update at commit
`693a59ff387f7540a8302bc7df451580f767bf65` was itself validated by
[GitHub Actions run 45727313138](https://github.com/hj00223536/blackroot-core/actions/runs/45727313138):
the Python 3.12 and Python 3.13 jobs both completed successfully, each
reported 395 passing unit tests and test-process exit code 0, and the Node.js
22 independent genesis-candidate verifier reported PASS. The preceding
workflow-timeout configuration commit was also validated by
[run 45727076855](https://github.com/hj00223536/blackroot-core/actions/runs/45727076855),
with all three jobs successful. These results confirm the checked-in
regression suite and in-repository cross-language candidate vector only;
they do not resolve the protocol decisions, provide an external client, or
satisfy the public-testnet activation gates.

## Cumulative issuance ledger regression evidence (2026-11-26)

The schema-v5 UTXO store records the consensus subsidy budget per active-chain
block, counts trusted pre-chain bootstrap outputs against the same supply cap,
and removes/rebuilds block issuance rows as the active branch disconnects or
reorganizes. Fees are excluded from newly issued subsidy. Integrity checks
compare each persisted block budget against the consensus subsidy schedule.
Schema-v5 preflight verifies the issuance column and bootstrap metadata; older
active stores are refused rather than assigned an invented historical total.

The complete schema-v5 fixture and issuance regression changes passed
[GitHub Actions run 45825892104](https://github.com/hj00223536/blackroot-core/actions/runs/45825892104):
Python 3.12 and 3.13 each completed 428 tests successfully, and the independent
Node.js 22 genesis verifier passed. This remains regression evidence for the
implemented storage paths, not a production consensus audit or authorization
to issue founder coins. The current genesis candidate still contains no founder
allocation, and the network is not launched.
