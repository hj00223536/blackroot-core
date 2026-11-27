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
- [ ] Finalize full header consensus: exact retarget
  boundary rules, median-time-past, future-time policy, genesis parameters, and
  network-specific difficulty behavior.
- [x] Implement an opt-in coordinated SQLite node-state lifecycle with a shared
  transaction boundary for header, block-body, UTXO, and recovery-journal writes;
  selected commit/rollback and process-termination cases have automated tests.
- [ ] Make coordinated storage the supported production lifecycle only after
  backup-first migration, restore drills, multi-process stress, operational
  shutdown/recovery behavior, and independent review are complete.
- [ ] Validate every block header and body before it can affect active state.
- [ ] Implement deterministic active-chain replay verification from the frozen genesis and compare the reconstructed UTXO set, provenance, issuance, active tip, and undo metadata with persisted state; fail closed on any mismatch.
- [ ] Complete side-branch storage, per-block UTXO undo, chainwork selection,
  deterministic reorganization, and adversarial crash/recovery testing.
- [ ] Add peer-to-peer protocol framing, peer limits, DoS controls, peer
  discovery, synchronization, and adversarial network tests.
- [ ] Build wallet key management, secure randomness, backup/restore, address
  handling, transaction signing, and independent wallet test vectors.
- [ ] Build mining software and independently reproduce the genesis block from
  frozen parameters. Never silently change genesis or consensus constants.
- [ ] Add independent implementations or cross-client consensus test vectors.
- [ ] Freeze transaction and block serialization limits as normative protocol
  rules, then verify CompactSize canonical boundaries, transaction byte layout,
  txid byte order, Merkle odd-leaf handling, and parser rejection behavior
  against independently sourced, versioned vectors. Include maximum-size and
  over-limit cases, truncated fields, trailing bytes, duplicate inputs, and
  integer boundary cases. The current 4,000,000-byte transaction parser limit
  and 10,000-byte script-vector limit are implementation bounds, not approved
  Mainnet protocol parameters; do not treat them as frozen consensus rules.
- [x] Add a regression for the Merkle mutation ambiguity where an odd
  transaction list and a list with its final transaction explicitly repeated
  produce the same Merkle root. The block validator rejects the repeated txid
  before transaction execution and leaves the caller's parent UTXO map unchanged.
  This is an implementation regression, not an independently sourced protocol
  vector; external reference vectors and independent-client reproduction remain
  required before Mainnet.
- [ ] Complete external security review, fuzzing, property tests, fault
  injection, and a public testnet period with documented incident handling.
- [ ] Establish reproducible builds, signed releases, and a reviewed dependency lock that pins every direct and transitive package to exact versions with verified hashes; the broad development constraint in `pyproject.toml` is not a release lock.
  vulnerability response, monitoring, backups, and operational runbooks.

## Genesis issuance authorization gate

Use the [genesis activation package checklist](genesis-activation-package-checklist.md), [trust-anchor governance proposal](genesis-trust-anchor-governance-proposal.md), and [Genesis package semantic verification plan](genesis-package-semantic-verification-plan.md) as review aids. They are proposals/plans only and do not satisfy any approval, trust-anchor, semantic-verification, or issuance gate.


- [ ] Review and freeze the public manifest format in [genesis-manifest-spec.md](genesis-manifest-spec.md), including canonicalization and digest test vectors.
- [ ] Record explicit owner approval for the exact manifest digest and founder locking script; keep all private key material outside source control.
- [ ] Implement a one-time initializer that verifies the frozen genesis transaction and atomically commits the genesis identity, exact founder output, initialization marker, and auditable issuance record.
- [ ] Prove exact reopen is idempotent and every altered manifest, duplicate issuance, partial database, or post-activation attempt fails without mutation.
- [ ] Independently reproduce final genesis and issuance vectors in a separately maintained client before any launch.

The current genesis candidate has no founder output. The manifest document is a proposal only and does not create a balance or authorize issuance.

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
agreement. The P2PKH prototype now delegates secp256k1 ECDSA verification to the
`cryptography` library/OpenSSL backend and has local strict-DER regression
coverage. This is not a complete Script engine, does not provide production
wallet key management, and has not yet passed independent cross-client vectors
or external cryptographic review.

### Legacy SIGHASH_ALL independent-vector gate

The current legacy SIGHASH_ALL implementation has local regression coverage for
valid signatures and modified-transaction rejection, but those tests are
generated by this repository and do not independently establish compatibility.
Before this gate can be closed, freeze the exact transaction and sighash
serialization rules, then compare byte-for-byte preimage and digest results
against independently sourced, versioned reference vectors (including
multi-input/multi-output transactions, non-default sequences, locktime, and
input-index boundaries). Record the source, version or commit, vector
provenance, expected preimage, expected digest, and observed result. Add
negative vectors for unsupported sighash flags and malformed encodings.
A second implementation or independently maintained vector harness must
reproduce the same results. Do not mark this gate complete based only on
self-generated signatures or tests that call the production sighash function
to construct their own expected values.

