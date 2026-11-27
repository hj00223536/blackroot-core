# Persistent Network Identity Audit

**Status: BOUNDED SOURCE AUDIT — IDENTITY GATE OPEN; NOT A PRODUCTION APPROVAL**

## Scope

Reviewed:

- `src/blackroot_node_state.py`
- `src/blackroot_header_store.py`
- `src/blackroot_utxo_db.py`
- `src/blackroot_node_config.py`
- `src/blackroot_node.py`

## Verified protections

1. `PersistentHeaderStore` persists and checks three parameters in `header_metadata`: schema version, proof-of-work limit, and configured genesis hash. On reopen, a non-empty header store must match those parameters exactly and the stored header DAG is replayed from the supplied genesis.
2. Header replay checks serialized header hashes, the unique genesis row, header linkage/admission, heights, and cumulative work through the in-memory chain implementation.
3. `PersistentNodeState._verify_persistent_tip()` checks active UTXO block heights and parent linkage against the replayed header DAG, compares stored headers with replayed headers, and requires the active UTXO tip to match its active block records.
4. The local CLI loads a strict `TestnetConfig` and passes its configured proof-of-work limit and genesis header into `PersistentNodeState.open_locked()`. The CLI reports the configured `network_id` in its startup record.

## Gaps and limits

1. **The persistent header identity does not include `network_id`, P2P message magic, or protocol version.** The header store binds to genesis hash and proof-of-work limit, not the complete configured network identity. The CLI's startup log reporting `network_id` is not a persisted identity check.
2. **The UTXO metadata table does not independently pin network identity or genesis.** Its metadata currently covers UTXO schema version and the accounting-only `bootstrap_issued_sats` value. In coordinated mode, UTXO state shares the SQLite file with header metadata, and the active-chain cross-check supplies a partial binding when active block records exist; this is not a separately authenticated UTXO network identity.
3. **No authenticated, externally pinned network-identity manifest is loaded at startup.** There is no demonstrated binding from a trust-policy pin to the configured network ID, message magic, protocol version, genesis parameters, consensus parameter set, and storage schema.
4. **Genesis hash alone is not a complete protocol identity.** Different configurations could reuse a genesis header while differing in P2P or other non-genesis protocol parameters. Those parameters have not all been frozen as a normative Mainnet specification.
5. This audit does not establish deterministic full UTXO replay, authenticated bootstrap provenance, race-free SQLite file opening, external policy freshness, or production restore safety. Those remain separate open gates.

## Required design before implementation

- Freeze a versioned canonical network-identity document only after the full protocol parameter set is reviewed and approved.
- Include at minimum a stable network identifier, genesis block/header commitments, proof-of-work and retarget parameters, serialization/address/script rules, P2P magic and protocol compatibility, and relevant storage schema/upgrade identifiers.
- Define canonical encoding, domain-separated digest, trust-anchor and external pin distribution, freshness/anti-rollback rules, key rotation/revocation, and recovery.
- Persist the accepted identity binding in a dedicated metadata record and reject any mismatch before state mutation. Define safe migration behavior; do not silently rewrite identity metadata on an existing database.
- Test fresh initialization, reopen, same-genesis/different-network-ID, changed message magic, changed protocol version, changed consensus parameters, corrupted or missing identity metadata, downgrade/rollback, and interrupted migration.
- Independently review the specification, implementation, trust distribution, and compatibility vectors before closing the gate.

## Decision

**Keep the persistent network-identity gate OPEN.** Existing code provides meaningful genesis-hash and proof-of-work-limit binding through the header store, plus active UTXO/header cross-checks. It does not yet persist and authenticate the complete network identity. No Mainnet readiness or launch authorization follows from this audit.
