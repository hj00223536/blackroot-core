# P2P resource-boundary audit

**Status: audit only. No resource policy is approved and no public listener is authorized.**

## Scope reviewed

This audit covers the current local-development P2P configuration and peer
manager in `src/blackroot_node_config.py` and
`src/blackroot_p2p_manager.py`. It is not a protocol specification, load test,
or independent security review.

## Observed implementation facts

- `TestnetConfig.max_peers` and `PeerManager.max_peers` require a positive
  integer and reject booleans, but neither defines an implementation ceiling.
  A configuration can therefore request an arbitrarily large peer count.
- The manager accounts for established peers plus outbound connection
  reservations. This is useful admission accounting, but the configured cap
  itself is unbounded.
- Each peer receives its own message-rate and byte-rate token buckets. These
  limits therefore scale with the number of admitted peers; they do not impose
  a node-wide aggregate bandwidth or message-processing budget.
- The manager bounds its recent background-error deque to 100 entries.
- The configured payload limit is bounded by `DEFAULT_MAX_PAYLOAD`, but a
  per-message cap alone does not bound aggregate memory, queued writes, parser
  work, or concurrent connection-handshake overhead.
- Inbound connections over the configured peer cap are closed after accept.
  This does not by itself establish protection against connection churn,
  accept-queue pressure, or operating-system resource exhaustion.
- `TestnetConfig.validate_bind_host` permits loopback only, but
  `PeerManager.start_server` accepts a host argument directly. A caller must
  explicitly enforce the configuration boundary; the manager itself is not
  an authenticated public-listener policy.
- The module documentation explicitly excludes peer discovery, encryption,
  cryptographic identity, and production anti-Sybil policy.

## Required decisions before a public network

Do not select numeric limits by guesswork. A reviewed resource policy must
specify and justify, at minimum:

1. A hard maximum peer count and separate inbound/outbound quotas.
2. A node-wide aggregate inbound/outbound byte budget and message/work budget,
   in addition to per-peer rate limits.
3. Bounds for concurrent handshakes, connection attempts, pending writes,
   per-peer queues, parser allocations, and total memory attributable to peers.
4. Connection-churn controls, admission policy, duplicate-identity handling,
   and behavior under file-descriptor and socket exhaustion.
5. Timeouts and backpressure behavior under slow readers, slow writers, and
   peers that send valid but expensive message sequences.
6. Safe defaults for each supported deployment profile, derived from measured
   resource envelopes and documented hardware assumptions.
7. Metrics, bounded logs, operator alerts, and deterministic shutdown behavior.

## Required validation

- Stress tests at, below, and above each configured boundary.
- Many simultaneous inbound and outbound connection attempts.
- Slowloris-style handshakes, slow readers/writers, disconnect/reconnect churn,
  oversized and fragmented frames, and valid-message CPU pressure.
- Aggregate traffic tests proving node-wide limits hold when many peers each
  remain below their individual rate limits.
- Memory, file-descriptor, task-count, and socket-count measurements under
  sustained adversarial load.
- Fault injection during accept, handshake, callback execution, and shutdown.
- Independent review of the final policy and implementation.

## Conclusion

The current manager has useful per-peer admission and rate-control primitives,
but the unbounded configurable peer count and absence of node-wide resource
budgets leave the P2P resource policy incomplete. Keep this gate open. Do not
enable public binding or describe the prototype as DoS-resistant until the
policy, tests, and independent review are complete.
