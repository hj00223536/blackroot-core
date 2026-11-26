# BLACKROOT security architecture and threat model

**Status: DESIGN PROPOSAL — not a consensus specification, not an approval of new protocol parameters, and not a launch authorization.**

## Objective

Build an independently operated, independently verifiable blockchain whose security claims are supported by reproducible evidence. The project may aim to outperform Bitcoin on specific measurable properties, but it must not claim general superiority without comparative, independently reviewed evidence.

The architecture should preserve open participation in validation and mining as the default design goal. Any change to that goal, consensus rules, monetary policy, network identity, or cryptographic primitives requires explicit owner review before implementation.

## Security properties

1. **Consensus integrity:** honest fully validating nodes derive the same valid chain from the same rules and accepted history.
2. **Issuance integrity:** no block, bootstrap path, reorganization, or storage recovery path can create value outside the approved issuance schedule.
3. **Authorization integrity:** only valid transaction witnesses/scripts authorize spending; unsupported script forms fail closed.
4. **State integrity:** invalid blocks and failed reorganizations do not partially mutate the active UTXO set or durable chain state.
5. **Network resilience:** malformed, replayed, oversized, slow, or abusive peer traffic cannot bypass validation or exhaust unbounded resources.
6. **Key safety:** wallet secrets remain local to the owner-controlled wallet boundary and never enter logs, CI, repository history, or node telemetry.
7. **Operational recoverability:** operators can detect corruption, restore verified backups, upgrade safely, and coordinate emergency response without silently changing consensus.

## Threat model

| Threat | Required defense and evidence |
|---|---|
| Invalid proof of work, timestamp, difficulty, or chain linkage | One normative header-validation path; negative vectors; independently maintained client reproduces every rule. |
| Inflation through overpaid coinbase, duplicate spends, or reorganization | Full block validation before state mutation; issuance ledger invariants; adversarial reorg tests; durable rollback tests. |
| Script or signature malleability / parser disagreement | Complete, versioned script specification; strict canonical parsing; independent cryptographic implementation and external review. |
| Eclipse, Sybil, or malicious peer behavior | Peer diversity policy, authenticated/validated chain data, bounded requests, peer scoring and backoff; multi-operator network tests. |
| DoS through oversized or pathological messages | Per-message and aggregate resource budgets, bounded queues, timeouts, concurrency limits, fuzzing, and load tests. |
| Clock manipulation | Explicit network time policy, trusted-clock threat analysis, deterministic boundary vectors, and enforcement at every admission path. |
| Database crash, corruption, or rollback | Atomic state transitions where supported, journal recovery tests, verified backup/restore drills, corruption detection, and operator runbooks. |
| Compromised release or dependency | Pinned dependencies, reproducible builds, signed artifacts, independent release verification, and documented key rotation/revocation. |
| Founder-key compromise or unauthorized genesis | No secret in source control; immutable owner-approved genesis manifest; independently verified output and one-time issuance authorization. |

## Layered architecture

### 1. Consensus and validation boundary

- Keep header validation, difficulty, timestamps, transaction validation, scripts, and issuance rules in a small normative consensus core.
- Require every network-delivered block to pass the same validation path before it can affect active state.
- Keep storage primitives private to the validated node-state boundary wherever practical.
- Treat test helpers, unchecked modes, compatibility constructors, and bootstrap primitives as non-production capabilities.
- Freeze byte-level rules only after independent implementation and review.

### 2. Peer-to-peer boundary

- Treat every peer message as hostile input, including messages from previously connected peers.
- Enforce bounded framing, parsing, outstanding requests, queue depth, connection count, and processing time.
- Separate peer discovery from consensus trust: peer identity or reputation must never make invalid consensus data valid.
- Test disconnects, stale requests, duplicate announcements, conflicting branches, slow peers, and malformed payloads.

### 3. Wallet and key boundary

- Keep signing keys in a separate wallet process or isolated wallet component, not in the public node networking process.
- Prefer audited, maintained cryptographic libraries over bespoke signing implementations.
- Require explicit transaction review, address/network checks, backup and restore drills, and safe handling of recovery material.
- Never ask users to disclose private keys, passwords, or recovery phrases.

### 4. Persistence and recovery boundary

- Commit header selection, validated block data, UTXO changes, and recovery metadata under a clearly specified transaction protocol.
- Distinguish true single-database atomicity from recoverable multi-file coordination.
- Exercise failures before, during, and after each durable write and during restart reconciliation.
- Verify restored state against independently derived chain and UTXO invariants.

### 5. Release and governance boundary

- Publish versioned specifications, test vectors, source commits, build instructions, and signed release checksums.
- Require independent review for consensus and cryptography changes.
- Define key rotation, vulnerability disclosure, emergency pause/upgrade authority, and transparent incident reporting before public operation.
- Do not let an emergency software release silently rewrite monetary or consensus history.

## Required verification program

1. **Differential consensus testing:** a separately maintained implementation must reproduce valid and invalid header, difficulty, transaction, script, serialization, and genesis vectors.
2. **Property testing:** exercise serialization round trips, canonical encodings, UTXO conservation, issuance bounds, and chainwork ordering over generated inputs.
3. **Fuzzing:** fuzz every parser and network message handler; retain minimized regression cases for every discovered defect.
4. **Adversarial network testing:** run independently administered nodes with partitions, latency, peer churn, malformed messages, competing forks, and resource exhaustion attempts.
5. **State-transition testing:** inject failures at every persistence boundary; verify no invalid state becomes active and restart recovery is deterministic.
6. **Wallet security review:** review signing, address derivation, transaction display, backup, restore, and secret isolation independently.
7. **Operational rehearsal:** test signed upgrades, rollback policy, backup restoration, incident communication, and vulnerability response.
8. **External review:** obtain written consensus, cryptography, networking, and operational reviews; track findings to verified fixes.

## Current repository status

The repository currently contains useful prototypes for header/PoW helpers, block transaction accounting, a restricted legacy P2PKH verifier, persistent UTXO/header storage, P2P synchronization, and selected CI/loopback/crash-recovery tests. These are engineering building blocks, not a complete production node.

Known release blockers include incomplete Script support, unresolved consensus and time-policy decisions, lack of a separately maintained external client, incomplete peer-discovery and adversarial-network defenses, no production wallet/miner, incomplete genesis authorization, and no external security audit. The controlling details remain in [the protocol-freeze gap register](protocol-freeze-gap-register.md) and [the testnet launch gates](testnet-launch-gates.md).

## Non-goals and explicit safeguards

- This document does not select new consensus values, cryptographic algorithms, network identifiers, ports, or monetary rules.
- It does not authorize a founder output, genesis activation, testnet, mainnet, public endpoint, or real-value transfer.
- It does not promise a price, listing, liquidity, mining profitability, or superiority to Bitcoin.
- Testnet coins, if a future testnet is separately approved, must be valueless and clearly labeled.

## Acceptance rule

A security property is not considered complete because a design document or unit test exists. It requires: a normative rule, a negative test, an independently reproduced test vector where applicable, review of every production entry point, and documented operational evidence. Unresolved findings remain visible blockers; they must not be relabeled as complete to meet a launch date.