**Decision rule:** keep all development isolated from real funds until every
blocking item is implemented, independently tested, reviewed, and approved.
A testnet is not a mainnet launch and has no promised monetary value.


### Block UTXO validation regression coverage

Block transaction validation is tested to reject two separately valid transactions that attempt to spend the same parent outpoint. A later invalid transaction must also leave the caller's parent UTXO snapshot unchanged, because validation operates on a private working copy. These checks cover in-memory block validation only; they do not establish complete consensus compatibility or production readiness.


### Transaction output-collision protection

The in-memory transaction application path now has a regression test proving that a transaction whose derived output outpoint already exists is rejected before any input is removed or output is written. The test snapshots the full UTXO map and asserts it is unchanged after rejection. This is a local state-integrity check, not a substitute for full consensus, script, or persistence testing.


### Canonical compact-target encoding

Header admission now requires compact `nBits` to round-trip through the
canonical encoder. A regression test constructs two distinct compact encodings
that decode to the same target and verifies that the non-canonical alias is
rejected at genesis admission. This removes one source of header-hash and
consensus interpretation ambiguity in the prototype; full header consensus
still requires an independently frozen specification and cross-client tests.


### Concurrent UTXO spend and duplicate block protection

A two-process regression test starts both spenders from the same persisted UTXO
snapshot and releases them together. The expected result is exactly one
successful spend and one rejected spend, with one resulting output and no
remaining funding output. A duplicate active-block test confirms that
reconnecting the same height/block is rejected without changing the active tip,
UTXO count, or active header records. These tests exercise SQLite writer
serialization and duplicate-connect rejection; they do not constitute a
high-load or crash/power-loss certification.

### Serialized block-body archive writer serialization

Block-body archival now uses the immediate-write transaction scope for its
read/check/insert sequence. This serializes standalone writers and prevents
concurrent processes from both observing an absent row before either inserts.
A regression test verifies repeated archival of the same block is idempotent
and round-trips exactly. Dedicated multi-process archive stress remains
required.

### Reorganization round-trip UTXO coverage

An integration regression now switches from the original active branch to a
longer side branch and then back to a still-longer extension of the original
branch. It checks that disconnected coinbase outputs disappear, replacement
outputs appear, and outputs from the reselected branch are recreated, followed
by the store integrity check. This exercises created-output undo and branch
reconnection across two successful switches. It does not yet cover spending
and restoring an ordinary pre-existing output or process interruption at every
individual reorganization write boundary.

### Ordinary-output restoration during reorganization

An integration test now seeds an authenticated ordinary P2PKH output, spends it
in the active branch, then switches to a longer competing branch. It verifies
that the spent funding output is restored from undo data and the disconnected
transaction's recipient output is removed. The test validates the ordinary
signature path and checks the resulting UTXO database integrity. Crash
interruption at each write boundary remains a separate launch gate.

### Chained in-block spends across reorganization

The ordinary-output reorganization integration case now includes two
transactions in the same block where the second spends the first transaction's
newly-created P2PKH output. After switching to a competing branch, it verifies
that the original funding output is restored and both disconnected transaction
outputs are absent. This exercises ordered in-block UTXO updates and undo
handling for a dependent transaction chain; broader adversarial package and
mempool policy tests remain outstanding.

### UTXO creation-height invariant

Authenticated UTXO provenance is now checked against the spending block height for every output type: no output may be spent at a height earlier than the height at which it was created. Coinbase outputs additionally require the configured maturity interval. Regression tests cover both coinbase and ordinary outputs with future creation heights. This closes a temporal-state validation gap in the maturity helper; it does not establish complete consensus readiness.


### Coordinated reorganization crash-recovery checkpoints

Process-exit regression tests now cover a coordinated reorganization interrupted
immediately after the recovery intent is written, after reorganization writes
have been applied but before the shared transaction commits, and immediately
after a successful commit. Reopen checks distinguish the expected old-state
rollback from the fully committed new state, verify that no recovery intent is
left pending, and run the UTXO integrity check. A separate two-process scenario
holds a writer inside the reorganization transaction, starts a competing
process, terminates the writer, and verifies that the contender can reopen and
complete the switch.

These are deterministic process-termination tests against SQLite transaction
boundaries. They do not simulate sudden power loss, torn writes, filesystem or
device failure, corruption, long-running contention, or every individual SQL
write boundary. Those remain explicit launch gates and require independent
fault-injection and restore testing.
