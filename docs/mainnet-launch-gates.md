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


## P2P resource-boundary gate

- [ ] Define and approve hard peer-count, inbound/outbound, node-wide bandwidth/work, handshake, queue, memory, and file-descriptor budgets based on measured deployment envelopes.
- [ ] Add adversarial load, churn, slow-peer, aggregate-rate, resource-exhaustion, and shutdown tests; independently review the final policy.

See [P2P resource-boundary audit](p2p-resource-boundary-audit.md) and [node-wide P2P resource policy design](p2p-node-wide-resource-policy-design.md). The design is proposal-only: it selects no numeric limits, implements no new controls, and does not authorize public binding. The source review confirms that peer count is configurable without a hard ceiling; inbound and outbound peers share one count rather than separately approved quotas; each peer owns independent rate buckets and a receive task; frame-size limits do not cap aggregate resident payloads; and pending writes/handshakes have no node-wide budgets. These are source-level findings, not measured capacity results. The current peer manager's per-peer controls do not establish node-wide DoS resistance or authorize public binding.

## Persistent network identity gate

- [ ] Freeze and independently review a canonical, versioned network-identity specification covering network ID/role, Genesis commitments, all consensus parameters, serialization/script/address identifiers, P2P magic/protocol compatibility, and storage compatibility.
- [ ] Define canonical digest vectors and authenticate the expected identity through an independently governed external pin with freshness, anti-rollback, rotation, revocation, and recovery rules.
- [ ] Resolve the existing identifier-format mismatch: local `TestnetConfig.network_id` is free-form text, while Genesis manifest/trust validators require 32-byte lowercase hex. Freeze one canonical representation and cross-component vectors; do not silently hash or normalize identifiers.
- [ ] Bind the authenticated identity atomically to persistent node state; reject missing or mismatched identity before state mutation or networking; define explicit backup-first migration for legacy databases.
- [ ] Add adversarial tests for same-Genesis/different-network configurations, altered protocol parameters, missing/corrupt identity metadata, rollback pins, interrupted initialization/migration, and no-mutation failure behavior.
- [ ] Complete independent implementation and security review before closing this gate.

See [persistent network identity binding design](persistent-network-identity-binding-design.md) and [persistent network identity source audit](persistent-network-identity-source-audit.md). The source audit confirms that current persistent metadata binds schema version, proof-of-work limit, and Genesis hash only; it does not bind network ID, P2P magic, or protocol version. It is a proposal only; it does not select Mainnet constants or authorize production use.

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

### Header-admission fail-closed regression coverage

Automated regressions now verify that a header with insufficient proof of work
and a header carrying incorrect retarget bits are rejected without changing the
known header DAG, selected tip, or chainwork-bearing node set. These tests cover
state atomicity for these two rejection paths only. They do not replace
independent proof-of-work/compact-target vectors, adversarial retarget boundary
testing, adjusted-clock policy review, or full external header-consensus review.

A further branch-local retarget regression rejects a candidate that borrows
the required difficulty bits calculated for a competing branch. The test checks
that rejection leaves the complete header DAG, selected tip, and cumulative
chainwork unchanged. It remains a local regression, not an independent
cross-client consensus vector.

### Header-batch commit-callback rollback

A regression now forces the optional in-memory header-batch commit callback to
raise after all candidate headers have been admitted. It verifies that the
header DAG, selected tip, cumulative chainwork, and newly inserted nodes all
return to their exact pre-batch state. This verifies in-memory rollback for the
callback failure path only; durable cross-store atomicity remains governed by
the coordinated storage and recovery requirements above.

### Persistent header admission clock-failure regression

A persistent-store regression now forces the configured adjusted-time provider
to fail before a candidate header is admitted. It verifies that the live DAG,
selected tip, cumulative work, and replayed durable header set remain unchanged.
This covers provider failure before persistence begins; clock synchronization,
peer-time sampling quality, and production adjusted-time policy remain unresolved
launch requirements.

### Persistent-header tamper detection

Regression coverage now mutates serialized header fields in SQLite while
retaining the original stored block hash. Startup replay must reject the
corrupted row on recomputed-hash mismatch. A separate reload test verifies
that a failed replay does not replace or mutate the currently published
in-memory header chain. This does not replace filesystem integrity controls,
database backup/restore drills, or independent storage review.


### Persisted UTXO row integrity validation

