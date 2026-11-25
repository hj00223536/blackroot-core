# BLACKROOT Testnet Protocol v0.1 — engineering draft

**Status: DRAFT / NOT NORMATIVE / NOT ACTIVATED.**
This document inventories repository behavior and unresolved decisions. It does not freeze consensus, approve the genesis candidate, or authorize public networking. A node implementation MUST NOT treat any value marked TBD or provisional as a launch parameter.

## 1. Identity and scope

| Field | Current record | Status |
|---|---|---|
| Chain name | BLACKROOT | Project name |
| Asset ticker | BRT | Provisional; legal/trademark availability unchecked |
| Ledger model | UTXO | Prototype |
| Network identifier | TBD | Must be unique and versioned |
| P2P message magic | TBD (4 bytes required by config) | Must be unique; all-zero rejected |
| P2P protocol version | TBD (positive integer required) | Must be frozen |
| Address prefixes/checksum | TBD | No public addresses |
| P2P port | TBD | Local prototype only |
| Listener policy | Literal loopback only | Current CLI/config safety boundary |

The current configuration object validates explicitly supplied network identity, message magic, protocol version, genesis header/hash, PoW limit, peer count, payload size, and port. It does not select canonical values. Do not invent values to fill the TBD fields.

## 2. Block header encoding (implementation record)

The reference header encoder currently uses an 80-byte layout:

1. version: uint32 little-endian.
2. prev_hash: 32 bytes in wire/internal order.
3. merkle_root: 32 bytes in wire/internal order.
4. timestamp: uint32 little-endian Unix seconds.
5. bits: uint32 little-endian compact target.
6. nonce: uint32 little-endian.

The header identifier is SHA256(SHA256(serialized_header)); display formatting reverses the digest bytes. These are current implementation facts and still require inclusion in a reviewed normative specification with cross-client vectors.

## 3. Proof of work and chain selection

- Hash function: SHA-256d (current implementation).
- Compact target decoding rejects invalid/non-canonical encodings and targets above the configured PoW limit.
- Header-chain prototype accumulates work and selects the branch with greatest accumulated work.
- Median-time-past and a fixed retarget schedule are represented in the prototype.

Not frozen: canonical PoW limit, retarget interval and exact boundary formula, clamping, minimum-difficulty exceptions, timestamp future bound/peer clock adjustment, and activation/versioning rules. The current draft target interval of 600 seconds and retarget interval of 2,016 blocks are design targets only.

## 4. Candidate genesis (not activated)

See docs/testnet-genesis-candidate.md. The recorded candidate uses timestamp 1795564800, header version 1, null previous hash, compact target 0x207fffff, nonce 0, a 63-byte legacy transaction with a zero-value OP_RETURN output, and the recorded txid/header/hash vectors.

This candidate is only a regression vector. Its easy target is unsuitable for public mining. It has not been approved as a network constant or reproduced by an independently maintained external client. Genesis identity, chain ID, message magic, address encoding, and reset policy remain TBD.

## 5. Transactions, scripts, and monetary rules

The repository contains transaction serialization, UTXO transition, script/signature checks, coinbase subsidy, maturity, absolute locktime, and relative sequence-lock components with tests. This draft does not claim full consensus completeness.

The following require normative definitions and independent vectors before activation:
- transaction versioning, canonical serialization, txid/wtxid rules and witness policy;
- signature hash preimages, supported algorithms, sighash flags and script semantics;
- script limits, standard/consensus distinction, unknown opcode behavior;
- input/output/value bounds, fee accounting and coinbase subsidy-plus-fees;
- coinbase script constraints and maturity;
- absolute and relative locktime edge cases and authenticated time/height provenance;
- block weight/size, transaction count, sigops and all resource limits;
- mempool policy (which must be distinguished from consensus).

Provisional economic targets in docs/blackroot-brt-launch-plan.md are not frozen: 50 BRT initial subsidy, 210,000-block halving, 100,000,000 atomic units per BRT, 21,000,000 BRT ceiling, and no premine proposed. The current integer-truncated subsidy schedule, summed over all 64 halving epochs, issues 2,099,999,997,690,000 atomic units (20,999,999.9769 BRT); the remaining 2,310,000 atomic units (0.0231 BRT) below the nominal 21,000,000 BRT ceiling are never issued by this schedule. The subsidy is 1 atomic unit per block in epoch 32 and zero from epoch 33 onward. This arithmetic is now pinned by a unit-test vector, but the monetary rules remain provisional and require independent review before activation.

## 6. State transition and reorganization

The codebase includes persistent header, UTXO, block-body, undo, recovery-journal and coordinated SQLite components. Tests cover selected rollback, restart, crash-recovery and reorganization cases.

Before activation, the specification must define:
- validation order and the exact point at which state mutation is permitted;
- chainwork tie-breaking and fork-choice behavior;
- atomic connect/disconnect and recovery after process/power failure;
- database schema/version migration and mandatory reindex behavior;
- pruning/archive retention and backup/restore invariants.

A passing unit suite is not a substitute for fault-injection, independent implementation, and operational recovery review.

## 7. P2P and security

The repository has bounded message framing, version/verack handshake, TCP sessions, peer management, header synchronization, and selected block-body synchronization tests. The current handshake is not cryptographic peer authentication. The local runner is loopback-only.

Still TBD or incomplete: peer discovery/bootstrap, authenticated transport policy, Sybil/eclipse resistance, peer scoring/bans/backoff, rate limits, per-command limits, timeout policy, request accounting, adversarial interoperability, fuzzing, long-running multi-process behavior, and public incident response.

## 8. Required activation gates

No public testnet activation until all of the following are approved and evidenced:
1. Versioned normative spec with every consensus parameter resolved.
2. Unique network ID, message magic, address prefixes, ports and protocol version.
3. Final deterministic genesis reproduced by a separately maintained implementation.
4. Full block/body/script/UTXO validation and safe fork/reorg behavior.
5. Multi-process sync and convergence across independent implementations.
6. Peer DoS protections, fuzz/property tests and external security review.
7. Reproducible builds, signed releases, monitoring, backup/restore drills, reset and incident policies.
8. Public documentation that test coins have no monetary value.

Mainnet requires a separate decision gate, independent audit, sustained public testnet evidence, operational readiness, and qualified legal review in Iraq. No deposits, sales, fundraising, or value claims are authorized by this draft.
