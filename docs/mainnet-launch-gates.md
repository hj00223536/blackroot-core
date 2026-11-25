# BLACKROOT Mainnet launch gates

**Status: NOT READY FOR MAINNET. No launch date is authorized by this repository.**

Passing unit tests demonstrates only that the tested prototype paths behave as
expected. It is not evidence of consensus compatibility, cryptographic safety,
network security, economic viability, legal authorization, or readiness to hold
customer funds.

## Blocking engineering requirements

- [ ] Freeze a normative protocol specification: serialization, network magic,
  address encoding, script language, transaction versioning, locktime, sequence,
  coinbase maturity, block limits, fee policy, and upgrade/version signaling.
- [ ] Implement a complete script interpreter and signature verification using
  established, reviewed cryptographic libraries and published test vectors.
- [ ] Implement full header consensus: canonical compact targets, exact retarget
  boundary rules, median-time-past, future-time limit, genesis parameters, and
  network-specific difficulty behavior.
- [ ] Validate every block's header and transactions before persistence.
- [ ] Implement side-branch storage, per-block UTXO undo data, cumulative-work
  selection, deterministic reorganization, and crash-recovery tests.
- [ ] Add peer-to-peer protocol with message framing, peer limits, DoS controls,
  peer discovery, synchronization, and adversarial network tests.
- [ ] Build wallet key management, secure random generation, backup/restore,
  address handling, transaction signing, and independent wallet test vectors.
- [ ] Build mining software and independently reproduce the genesis block from
  frozen parameters. Never silently change genesis or consensus constants.
- [ ] Add independent implementations or cross-client consensus test vectors.
- [ ] Complete external security review, fuzzing, property tests, fault
  injection, and a public testnet period with documented incident handling.
- [ ] Establish reproducible builds, signed releases, dependency pinning,
  vulnerability response, monitoring, backups, and operational runbooks.

## Blocking launch and governance requirements

- [ ] Obtain written advice from qualified Iraqi counsel on the proposed
  activity, issuance, exchange, custody, mining, marketing, and any fundraising.
- [ ] Confirm applicable Central Bank of Iraq requirements and any other
  licensing, AML/CFT, consumer-protection, tax, sanctions, and data obligations.
- [ ] Publish transparent governance, supply, mining, treasury (if any), upgrade,
  disclosure, and incident-response policies.
- [ ] Do not sell coins, accept deposits, promise returns, or represent BROOT as
  approved or listed before the relevant legal and technical gates are met.

## Current verified scope

The repository contains Python reference prototypes for SHA-256d header helpers,
subsidy arithmetic, transaction serialization and basic UTXO value accounting,
block transaction accounting, and a SQLite persistence prototype. The tests
cover those limited code paths only.

Known critical omissions include script/signature verification, complete header
consensus validation, coinbase maturity, persistent side branches, undo/reorg
support, P2P, wallet, mining, reproducible genesis, independent audits, and
jurisdiction-specific legal clearance.

**Decision rule:** keep development on isolated local test data until every
blocking item is implemented, independently tested, reviewed, and approved.
A testnet is not a mainnet launch and has no promised monetary value.