The explicit UTXO integrity audit now validates each persisted outpoint and
its value, script type, creation height, coinbase flag, and creation MTP rather
than relying only on SQLite schema constraints. A regression deliberately
bypasses SQLite CHECK constraints, corrupts a stored transaction ID, and
requires the integrity audit to fail closed. This is row-shape and metadata
validation only; it does not prove that the complete live UTXO set equals an
independent replay of every active block. Deterministic full UTXO replay and
independent cross-implementation verification remain mandatory launch gates.


A second persisted-UTXO integrity regression bypasses SQLite CHECK constraints
and independently corrupts the stored output value, creation height, coinbase
flag, and creation MTP. Each malformed field must cause the explicit integrity
audit to fail closed. The test restores the row between cases. This checks
persisted metadata shape and bounds; deterministic replay comparison against
the active block history is still required before production use.


The audit now also indexes active-chain transactions and checks every live
UTXO whose transaction ID appears in that history against the original output
value, locking script, output index, creation height, and coinbase position.
Regression coverage mutates each of these fields and requires fail-closed
behavior. Trusted bootstrap outputs are not represented by active block
transactions and are deliberately excluded from this comparison. This is a
source-output consistency check for extant rows, not a complete replay: it
cannot prove that no unspent output is missing, that spent outputs are absent,
or that all provenance and undo records are correct. Full deterministic replay
from an authenticated genesis/bootstrap manifest remains a launch gate.


### Persisted block undo-created integrity

The UTXO integrity audit now derives the expected set of created outpoints
from every transaction in each active block and requires the persisted
`block_undo_created` rows for that height to match exactly. Regression
coverage deletes a required undo row and then injects an extra output index;
both cases must fail closed. This validates the created-output index used by
disconnect/reorganization, but does not yet reconstruct spent-output undo
records or independently replay the complete UTXO state. Full deterministic
replay and spent-undo verification remain mandatory launch gates.


### Persisted block undo-spent integrity

The UTXO integrity audit now checks that undo-spent rows refer to inputs
actually present in the corresponding active block, rejects duplicate or
non-parent references, and compares restored value, locking script, creation
height, and coinbase provenance with the source transaction whenever that
source is part of active block history. It also derives the expected undo
records for spends of known historical transaction outputs and fails closed
when one is missing. Regression coverage removes a required record and alters
its stored value. Bootstrap outputs are not represented by active transaction
history, so their original values and scripts still require an authenticated
bootstrap manifest to validate undo data completely. This remains a partial
integrity audit, not deterministic full UTXO replay.


The active-history spent-input audit also tracks every outpoint spent in prior
blocks, including bootstrap outpoints whose source transaction is not present
in active block history. A repeated spend is rejected even when the source
cannot yet be independently resolved. This detects duplicate bootstrap spends
in the stored history, but does not authenticate the bootstrap output's
original value, script, or provenance; that still depends on the pending
authenticated bootstrap manifest and full replay gate.


### Active block header/body commitment audit

The persisted-chain integrity audit now reconstructs each active block from its
stored 80-byte header and ordered raw transaction records. It checks the
reconstructed header hash and parent link against the block index and verifies
that the ordered transaction IDs reproduce the header's Merkle root. A
regression test mutates the stored Merkle commitment and updates the indexed
block hash to match the altered header; the audit must still reject the record
because the transaction body no longer commits to that root. This validates
internal persistence consistency only: it does not replace independent header
consensus validation, full UTXO replay, or external implementation review.


The active-chain integrity audit also checks transaction dependency order:
an input referencing a transaction recorded in the same block must reference
an earlier transaction position, and the referenced output index must exist.
Inputs may not resolve to a transaction later in the active chain. This is a
persistence-consistency check, not a substitute for full script, maturity,
sequence-lock, or consensus validation during block connection.


The active-block persistence audit additionally enforces the structural
coinbase rule: the first transaction must be the sole coinbase transaction,
and no later transaction may have the null-prevout coinbase form. This check
protects the stored transaction ordering audit; it does not independently
revalidate subsidy limits, coinbase maturity, or the complete block consensus
rules.


### Reorganization atomicity regression

A regression test now creates an active two-block chain, disconnects its tip,
connects one replacement block, and then deliberately fails validation while
connecting the next replacement block (missing input). The expected behavior
is full transaction rollback: the original tip and its UTXO must remain, the
partially connected replacement output must not remain, and the integrity
audit must still pass. This test is added but must pass in CI before its result
can be treated as verified; it does not replace crash/fault injection against
process termination or storage-device failures.

