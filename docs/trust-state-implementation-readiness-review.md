# BLACKROOT trust-state persistence implementation-readiness review

**Status: SOURCE REVIEW ONLY. No trust-state persistence code is implemented by this review. No external pin authority is selected. No trust activation, Genesis issuance, Testnet, or Mainnet is authorized.**

## 1. Scope

This review compares the trust-state persistence proposal with the current repository primitives. It is a bounded source inspection, not an independent security audit and not a claim that the inspected modules are production-ready.

## 2. Existing primitives observed

### Data-directory lock

`src/blackroot_data_dir_lock.py` provides an exclusive non-blocking POSIX `flock` on `.blackroot-node.lock`, creates the data directory, writes the owning PID, and fsyncs the lock file. It deliberately leaves the lock file in place to avoid split-lock races. The lock is advisory and only coordinates processes that use the same locking convention.

The current `PersistentNodeState` constructor in `src/blackroot_node_state.py` does not acquire or require a `DataDirectoryLock`. Therefore the existence of the lock class does not prove that every node-state or future trust-state access is serialized under it. Integration must be explicit and tested; do not infer lock ownership from a data-directory path.

### SQLite transaction coordinator

`src/blackroot_sqlite.py` currently:

- opens a SQLite connection;
- enables foreign keys and a busy timeout;
- enables WAL mode, retrying a locked journal-mode transition;
- sets `PRAGMA synchronous = FULL`;
- exposes a restricted connection facade that blocks store-level commit, rollback, close, and executescript;
- uses explicit `BEGIN IMMEDIATE`, commits once on success, and rolls back on exceptional exit.

These are useful transactional building blocks. They do not authenticate an external policy, prevent restoration of an old database snapshot, establish owner identity, or prove power-loss guarantees for every filesystem/device. The coordinator also does not itself acquire the data-directory process lock.

### Node state

`PersistentNodeState` can use the coordinated SQLite connection for headers, UTXOs, and the recovery journal. Its current startup path verifies selected persistent state and reconciles the recovery journal, but it has no trust-state table, external-policy verifier, or trust-state rollback check.

## 3. Blocking integration gaps

Before implementing persistent trust state, the project must resolve and test all of the following:

1. **Lock ownership contract:** decide whether a higher-level node lifecycle object owns the data-directory lock or whether a dedicated locked-state factory does. Avoid acquiring the same lock recursively in multiple constructors. Make it impossible for trust-state read/write paths to run without the required lock.
2. **Data-directory identity:** derive the SQLite database and lock location from one canonical resolved data directory; reject path aliases and unsafe placement outside that directory.
3. **Transaction ownership:** trust-state acceptance must use the same node-owned SQLite transaction boundary as its dependent state, or a separately justified atomic protocol. A store must never commit independently when given a coordinator-owned connection.
4. **External policy verification:** the acceptance API must receive an authenticated, fresh policy result from a separately selected mechanism. Raw caller-supplied digest/sequence values are not sufficient.
5. **Startup order:** acquire lock, authenticate current external policy, validate persisted trust state, compare sequence/digest/predecessor, then expose trust-dependent functionality. Missing or unverifiable external evidence must fail closed.
6. **Rollback test:** restore a byte-for-byte old database backup while the external pin remains newer and prove that startup rejects it. A local-only test cannot demonstrate external anti-rollback.
7. **Fault testing:** add subprocess crash tests around the trust-state transaction, competing process tests, corrupt/truncated database tests, disk-full/permission fault injection, and reopen checks. Process-exit tests do not equal physical power-loss certification.
8. **Operational recovery:** define independently authorized recovery for lost/corrupt state and compromised policy signers. Never silently reset the sequence or accept the local backup as current authority.

## 4. Recommended implementation boundary

Do not add a trust-state persistence table or API until the external release-policy distribution model, authentication, freshness, quorum, and recovery governance have been selected and independently reviewed.

After that decision, implement in small stages:

- a versioned immutable validated-policy result type whose provenance cannot be forged by passing arbitrary raw values through the public acceptance API;
- a lock-enforced node lifecycle boundary;
- a trust-state schema and explicit transactional transition;
- startup comparison with external policy;
- adversarial and crash-recovery tests;
- independent review before any trust-dependent activation.

The type boundary alone is not cryptographic authentication. It must be constructed only by the verified external-policy layer, and the trust root for that layer must be independently established.

## 5. Current conclusion

The repository has reusable POSIX locking and SQLite transaction primitives, but they are not yet wired into a mandatory trust-state lifecycle. The safe next step is to settle external policy authority and lock ownership, not to create a local sequence counter that could be mistaken for rollback resistance.

Until these gaps are closed, keep trust-state persistence unimplemented and all issuance/activation gates closed.
