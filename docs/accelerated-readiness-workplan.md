# BLACKROOT accelerated readiness work plan

**Status: planning aid only. It is not a protocol specification, security certification, launch authorization, or approval to issue BRT.**

This plan orders existing open launch gates by dependency so engineering work can proceed quickly without inventing consensus rules, network identity, trust keys, witness operators, economic parameters, or legal conclusions.

## Execution rule

Work may proceed in parallel only where tasks are genuinely independent. Every change must be reviewed against the current source and tests. A task is complete only when its implementation, regression tests, exact commit, and required independent evidence exist. A queued CI run is not a passing test. A design document is not an implementation. A local test is not an independent audit.

No Mainnet/Testnet public launch, Genesis initialization, founder allocation, or production issuance is authorized by this plan.

## Critical path

### Wave 0 — Preserve a safe baseline

- Confirm the exact main-branch commit before editing.
- Keep all existing fail-closed gates enabled.
- Run the full test suite in a reproducible environment and record the exact commit and result.
- Resolve queued or failed CI infrastructure before relying on CI evidence.
- Do not merge unrelated changes into a security-sensitive patch.

**Exit evidence:** clean repository state, exact tested commit, completed CI, retained test logs.

### Wave 1 — Freeze protocol decisions before implementation

- Resolve the canonical network-ID representation shared by local configuration, Genesis manifest, trust configuration, release policy, and persistent storage.
- Freeze network role, Genesis commitments, P2P magic, protocol version, consensus parameters, serialization/script identifiers, address identifiers, and storage compatibility.
- Freeze transaction/block serialization limits and byte-level vectors.
- Freeze full header consensus: retarget boundaries, MTP, future-time rules, timestamp limits, and network-specific genesis difficulty.
- Obtain independent reproduction of canonicalization and consensus vectors.

**Hard stop:** do not hash, normalize, truncate, or reinterpret the current free-form local network ID to fit the manifest's 32-byte hexadecimal format. That would silently create a new protocol rule.

**Exit evidence:** reviewed normative specification, canonical byte vectors, independent implementation results, explicit owner approval of the exact specification digest.

### Wave 2 — Persistent identity and trust freshness

- Implement one validated network-identity object only after Wave 1 is approved.
- Pass the same validated identity through configuration, persistent state, P2P manager, and runtime.
- Persist exact canonical identity bytes and digest atomically.
- Reject missing or mismatched identity before mutation or networking.
- Define and test backup-first migration; never silently assign identity to a legacy database.
- Select and govern an external anti-rollback witness architecture before implementation.
- Implement challenge-bound witness responses, freshness, monotonic state, quorum, revocation, equivocation evidence, and recovery only after the protocol is approved.

**Hard stop:** caller-supplied pins and local SQLite checkpoints are not authenticated external trust. No trust-on-first-use for production.

**Exit evidence:** adversarial rollback/replay tests, crash tests, independent witness verification, documented operator/key custody, external review.

### Wave 3 — Deterministic ledger integrity

- Authenticate Genesis and bootstrap provenance.
- Implement read-only deterministic UTXO replay from the exact approved Genesis and frozen consensus rules.
- Reconstruct UTXOs, provenance, issuance, active tip, and undo metadata from ordered block/transaction history.
- Compare reconstructed state against persisted state and fail closed on any mismatch.
- Verify all bootstrap outputs and their historical metadata without inventing unknown MTP or provenance.
- Test tampering, missing rows, reordered transactions, corrupted undo data, interrupted writes, and restore scenarios.

**Exit evidence:** independent replay reproduction and adversarial no-mutation tests.

### Wave 4 — Consensus and cryptographic execution

- Complete production script execution and signature verification using reviewed libraries.
- Publish independent transaction/script/signature vectors.
- Complete contextual header and block validation before active-state mutation.
- Complete side-branch storage, chainwork selection, deterministic reorganization, and crash-safe recovery.
- Add cross-client consensus tests and differential testing.

**Exit evidence:** independent implementation agreement, fuzz/property/fault tests, external cryptographic and consensus review.

### Wave 5 — P2P and operational hardening

- Define measured node-wide and per-peer limits for memory, queues, bandwidth, handshakes, connections, tasks, and file descriptors.
- Implement discovery and synchronization with strict framing and bounded resource ownership.
- Run adversarial load, churn, slow-peer, partition, and shutdown tests on documented hardware.
- Complete reproducible builds, signed releases, exact dependency locks, monitoring, backups, incident response, and operational runbooks.

**Exit evidence:** measured deployment envelope, independent network security review, reproducible release artifacts, recovery drills.

### Wave 6 — Wallet, mining, and Genesis reproduction

- Implement wallet key generation, secure storage, signing, address handling, backup, and recovery.
- Add independent wallet vectors and recovery drills.
- Implement mining software against the frozen consensus rules.
- Reproduce Genesis independently from the exact approved parameters and manifest.
- Verify supply accounting, reward boundaries, integer rounding, and maximum issuance.

**Hard stop:** no real founder output or issuance initializer until the exact manifest digest and founder locking script have separate explicit approval and all authorization gates pass.

**Exit evidence:** independent wallet/miner/Genesis reproduction, supply proofs, reviewed one-time initializer and failure tests.

### Wave 7 — Independent launch review and legal authorization

- Complete external security review and resolve every critical/high finding.
- Complete qualified Iraqi legal review covering issuance, mining, custody, exchange, marketing, fundraising, AML/CFT, consumer protection, tax, sanctions, and data obligations.
- Publish governance, supply, mining, treasury, upgrade, disclosure, and incident-response policies.
- Conduct a controlled private test period only after the required approvals and technical gates.
- Make a separate, explicit decision for any public Testnet, Genesis issuance, or Mainnet launch.

**Exit evidence:** signed review reports, legal advice, approved operations/governance package, explicit launch decision for the exact release and manifest digest.

## Parallel work boundaries

The following can be developed independently after interface contracts are frozen: wallet user-interface work, build reproducibility, documentation, fuzz harnesses, P2P stress tooling, and independent test-vector implementations.

The following must not be parallelized by inventing incompatible interfaces: network identity, consensus serialization, Genesis manifest, trust configuration, witness checkpoint encoding, and persistent identity metadata. These share cryptographic and consensus commitments and require one reviewed specification first.

## Current known blockers

- The local Testnet network ID is free-form text, while Genesis/trust prototypes require 32-byte lowercase hexadecimal.
- Persistent storage does not bind the complete network identity.
- The local trust checkpoint does not authenticate external pins or prevent full database snapshot rollback.
- No witness operators, keys, quorum, or external monotonic evidence are configured.
- Bootstrap provenance and deterministic full UTXO replay remain open.
- Full script execution, production consensus, complete P2P resource policy, wallet/miner, independent review, and legal review remain open.
- Mainnet launch gates remain open; the current prototype is not production-ready.

## Reporting format

For each future work item, report:
1. exact files and behavior changed;
2. exact commit SHA;
3. tests run and exact tested SHA;
4. CI run ID and final conclusion, if available;
5. remaining limitations and independent evidence still required.

Never report "complete" based only on a commit, a queued workflow, a passing narrow unit test, or a design proposal.