### Reorganization created-output undo preflight

Before disconnecting an active block, the reorganization path now reconstructs
the expected created-outpoint set from the ordered persisted transaction bodies
and compares it with that block's block_undo_created records. A mismatch
aborts the reorganization inside the same database write transaction. A
regression removes one required undo-created row and verifies that the active
tip and UTXO set remain unchanged. This guards one class of persisted undo
corruption; it is not a substitute for deterministic full UTXO replay or
fault-injection at every database write boundary.

### Reorganization spent-output undo history preflight

Before disconnecting an active block, reorganization now cross-checks spent
undo rows against the block's non-coinbase inputs, rejects duplicate inputs and
inputs already spent in earlier active blocks, and checks known historical
output value, script, creation height, and coinbase provenance. It derives the
required undo set only from historical outputs not already spent in the prior
active prefix. Bootstrap-origin outputs remain unauthenticated without a
separate authenticated bootstrap manifest, and this check is not full UTXO
replay or a substitute for consensus validation.

### Tip-disconnect transaction dependency preflight

The tip-disconnect storage primitive now reconstructs the active transaction index
from persisted transaction bodies and checks dependency order across the complete
active prefix plus the candidate tip before applying any UTXO undo mutation. It
rejects an earlier active transaction that references an output from the same
or a later block, or an output index that does not exist in an earlier source
transaction. A regression verifies that a dependency-order rejection leaves
the active tip and UTXO state unchanged. This is a storage-integrity safeguard;
it does not validate block headers, proof of work, scripts, or the full
consensus state, and it does not replace deterministic full UTXO replay.

### Tip-disconnect persisted transaction-count guard

The tip-disconnect preflight now compares the number of persisted ordered
transaction bodies with the active block's recorded transaction count before
examining undo records or mutating UTXOs. A regression removes a non-coinbase
transaction row together with its matching created/spent undo entries while
leaving the block metadata unchanged; disconnect must reject the incomplete
body and preserve the tip and UTXO set. This detects one coordinated storage
corruption case, but does not replace header/Merkle verification or deterministic
full UTXO replay.

### External trust-policy pin distribution

The requirements proposal in `docs/external-release-policy-pin-distribution-proposal.md` is not an implementation or approval. Before production trust activation, the project must select and independently review an external pin distribution and freshness mechanism, signer identity and quorum, separation of duties, rollback detection, key rotation/revocation, and recovery procedures. A local database or restored backup is not an authoritative external pin. This gate remains OPEN; no owner key, policy authority, or trust activation is approved.

### Trust-state lifecycle integration review

`docs/trust-state-implementation-readiness-review.md` records a bounded source review. The existing POSIX data-directory lock is not mandatory in `PersistentNodeState`, and the SQLite transaction coordinator does not acquire it. Neither component supplies external pin authentication or snapshot rollback resistance. Mandatory lock ownership, external policy authentication/freshness, transactional acceptance, restore-old-backup rejection, and crash/fault tests remain OPEN. Do not treat the existing primitives as a completed trust-state implementation.

### Mandatory node data-directory lock adoption

An opt-in `PersistentNodeState.open_locked(...)` lifecycle entry point has been added to hold `DataDirectoryLock` for the coordinated node-state lifetime, with focused tests for exclusivity and release. This does not yet close the gate: legacy constructors and `open_coordinated()` remain callable without the lock. Audit and migrate every production CLI/service/startup path to the locked entry point, reject bypasses in production mode, and pass CI plus process-level fault tests before treating single-process data-directory ownership as enforced. POSIX advisory locking does not prevent privileged local modification or backup rollback.

The loopback-only local testnet CLI now uses `PersistentNodeState.open_locked(...)`, making the node-state object own its data-directory lock. Its subprocess test checks that a competing CLI process using the same directory is rejected. This does not establish a Mainnet startup path: legacy unlocked constructors remain available, and all production entry points must be audited and constrained before the mandatory-lock gate can close. CI verification is pending.

### Node entry-point lock audit — gate remains open

