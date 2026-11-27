# BLACKROOT trust-state persistence and rollback-resistance design

**Status: DESIGN PROPOSAL ONLY. Not implemented, not independently reviewed, and not an authorization to activate a trust anchor or issue BRT.**

## 1. Security objective

Persist the last accepted trust-configuration identity so a process restart cannot accidentally accept an older configuration. Preserve fail-closed behavior across interrupted writes, corrupted state, missing state, and configuration rotation.

A local SQLite row or ordinary file is not, by itself, rollback-resistant against an attacker who can restore or replace the data directory. This design must not claim otherwise.

## 2. Threat model and limits

The design distinguishes:

- **Process crash / power loss:** addressed through a transactional state update, durable commit, and startup verification.
- **Concurrent local node processes:** addressed by the existing exclusive data-directory lock; trust-state updates must occur while that lock is held.
- **Accidental corruption or partial writes:** detected by schema checks, digest verification, and fail-closed startup.
- **Malicious replacement of the local database or a full old backup:** not prevented by a local digest or SQLite transaction. Detection requires a trust anchor outside the replaceable data directory.
- **Compromise of the external pinning mechanism or owner key:** outside the protection of this persistence layer; requires separate governance, recovery, and independent review.

## 3. Required persisted record

A future versioned record should bind all of the following:

- schema version;
- project and network identity;
- accepted trust configuration sequence;
- exact trust configuration digest;
- exact predecessor digest (null only for sequence 1);
- accepted-at software/release-policy identifier;
- state record digest and integrity version.

Do not store private keys, signing seeds, wallet secrets, or credentials in this record.

The record is an audit/cache of a decision already authorized by an independently pinned release policy. It must never create authority by itself.

## 4. Acceptance transition

A future acceptance API must receive a fully validated trust configuration plus independently authenticated release-policy pins. It must reject unless:

1. the data-directory process lock is held;
2. network and project identifiers match the configured node;
3. configuration digest equals the external pin;
4. sequence equals the externally expected sequence;
5. sequence 1 has no predecessor, or later sequences link to the exact externally expected predecessor;
6. sequence is strictly greater than the locally persisted accepted sequence, except for an explicitly defined idempotent reopen of the exact same sequence and digest;
7. same sequence with a different digest is always rejected;
8. lower sequence is always rejected;
9. missing, malformed, or corrupt local state is not silently initialized or reset when prior acceptance may have occurred.

A local state record must not be used as the sole source of the expected sequence or digest. Doing so would allow an attacker who restores an older database to restore the older trust decision too.

## 5. Durability and atomicity requirements

Before implementation is considered:

- use one transactional store or a carefully specified atomic-write protocol;
- serialize updates under the existing node data-directory lock;
- use explicit transaction boundaries and durable commit settings;
- for file-based state, write a new file in the same directory, flush file contents, atomically replace the destination, and flush the parent directory where supported;
- never unlink and recreate the process lock file while another process may hold it;
- make update retries idempotent;
- define recovery for interrupted commit, torn/corrupt record, disk-full, permission failure, and unsupported filesystem semantics;
- preserve the previous record for forensic review without automatically falling back to it as trusted current state.

Filesystem and storage guarantees vary. The implementation must document supported platforms and refuse startup when required durability semantics cannot be established.

## 6. External rollback detection

At least one independent anti-rollback source is required before production use. Candidate approaches require security review and an operational threat model:

- a release-policy digest and expected sequence pinned in a separately controlled deployment/release environment;
- an independently administered append-only transparency log with verifiable inclusion and consistency proofs;
- a hardware-backed monotonic counter or protected keystore where the deployment platform actually provides and validates the required guarantees.

No candidate is selected by this document. A signed but stale release policy is still stale; freshness and recovery procedures must be specified. If the external source is unavailable, stale, inconsistent, or unverifiable, the node must refuse trust activation rather than fall back to local state.

## 7. Startup behavior

Startup must acquire the data-directory lock before reading or mutating trust state. It then validates the state schema, record digest, network identity, and external anti-rollback evidence. A mismatch, missing external pin, lower sequence, same-sequence digest conflict, or corrupt record stops trust-dependent operations.

Do not silently repair trust state from a manifest, approval record, local backup, or peer-provided data. Recovery requires an independently authorized and reviewed recovery decision.

## 8. Required tests

Before implementation acceptance, test:

- first sequence accepted only with null predecessor;
- next sequence accepted only with exact previous digest;
- sequence downgrade rejected after restart;
- same sequence / different digest rejected;
- old database snapshot restored while external pin remains newer;
- missing or unavailable external pin fails closed;
- corrupt and truncated state fail closed;
- process termination before, during, and after commit;
- disk-full and permission failures do not advance in-memory accepted state;
- two processes racing to accept different successors;
- lock loss / lock acquisition failure;
- retry of the exact already-committed transition is idempotent;
- unsupported filesystem durability semantics fail closed.

Use subprocess crash tests and fault injection; ordinary unit tests alone are insufficient.

## 9. Integration boundary

The existing `DataDirectoryLock` is an advisory POSIX process lock. It prevents cooperating node processes from concurrently owning the same data directory; it does not defend against privileged local modification or backup rollback.

The existing trust validator accepts external pins as function arguments. It does not authenticate their provenance or persist monotonic state. No trust-state persistence is implemented by this proposal.

The detached approval verifier, trust configuration parser, and any future persistent state must remain separate from genesis issuance and node startup until independent review and explicit owner approval.

## 10. Stop conditions

Until external pinning, durable state semantics, recovery governance, adversarial tests, and independent review are complete:

- do not configure a real owner key;
- do not treat local persisted trust state as an authoritative trust anchor;
- do not create or activate a founder allocation;
- do not initialize production issuance;
- do not announce public testnet or mainnet readiness.
