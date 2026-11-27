# Persistent network identity source audit

**Status: source audit only. The identity-binding design remains unimplemented and unapproved.**

## Files and code paths inspected

- `src/blackroot_node_config.py`: `TestnetConfig` carries
  `network_id`, four-byte `message_magic`, `protocol_version`,
  Genesis header/hash, and `pow_limit`.
- `src/blackroot_node_state.py`: `PersistentNodeState.open_locked()`
  accepts a data directory, database path, `pow_limit`, Genesis header,
  and optional adjusted-time provider. It does not accept a `TestnetConfig`
  or a canonical network identity object.
- `src/blackroot_header_store.py`: `PersistentHeaderStore` writes and
  checks only three metadata entries: `schema_version`, `pow_limit`,
  and `genesis_hash`.

## Concrete gap

The persisted header-store metadata does not bind the database to the complete
configured network identity. In particular, `network_id`, `message_magic`,
and `protocol_version` are not stored or compared during reopen. Other
consensus, serialization, script, address, and storage-compatibility
identifiers are likewise not represented in this metadata.

Consequently, the storage layer cannot distinguish two configurations that
share the same Genesis header and proof-of-work limit but differ in network ID,
P2P magic, or protocol version. The current `open_locked()` API has no input
from which it could perform those comparisons. This is a source-level finding;
it is not a claim that a public network is running or that a specific deployed
database has been cross-opened.

## Why no quick patch was applied

The repository's local testnet configuration accepts a free-form text
`network_id`, while Genesis manifest and trust-configuration prototypes
require exactly 32 bytes represented as lowercase hexadecimal. Converting,
hashing, truncating, or normalizing one representation into another would
silently define a protocol identity rule without an approved specification.

The persistent identity design therefore needs an explicit canonical schema,
versioned serialization and digest vectors, an externally authenticated
expected-identity pin with freshness/anti-rollback governance, and an
atomic fail-closed binding/migration plan before implementation.

## Required implementation and tests

1. Approve one canonical network-ID representation and identity schema shared
   by local config, Genesis manifest, trust configuration, release policy,
   and persistent storage.
2. Define the complete identity payload and deterministic canonical bytes;
   independently reproduce digest vectors in another implementation.
3. Authenticate the expected identity using an independently governed pin;
   define sequence, freshness, rollback, rotation, revocation, and recovery.
4. Bind identity atomically to the coordinated database before any state
   mutation or P2P networking; reject absent, malformed, or mismatched identity.
5. Define a backup-first migration for legacy databases. Never infer or silently
   assign identity to an existing database.
6. Add tests for same-Genesis/different-network ID, changed message magic,
   changed protocol version, changed consensus parameters, missing/corrupt
   identity rows, tampering, stale pins, rollback, interrupted migration, and
   no-mutation failure behavior.
7. Have independent reviewers verify both the specification and implementation.

## Conclusion

Persistent storage currently checks a useful but incomplete subset of
parameters. It does not authenticate or persist the full network identity.
Keep the persistent network identity launch gate open; do not describe this
storage lifecycle as safe for multi-network production use.

## Startup and runtime wiring detail

The local CLI currently performs the following composition:

1. It parses `TestnetConfig`.
2. It passes only `config.pow_limit` and `config.genesis_header` to `PersistentNodeState.open_locked()`.
3. It creates the peer manager through `config.create_peer_manager(version)`, which applies the configured four-byte message magic and protocol-version floor to P2P sessions.
4. It passes the protocol version separately to `BlackrootNodeRuntime`.
5. It prints `config.network_id` in the startup event.

This means the current CLI does use the configured P2P magic/version for its live manager, but those values are not supplied to or persisted by the state store. The startup log is informational only. In addition, the runtime constructor accepts a state, a manager, and a protocol version as separate arguments; it does not have a canonical identity object with which to prove that the manager and persistent state belong to the same network. This is an API composition gap, not evidence that the current loopback CLI has actually connected mismatched networks.

The appropriate fix remains the approved, canonical identity object described in the design proposal. Do not patch this by adding ad hoc constructor arguments or by hashing the free-form local `network_id`: that would create another partially specified identity format. Once the identity schema and external pin are approved, one validated identity should be passed through configuration, persistent-state initialization/reopen, peer-manager construction, and runtime composition, with mismatch rejection before networking or state mutation.
