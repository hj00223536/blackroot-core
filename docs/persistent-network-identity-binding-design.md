# Persistent Network Identity Binding Design

**Status: DESIGN PROPOSAL ONLY — NOT IMPLEMENTED, NOT APPROVED, AND NOT A MAINNET CONFIGURATION.**

## Purpose

Prevent a persistent node database from being reopened under a different network configuration merely because a subset of parameters (currently the genesis header hash and proof-of-work limit) still matches.

This proposal does not select or freeze any BLACKROOT Mainnet constants. It must not be used to infer a Mainnet network ID, P2P magic, protocol version, address format, or consensus parameter.

## Source audit baseline

The current `PersistentHeaderStore` stores and checks `schema_version`, `pow_limit`, and `genesis_hash`. Its replay rebuilds the header DAG from the supplied genesis. `PersistentNodeState` cross-checks active UTXO block records against that replayed header DAG. The local `TestnetConfig` separately contains `network_id`, four-byte `message_magic`, `protocol_version`, genesis, and proof-of-work limit, but those complete values are not persisted as one authenticated database identity.

The existing checks are useful and must remain. They are not a complete network identity binding.

## Proposed identity document

After (and only after) the normative protocol specification is frozen, define a versioned identity document containing:

- identity schema/version and canonicalization identifier;
- stable network identifier and network role (development, public test network, or main network);
- genesis header and block commitments, including exact serialized bytes;
- proof-of-work limit, target spacing, retarget interval, adjustment clamps, timestamp rules, and other frozen consensus parameters;
- transaction/block serialization and script-rule version identifiers;
- P2P message magic, protocol version and compatibility policy;
- address and key-encoding identifiers where relevant;
- storage schema compatibility identifier and required migration policy.

Every field must have a normative type, range, byte order, and interpretation. Unknown fields and missing required fields fail closed. The document must not include mutable runtime observations such as peer count or local wall-clock time.

## Canonical digest and authentication

1. Freeze a strict canonical encoding and publish byte-for-byte vectors in at least two independently maintained implementations.
2. Compute a domain-separated cryptographic digest over the canonical bytes. The domain string and digest algorithm must themselves be frozen in the specification.
3. Authenticate the expected digest through the separately governed external trust/pin mechanism. A digest stored only beside the database is not an authenticity anchor.
4. Define sequence numbers, predecessor digests, freshness, rollback rejection, key rotation, revocation, quorum or separation-of-duties rules, and recovery before deployment.
5. Keep network identity approval separate from founder allocation approval and software release signing.

The existing Genesis trust prototype does not by itself authenticate an external identity pin or provide persistent anti-rollback state. Do not reuse its test fixture key as an owner or production trust key.

## Database binding and startup behavior

- Store the canonical identity bytes, digest, and identity schema version in a dedicated metadata record in the coordinated database.
- On first initialization, require a separately authenticated expected identity and commit the binding atomically with the initial database schema. No implicit trust-on-first-use for production.
- On every reopen, verify the external pin first, then compare the exact canonical identity bytes and digest before any state mutation, peer networking, or issuance.
- A missing identity record in an existing non-empty database is an error, not permission to initialize it silently.
- A mismatch in network ID, role, magic, protocol version, genesis, consensus rules, or storage compatibility must fail closed.
- Never rewrite an existing identity record as a repair shortcut. Any migration requires a separately specified, authenticated, backup-first migration with explicit operator authorization.
- Preserve current genesis hash, proof-of-work-limit, header replay, UTXO/header cross-check, and SQLite integrity checks as independent defense-in-depth checks.

## Required test matrix

- fresh database initialization with valid external pin;
- exact identity reopen is idempotent;
- same genesis but different network ID;
- same genesis but different network role;
- changed message magic;
- changed protocol version or compatibility policy;
- changed proof-of-work/retarget/timestamp rule;
- changed serialization/script/address identifier;
- changed storage compatibility identifier;
- missing, malformed, duplicate, or unknown identity fields;
- corrupted stored canonical bytes or digest;
- absent identity metadata in an existing database;
- untrusted, revoked, stale, or rollback external pin;
- interrupted initial binding and interrupted migration;
- concurrent process attempting first initialization;
- legacy database migration refusal unless an explicit approved migration exists.

Every rejection test must assert that no database rows, metadata, active tip, UTXO state, or issuance counters were changed.

## Explicit non-goals and limits

This binding does not replace full deterministic UTXO replay, authenticated bootstrap provenance, complete consensus validation, safe backup/restore, race-free descriptor-relative SQLite opening, external security review, legal review, or operational readiness. It does not make the current local testnet CLI a production node.

## Approval required before implementation

The owner and independent reviewers must approve the normative identity schema, canonicalization vectors, trust/pin authority and recovery model, migration behavior, and exact implementation scope. No production identity values or keys are supplied by this proposal.
