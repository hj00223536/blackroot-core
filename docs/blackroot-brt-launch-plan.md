# BLACKROOT (BRT) Launch Preparation Plan

**Project status: experimental prototype. No public testnet or mainnet is launched.**

This plan records the owner's selected direction: an independent blockchain named BLACKROOT with provisional ticker **BRT**. Ticker availability, trademarks, and legal permission have not been verified. This document is not a launch announcement, investment offer, or promise of value.

## Identity and provisional design

- Chain name: BLACKROOT
- Native ticker: BRT (provisional)
- Architecture: independent UTXO blockchain
- Proposed consensus: proof-of-work, SHA-256d (subject to protocol review)
- Target block interval: 10 minutes (provisional)
- Proposed total supply: 40,000,000 BRT
- Proposed founder allocation: 20,000,000 BRT (50%), intended to be spendable and not time-locked
- Proposed mining allocation: 20,000,000 BRT (50%), to be emitted under a yet-to-be-specified reward schedule
- No cash liquidity pool is funded or promised at this stage.
- The previous 21,000,000 BRT supply and 50 BRT / 210,000-block subsidy model are superseded as the owner's selected design direction, but remain the current prototype constants until a reviewed consensus change is implemented.
- The allocation proposal is recorded in [docs/blackroot-brt-monetary-policy-proposal.md](blackroot-brt-monetary-policy-proposal.md). It is not yet active in consensus, genesis, or any wallet.
- These monetary and consensus parameters are not frozen; do not rely on them until the normative specification and test vectors are reviewed and approved.

## Release stages

### Stage 0 — Prototype integrity (current)
- [ ] Complete cross-version CI and resolve reproducible warnings.
- [ ] Establish a clean reproducible test report and release candidate commit.
- [ ] Review SQLite lifecycle, migration, backup, recovery, and data-directory locking.
- [ ] Document known limitations and threat model.

### Stage 1 — Protocol freeze
- [ ] Normative specification covering serialization, transaction/script rules, signatures, block validation, retargeting, time rules, fees, upgrades, network magic, address encoding, and limits.
- [ ] Normative monetary specification for the 40,000,000 BRT proposal, including founder genesis allocation, mining reward curve, exact cumulative cap, rounding, and coinbase/genesis spend rules.
- [ ] Testnet identity and genesis generated deterministically from reviewed inputs.
- [ ] Genesis/header/transaction vectors reproduced by an independent implementation.
- [ ] Freeze testnet parameters; resets must create a new network identity.

### Stage 2 — Full node and interoperability
- [ ] Complete validation-before-state-mutation path.
- [ ] Full block synchronization and fork/reorganization behavior.
- [ ] P2P peer discovery, rate limits, DoS protections, adversarial tests.
- [ ] Two independent node implementations or a second independent consensus-vector implementation.
- [ ] Wallet functionality, secure key generation, signing, backup and recovery vectors.
- [ ] Mining implementation and deterministic genesis verification.
- [ ] Structured logs, status interface bound to localhost, safe shutdown, data locks, schema migration.

### Stage 3 — Public testnet
- [ ] Independent security review and remediation.
- [ ] Fuzzing, property tests, fault injection, multi-node tests.
- [ ] Reproducible builds, dependency pinning, signed release artifacts.
- [ ] Public testnet operations, monitoring, incident response, documented reset policy.
- [ ] Clearly state test coins are valueless; do not solicit funds or sell coins.

### Stage 4 — Mainnet decision
- [ ] Complete independent audit of consensus, cryptography, wallet, and networking.
- [ ] Operational readiness: monitoring, backups, recovery drills, signed releases, key-management policy, upgrade governance.
- [ ] Qualified Iraqi legal advice and review of applicable CBI, licensing, AML/CFT, tax, consumer, and marketing rules.
- [ ] Publish transparent supply, mining, governance, upgrade, risk, and incident policies.
- [ ] Public testnet stability period and published results.
- [ ] Explicit release approval; no date until all blockers are closed.

## Launch rule

Do not deploy a mainnet genesis, advertise a market value, accept deposits, sell tokens, or ask users to entrust funds until every blocker above is independently verified and approved. Unit-test success alone is not launch readiness. A spendable founder allocation is not cash liquidity and does not guarantee buyers, exchange access, or a market price.