A bounded audit is recorded in `docs/node-entrypoint-lock-audit.md`. The local CLI is migrated to `PersistentNodeState.open_locked()`, and the package declares no console-script entry point. However, `PersistentNodeState.__init__()` and `open_coordinated()` remain unlocked compatibility APIs, while `BlackrootNodeRuntime` accepts caller-provided state without requiring lock ownership. Therefore the mandatory process-ownership gate is still OPEN until a supported production composition root rejects unlocked state and is covered by integration tests. This audit does not establish Mainnet readiness.

### Runtime lock enforcement follow-up

`PersistentNodeState.data_directory_locked` exposes current lock ownership. The local CLI opts into `BlackrootNodeRuntime(require_locked_state=True)`; tests cover rejection of unlocked state and acceptance/release of locked state. This narrows accidental bypass at the CLI/runtime boundary, but the enforcement flag remains opt-in for compatibility callers and legacy constructors remain unlocked. The global mandatory process-ownership gate remains OPEN. CI verification is pending.

Lock-file hardening follow-up: `DataDirectoryLock` now uses `O_NOFOLLOW` where available, rejects symlinked lock paths and directories, and verifies the opened descriptor is a regular file. Tests cover symlink redirection and invalid directory paths. This is defense in depth, not a substitute for restrictive directory permissions, privileged-tampering defenses, or filesystem review. CI verification remains pending.


### Private node data-directory permissions

`DataDirectoryLock` now requires the opened data directory to be owned by the current user and to exclude group/other permissions (0700 or stricter), and opens the lock file relative to a pinned directory descriptor. A regression covers rejection of a permissive 0755 directory before lock-file creation. This does not defend against the owning user or privileged local tampering, parent-path replacement before descriptor acquisition, hostile filesystems, or restored-backup rollback. Independent filesystem, ownership, backup/restore, and crash-recovery review remains OPEN; CI must pass on the exact commit.


### SQLite online backup and restore gate — OPEN

