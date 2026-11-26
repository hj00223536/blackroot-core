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
- Owner-approved mining allocation: 20,000,000 BRT (50%), scheduled at 10 BRT per block for heights 1 through 2,000,000 inclusive
- No cash liquidity pool is funded or promised at this stage.
- The previous 21,000,000 BRT supply and 50 BRT / 210,000-block subsidy model have been replaced in the reference consensus subsidy helper by the owner-approved 40,000,000 BRT schedule.
- CI run 45731576058 passed: Python 3.12, Python 3.13, and independent Node.js 22 genesis/vector checks all succeeded. This is a test-suite result, not a complete protocol audit. The 20,000,000 BRT founder output is not yet present in genesis, and no wallet balance has been created.
- These monetary and consensus parameters are not frozen; do not rely on them until the normative specification and test vectors are reviewed and approved.

## Release stages

### Stage 0 — Prototype integrity (current)
- [x] Cross-version CI passed for the schema-v5 issuance-ledger regression (428 tests each on Python 3.12 and 3.13, run 45825892104). Later independent Base58Check vector changes also passed both Python jobs and Node.js 22 in runs 45826222268 and 45826234922. This does not close protocol, wallet, or audit gates.
- [ ] Establish a clean reproducible test report and release candidate commit.
- [ ] Review SQLite lifecycle, migration, backup, recovery, and data-directory locking.
- [ ] Document known limitations and threat model.

### Stage 1 — Protocol freeze

The detailed open decisions and required evidence are tracked in [Protocol-freeze gap register](protocol-freeze-gap-register.md). All listed protocol decisions remain open until normative rules and independent vectors are approved.
- [ ] Normative specification covering serialization, transaction/script rules, signatures, block validation, retargeting, time rules, fees, upgrades, network magic, address encoding, and limits.
- [x] Owner-approved monetary schedule specified: 20,000,000 BRT founder allocation plus 20,000,000 BRT mining allocation at 10 BRT per block for heights 1–2,000,000.
- [ ] Founder genesis output, spendability, exact serialization, and independent vectors implemented and reviewed. Current genesis remains a zero-value OP_RETURN; no founder coins are issued.
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
