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

## Additional transport and admission source review

The following details were checked directly in `src/blackroot_p2p_manager.py`
and `src/blackroot_p2p_transport.py`:

- `PeerManager._load()` counts managed peers plus outbound reservations. Outbound
  connect reserves a slot before awaiting the socket open; inbound accept checks
  the same count and immediately closes a connection when the configured cap
  has been reached. This prevents ordinary concurrent outbound calls from
  oversubscribing the configured count, but it does not define separate
  inbound/outbound quotas or a hard implementation ceiling.
- The listener uses `asyncio.start_server` without an explicit deployment
  backlog, connection-rate policy, or per-source admission policy. Rejected
  inbound sockets have already reached the accept callback; this is not a
  pre-accept resource shield.
- Each admitted peer gets its own `PeerConnection`, receive task, send lock,
  and three independent token buckets (control-message count, data-message
  count, and data bytes). There is no shared manager-level bucket or global
  work counter. Thus a peer population can multiply the aggregate configured
  per-peer allowance.
- The receive loop reads the fixed 24-byte frame header, checks the configured
  and command-specific payload lengths, charges the peer's rate bucket, and
  then uses `readexactly(length)`. The full read is wrapped in the handshake
  or idle timeout. This bounds an individual declared frame and its wait time,
  but the timeout is not a global concurrency or memory budget.
- The default frame ceiling is 2,000,000 bytes, and the transport also applies
  command-specific ceilings for block, headers, inventory, and control frames.
  These are useful per-frame protections; they do not cap the sum of payloads
  concurrently resident across peers or messages queued by application tasks.
- `PeerConnection.send()` serializes writes with an `asyncio.Lock`, writes a
  complete encoded frame, and awaits `writer.drain()`. The lock serializes
  actual writer access, but there is no explicit maximum number/bytes of
  callers waiting to send or a manager-wide pending-write budget.
- `PeerManager._track()` creates one task per peer and retains it in a set.
  Peer count indirectly bounds these tasks only by the configurable cap; with
  no hard cap, task and associated object counts are not bounded by a fixed
  implementation limit.
- The current local CLI validates loopback bind hosts before calling the
  runtime, but `BlackrootNodeRuntime.listen()` and `PeerManager.start_server()`
  can be called directly with arbitrary host arguments. The loopback rule is
  therefore a composition-level local-prototype safeguard, not an intrinsic
  listener security boundary.

These findings are source-level observations, not measurements of peak memory,
file descriptors, kernel accept queues, or throughput under load. Those require
instrumented stress and fault tests on the supported deployment platforms.

## Focused test gaps identified

Existing tests cover peer handshakes, configured peer-count admission, rate
bucket propagation, bounded background-error history, concurrent inbound and
outbound admission races, and slow/incomplete handshake cleanup. In particular,
the manager tests exercise concurrent outbound dials, inbound accept bursts,
and a mixed-direction race at the configured peer cap. Transport tests exercise
timeouts while a header or version payload is incomplete, and the manager test
checks that a timed-out inbound peer releases its managed peer slot.

These are focused correctness tests using local asyncio streams and short test
timeouts. They are not load tests and do not prove hard global resource limits;
no node-wide limits exist. Remaining validation work, to be paired with an
approved resource policy, includes:

1. repeated connection churn and bounded pending handshakes/dials under load;
2. aggregate bytes/messages/work across many individually compliant peers;
3. bounded pending send calls/bytes with slow readers and blocked drains;
4. total memory, task, socket, and file-descriptor ceilings under adversarial
   load, including clean shutdown after overload;
5. fairness and backpressure so one peer cannot monopolize global capacity.

No numeric policy is selected by this audit. Values must follow documented
hardware profiles, measured workloads, operator requirements, and independent
security review; do not infer production-safe defaults from the local testnet
configuration.

## Outbound send-queue and pre-lock allocation finding

A follow-up review of `PeerConnection.send()` found a concrete aggregate
memory exposure that is not visible from the existence of the per-peer send
lock:

- The method calls `encode_message()` and constructs the complete frame before
  acquiring `_send_lock`. Concurrent callers can therefore each allocate and
  retain a full encoded frame while waiting for the lock.
- The lock serializes `writer.write()` and `writer.drain()`, but does not bound
  the number of tasks waiting to acquire it, the aggregate bytes held by those
  tasks, or the time a caller may wait behind a slow reader.
- There is no explicit send-waiter counter, per-peer pending-byte reservation,
  node-wide pending-byte reservation, write-drain deadline, or cancellation
  accounting for such reservations.
- The configured maximum frame size constrains each encoded frame only. It
  does not constrain the sum of frames retained by concurrent callers.

This is a source-level finding, not a demonstrated exploit or measured memory
impact. It does mean that the current send lock must not be described as a
bounded outbound queue or backpressure policy.

Before implementation, the reviewed resource policy must define whether sends
are rejected immediately or admitted through a bounded queue; reserve both
waiter capacity and byte capacity before encoding or retaining a frame; define
per-peer and node-wide accounting; release reservations exactly once on
completion, cancellation, write failure, and shutdown; and specify a bounded
write-drain/shutdown behavior. The implementation must not hold an unbounded
number of tasks waiting on an asyncio lock. Any queue limit must come from an
approved measured profile, not an arbitrary constant.

The receive path has a related but distinct boundary: it validates the frame
length and charges the peer-local token buckets before reading the payload,
then retains the complete payload for decoding and handler execution. This
protects against oversized individual frames and per-peer rate excess, but
there is still no shared node-wide reservation for payload bytes retained
across peers or application callbacks. The receive and send budgets therefore
need one coherent ownership/accounting model rather than independent counters.