`tests/test_sqlite_online_backup.py` exercises SQLite's online backup API for
an active WAL-mode source while its connection remains open, then checks the
backup with `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Existing
coverage also checks domain-level UTXO/archive validation and that validating a
damaged backup does not mutate the source database.

This is primitive-level test coverage, not a production backup/restore
facility. There is no approved node-level backup command, authenticated
backup manifest, atomic restore workflow, anti-rollback anchor, retention or
off-host policy, encryption/key-management policy, or tested disaster-recovery
runbook. A valid old backup can still be stale; database integrity alone does
not prove that its chain tip is current or authorized. Production readiness
requires coordinated backup of every required node artifact, manifest-bound
checksums and schema/network/genesis identity, offline verification, restore
into a fresh isolated directory, full chain/UTXO/trust-state validation,
external anti-rollback freshness checks, atomic activation, and fault tests
covering interruption at each step. Do not overwrite the live data directory
during restore. CI must pass on the exact test commit; this gate remains OPEN.

The proposed end-to-end workflow is specified in `docs/production-backup-restore-design.md`. It remains a design proposal only: no production backup command, authenticated manifest, anti-rollback authority, or restore activation mechanism has been implemented or approved.



### P2P admission-race and slow-handshake regression coverage

Focused local asyncio regressions now exercise concurrent outbound dials,
inbound accept bursts, and a mixed inbound/outbound race against the configured
peer-count cap. Additional tests exercise handshake timeout cleanup when a
remote peer stops partway through a frame header or version payload, and verify
that a timed-out inbound session releases its manager peer slot. These tests
improve coverage of ordinary event-loop admission and timeout cleanup; they do
not establish a hard implementation ceiling, a bounded kernel accept queue,
or protection against connection churn.

Node-wide byte/message/work budgets, receive-memory reservations, bounded
pending writes and waiters, listener backlog and OS descriptor policy,
instrumented adversarial load tests, supported-hardware measurements, and
independent security review remain OPEN. Per-peer token buckets still allow
aggregate resource consumption to scale with peer count. No public listener
or production P2P resource profile is authorized. CI must pass on the exact
candidate commit before these focused tests are treated as verified.

### Persistent network-identity binding — OPEN

Bounded source audits are recorded in
`docs/persistent-network-identity-audit.md` and
`docs/persistent-network-identity-source-audit.md`. The latter also traces
CLI startup and runtime wiring: the local peer manager uses configured P2P
magic/version, but persistent state receives only the proof-of-work limit and
Genesis header, while the runtime receives manager and protocol version as
separate arguments. The startup `network_id` log is not a persisted identity
binding. The persistent header store
currently binds its metadata to schema version, proof-of-work limit, and the
configured genesis hash, and active UTXO records are cross-checked against the
replayed header DAG. However, the persisted identity does not include the
configured network ID, P2P message magic, or protocol version; the UTXO
metadata table does not independently pin network identity or genesis; and no
authenticated externally pinned network-identity manifest is loaded at
startup. A genesis hash is not a complete identity for all protocol settings.

Before this gate can close, freeze and independently review a canonical,
versioned identity specification covering the complete consensus and P2P
parameter set, define trust-anchor/pin distribution and anti-rollback, persist
the accepted binding without silently rewriting existing databases, and add
mismatch, downgrade, corruption, and interrupted-migration tests. This is a
source audit and design requirement, not an implementation or launch approval.

### P2P outbound queue and aggregate payload accounting update

The source audit now records a concrete outbound resource boundary: peer
frames are encoded before acquiring the per-peer send lock, and the lock does
not cap concurrent waiting send tasks or retained frame bytes. The receive
path likewise has per-peer frame/rate limits but no shared node-wide payload
reservation across peers and callbacks. See
`docs/p2p-resource-boundary-audit.md`, “Outbound send-queue and pre-lock
allocation finding”.

This is an audit finding only. No numeric queue, waiter, memory, or drain-time
limits have been approved; no bounded queue or node-wide reservation has been
implemented; and no public listener is authorized. Keep the P2P resource gate
open pending an approved measured profile, implementation, cancellation and
shutdown accounting tests, adversarial aggregate-load tests, and independent
security review.

The node-wide P2P resource design now specifies the required send/receive reservation ownership contract, including reservation-before-frame-allocation, bounded single-writer queues, byte as well as waiter quotas, receive ownership transfer to asynchronous handlers, exact-once cancellation/shutdown release, and observable invariants. This remains a design proposal only; it is not implemented or approved, and no production numeric limits have been selected. See `docs/p2p-node-wide-resource-policy-design.md`, section 11.

A synchronous count-and-byte reservation primitive has been added in
`src/blackroot_p2p_resources.py` with focused unit tests. It is not yet
integrated into P2P transport/manager reads, writes, callbacks, or shutdown;
it is not a production policy and does not close the aggregate-resource gate.
See section 12 of `docs/p2p-node-wide-resource-policy-design.md`.

Outbound send accounting is now available as an opt-in PeerConnection capability using explicit peer and shared node budgets. It is not wired through PeerManager, is not mandatory, and does not account inbound payloads or application handlers. The P2P node-wide resource gate remains OPEN.

P2P receive-side resource reservations have been added as an opt-in feature: fixed-header validation is followed by peer and shared-node reservation before payload-body reads, with reservation retained through awaited message handling. PeerManager can inject caller-supplied shared node budgets and fresh per-peer budget factories. This is not mandatory and does not close the node-wide resource gate; unbudgeted paths remain possible, application-retained copies/tasks are not bounded, and no production resource profile has been approved.

Receive reservation lifecycle now releases decoded messages that are closed before handler dispatch, while preserving reservations owned by an active asynchronous handler. This is covered by focused tests but does not bound application-retained copies or callback-created tasks; the P2P node-wide resource gate remains OPEN.

The P2P transport now exposes `take_receive_reservation()` during active handler dispatch so an application can transfer accounting ownership with payload data to a bounded downstream consumer. The consumer must release the transferred reservation exactly once after its final use. This API is opt-in and does not itself enforce bounded application queues or callback-created task counts; the P2P resource-policy gate remains OPEN.

A bounded single-consumer application queue prototype now exists at `src/blackroot_p2p_queue.py`. It accepts a payload only with a live transferred reservation, bounds item count, releases queued reservations on close, and releases in-flight ownership on acknowledgement. Focused tests were added. This does not yet provide a supervised production worker lifecycle, measured memory ceilings, retry semantics, multi-consumer scheduling, or a mandatory policy; the P2P resource gate remains OPEN and public networking is not authorized.

The queue prototype now includes a cancellation-safe `consume()` context manager that acknowledges and releases an in-flight reservation in `finally`, plus recovery of the consumer slot when cancellation occurs while waiting. Tests cover both cancellation paths. Worker supervision and replacement limits remain responsibilities of the runtime; this remains an opt-in prototype, not a production resource policy.

`PeerManager` can now opt into one bounded `ReservedMessageQueue` per peer through `application_queue_factory`, provided explicit receive peer/node budgets are configured. It transfers receive reservations to the queue, fails closed and releases the rejected reservation on queue overflow, and closes queued messages on peer teardown. The runtime still must supervise consumer workers; no worker pool, measured production cap, or mandatory integration is established. This is not authorization for public P2P binding.

`PeerManager.start_application_worker(peer, handler)` now retains one sequential application consumer task per configured peer queue. Handler exceptions are recorded and close both queue and peer; manager shutdown cancels and awaits remaining worker tasks so in-flight reservations are released through the queue context manager. Worker restarts are not automatic, and handler side effects may not be rollback-safe under cancellation. This still lacks a measured production concurrency/memory profile and independent review; the P2P gate remains OPEN.

Manager shutdown now closes all per-peer application queues before closing streams, then waits for peer tasks and cancels/awaits any remaining application workers. A test covers cancellation during a blocked handler and verifies in-flight receive reservations are released. External handler side effects remain outside rollback guarantees; worker lifecycle and P2P resource policy still require adversarial testing and independent review.

Peer teardown now closes the per-peer queue, cancels and awaits its retained worker, then completes stream cleanup. This prevents a disconnected peer from leaving a blocked application handler holding an in-flight receive reservation indefinitely. Per-peer worker-start bookkeeping is also cleared on disconnect. Tests cover disconnect during blocked handler execution and verify reservation counters return to zero. External handler side effects remain non-transactional; global worker scheduling, measured limits, and independent review remain open gates.

Concurrent `PeerManager.close()` calls now wait for the same shutdown completion instead of later callers returning while the first teardown is still running. A blocking-peer test verifies this ordering. This is event-loop-local lifecycle synchronization and does not change the open production P2P resource gate.

The per-peer queue factory now rejects shared, previously used, or closed queue instances; each peer must receive a fresh pristine queue. A test covers accidental queue reuse across two peers. This prevents cross-peer consumer ownership ambiguity but does not close the node-wide resource-policy gate.


A cancellation-safety review found that a caller cancelling its own `PeerManager.close()` await could interrupt teardown while the manager's completion event was still signalled in `finally`. Shutdown now runs in one retained task awaited through `asyncio.shield()`; cancellation of an individual caller cannot cancel the shared teardown, and later callers await that same task. Tests cover cancellation of the first caller while a peer close is blocked. This improves lifecycle correctness but is not evidence of a production resource ceiling; the P2P gate remains OPEN.


Peer setup now closes a newly accepted socket and removes/closes any partially
registered application queue when per-peer callback or queue construction
fails. Tests cover invalid handler-factory and queue-factory results. This
reduces resource leakage on local setup errors but does not close the P2P
admission/resource-policy gate or authorize public listener exposure.


### P2P setup ownership failure containment — OPEN

Per-peer send/receive budget factories and PeerConnection construction are now inside the same socket-ownership cleanup boundary as callback and queue setup. Any setup exception closes the accepted socket and removes/closes a partially registered application queue. The synchronous inbound accept callback records ordinary setup/registration exceptions in bounded manager error history and closes the socket rather than leaking an unhandled callback exception. Focused regressions cover raising/invalid budget factories and inbound setup failure.

This is not a production P2P admission or resource ceiling. It does not bound kernel backlog, connection rate, aggregate descriptors, memory, tasks, or CPU, and does not authorize public listener exposure. CI must pass on the exact candidate commit; stress testing and independent review remain required.


Peer tracking now rolls back the managed-peer entry and closes the socket if asyncio task creation fails after peer construction; the unsubmitted coroutine is explicitly closed. A focused regression verifies socket closure and empty peer/task registries. This is a local failure-containment safeguard only; node-wide task ceilings and P2P stress/security gates remain OPEN.


### Listener startup/shutdown race — OPEN

Listener startup is single-flight, and a listener returned after shutdown has begun is immediately closed and awaited instead of being installed on an already-closed manager. Tests cover close-during-startup and concurrent startup attempts. This is lifecycle hardening only: backlog sizing, connection-rate limits, deployment bind policy, aggregate resource caps, stress tests, and independent review remain required. No public listener is authorized.


Shutdown now waits for any listener bind already in progress to finish its cleanup path before marking manager shutdown complete. The race regression asserts close remains pending until a delayed bind returns and the late listener has been closed. This lifecycle gate remains separate from production bind/backlog policy, stress evidence, and independent security review.


### Application worker task-creation failure — OPEN

Worker admission now rolls back if task creation fails: the coroutine is closed and the peer's worker-start marker is removed, with a focused regression verifying no task/marker remains. This is local failure containment only. Global task limits, measured resource profiles, adversarial stress testing, and independent review remain open.


### In-flight outbound dial shutdown — OPEN

The manager now retains, cancels, and joins outbound dial tasks during shutdown, then waits for connect reservations to drain. A regression verifies cancellation of a deliberately blocked outbound dial and release of its admission reservation. This does not establish production outbound rate limits, global descriptor/task ceilings, stress evidence, or independent review.


### Outbound dial task-creation rollback — OPEN

A failure-injection regression now covers failure to create the retained dial task. The unsubmitted coroutine is closed, the outbound reservation is released, and the shutdown-drain event returns to the set state. This is a local bookkeeping invariant only; global task/descriptor ceilings, measured load testing, production outbound policies, and independent review remain open.


Outbound dial lifecycle coverage was extended with a caller-cancellation regression: cancelling a task awaiting `connect()` cancels its retained socket dial and releases the outbound reservation. Together with shutdown cancellation and task-creation failure tests, these are focused lifecycle checks only. OS-level socket exhaustion, connection churn, global task/descriptor ceilings, measured hardware profiles, and independent review remain OPEN.


### Peer tracking rollback and application-queue ownership — OPEN

A failure-injection regression now covers failure to create the retained peer
session task after peer construction. The rollback removes the peer from the
manager, closes its socket, closes and unregisters its per-peer application
queue, and clears any worker-admission bookkeeping. This prevents an orphaned
queue from retaining queued receive reservations after task creation fails.
It is a local lifecycle invariant only; it does not establish a node-wide task
ceiling, a production resource profile, adversarial stress evidence, or
independent security review. The P2P resource gate remains OPEN.


### Shared peer transport teardown — OPEN

PeerConnection.close() now creates one retained teardown task shared by concurrent callers and awaited through asyncio.shield(). The writer close and wait_closed() path therefore has one owner; cancellation of one caller does not cancel transport teardown. Focused regressions cover concurrent callers and cancellation followed by a later waiter. Task-creation failure closes the unsubmitted coroutine and performs synchronous writer/reservation cleanup. This is lifecycle hardening only. It does not close the P2P resource-policy gate, provide a measured production profile, or replace independent review.

### Transport teardown task-creation failure retry guard — OPEN

A failure-injection regression now checks that failure to create the retained teardown task does not cause a later close caller to invoke writer.close() again. The first caller records the startup failure, closes the unsubmitted coroutine, attempts synchronous socket closure once, and releases any receive reservation still owned locally. Later callers fail explicitly. This remains narrow lifecycle hardening; P2P resource limits, adversarial stress testing, production deployment policy, and independent review remain OPEN.


### Header batch commit callback mutation guard — OPEN

`HeaderChain.add_batch()` now prevents its `on_commit` callback from invoking public single-header or nested-batch mutation APIs while the callback is running. This prevents the callback from silently extending the in-memory DAG beyond the validated batch and its returned accepted-header list. Focused regressions cover both mutation paths. This remains an in-memory header prototype: callback side effects outside the DAG cannot be rolled back, and persistent branch state, block-body validation, UTXO replay, and independent consensus review remain launch gates.

### Persisted active block body preflight during reorganization — OPEN

Before trusting active-chain undo records, reorganization now checks that the
persisted transaction rows have the expected count and contiguous positions,
reconstructs the block from its stored 80-byte header and raw transaction
records, and verifies the block hash, parent commitment, Merkle root, and each
transaction ID against the positional index. Regression tests corrupt the
stored transaction count, a transaction position, a stored transaction-ID
index, a persisted header byte, an unreferenced undo-spent record, and a
known historical input's undo value, and assert that reorganization fails
without changing the active tip, headers, or UTXO set.
These are targeted database-integrity checks, not deterministic full UTXO
replay or complete consensus validation. Bootstrap provenance, undo metadata
provenance, crash recovery, adversarial testing, and independent review remain
open.
