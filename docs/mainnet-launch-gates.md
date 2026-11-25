# BLACKROOT Mainnet launch gates

**Status: NOT READY FOR MAINNET. No launch date is authorized by this repository.**

Passing unit tests demonstrates only that tested prototype paths behave as
expected. It is not evidence of consensus compatibility, cryptographic safety,
network security, economic viability, legal authorization, or readiness to hold
customer funds.

## Blocking engineering requirements

- [ ] Freeze a normative protocol specification: serialization, network magic,
  address encoding, script language, transaction versioning, locktime, sequence,
  coinbase maturity, block limits, fee policy, and upgrade/version signaling.
- [ ] Complete and independently review script execution and signature
  verification using established cryptographic libraries and published vectors.
- [ ] Finalize full header consensus: canonical compact targets, exact retarget
  boundary rules, median-time-past, future-time policy, genesis parameters, and
  network-specific difficulty behavior.
- [x] Implement an opt-in coordinated SQLite node-state lifecycle with a shared
  transaction boundary for header, block-body, UTXO, and recovery-journal writes;
  selected commit/rollback and process-termination cases have automated tests.
- [ ] Make coordinated storage the supported production lifecycle only after
  backup-first migration, restore drills, multi-process stress, operational
  shutdown/recovery behavior, and independent review are complete.
- [ ] Validate every block header and body before it can affect active state.
- [ ] Complete side-branch storage, per-block UTXO undo, chainwork selection,
  deterministic reorganization, and adversarial crash/recovery testing.
- [ ] Add peer-to-peer protocol framing, peer limits, DoS controls, peer
  discovery, synchronization, and adversarial network tests.
- [ ] Build wallet key management, secure randomness, backup/restore, address
  handling, transaction signing, and independent wallet test vectors.
- [ ] Build mining software and independently reproduce the genesis block from
  frozen parameters. Never silently change genesis or consensus constants.
- [ ] Add independent implementations or cross-client consensus test vectors.
- [ ] Complete external security review, fuzzing, property tests, fault
  injection, and a public testnet period with documented incident handling.
- [ ] Establish reproducible builds, signed releases, dependency pinning,
  vulnerability response, monitoring, backups, and operational runbooks.

## Blocking launch and governance requirements

- [ ] Obtain written advice from qualified Iraqi counsel on the proposed
  activity, issuance, exchange, custody, mining, marketing, and fundraising.
- [ ] Confirm applicable Central Bank of Iraq requirements and any other
  licensing, AML/CFT, consumer-protection, tax, sanctions, and data obligations.
- [ ] Publish transparent governance, supply, mining, treasury (if any), upgrade,
  disclosure, and incident-response policies.
- [ ] Do not sell coins, accept deposits, promise returns, or represent BROOT as
  approved, regulated, or listed before relevant legal and technical gates pass.

## Current verified scope

The repository contains experimental Python components for SHA-256d and
subsidy helpers, header validation/fork-choice, a replay-verified SQLite header
store, legacy transaction serialization, limited P2PKH script validation,
block-body checks, coinbase maturity, and a SQLite UTXO persistence/reorg
prototype. An opt-in coordinated persistent node-state lifecycle now places the
header store, UTXO store, block-body archive, and recovery journal on one
node-owned SQLite connection. Selected transaction rollback, process-exit, competing-branch reorganization,
restart persistence, and independent-process writer-serialization cases pass
automated tests. This is
still a partial prototype, not a complete production node lifecycle.

The legacy compatibility mode still uses separate header, UTXO, and recovery
journal files. The coordinated mode is opt-in. The repository now includes
read-only preflight, WAL-consistent snapshot creation, cross-store consistency
checks, a schema merge planner, and a staging importer with a coordinated-node
reopen validator. These tools do not perform production cutover; backup
restoration drills, large-dataset testing, migration fault injection, and
independent review remain required. Header replay verification does not by
itself validate historical external adjusted-time inputs or establish peer
agreement. The pure-Python signature code is not suitable for production key
handling.

**Decision rule:** keep all development isolated from real funds until every
blocking item is implemented, independently tested, reviewed, and approved.
A testnet is not a mainnet launch and has no promised monetary value.
