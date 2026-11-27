# P2P Node-Wide Resource Policy Design

**Status: DESIGN PROPOSAL ONLY — NOT IMPLEMENTED, APPROVED, OR A PRODUCTION SECURITY CONTROL.**

This document translates the source findings in
`p2p-resource-boundary-audit.md` into an implementation and validation plan.
It deliberately selects no production numeric limits. No public listener,
peer-discovery service, or Mainnet operation is authorized by this proposal.

## 1. Goals and non-goals

The implementation must make resource use bounded at both the individual
connection and whole-node levels. Per-peer limits remain useful, but must not
multiply into an unbounded aggregate allowance as peer count increases.

The policy must fail closed when required limits are missing, invalid, or
inconsistent. It must be applied before accepting public traffic and before
allocating peer-owned tasks or buffers.

This proposal does not define consensus rules, network identity, peer
authentication, Sybil resistance, discovery, encryption, or an operational
deployment profile. It does not claim that rate limits alone prevent DoS.

## 2. Policy model

Introduce one immutable, validated `P2PResourcePolicy` object, separate from
consensus configuration. It should contain named limits in these categories:

| Category | Required policy dimensions |
|---|---|
| Admission | total peers; inbound peers; outbound peers; pending inbound handshakes; pending outbound dials; per-source admission quota if a trustworthy source identity is defined |
| Time | connect, handshake, header-read, payload-read, idle, write-drain and shutdown deadlines |
| Frame and parser | global frame ceiling; command-specific ceilings; parser work units per message; maximum nested/decoded item counts |
| Memory | per-peer receive budget; node-wide receive budget; queued application payload bytes; pending outbound bytes |
| Work and rate | per-peer message/byte rates; node-wide message/byte rates; weighted command work budget; burst ceilings |
| Runtime objects | maximum peer tasks; pending callback tasks; pending send waiters; background error and telemetry retention |
| OS resources | socket/file-descriptor budget; listener backlog; reserved descriptors for logging, storage and shutdown |

All integer fields must reject booleans. All rates and timeouts must be finite,
positive numbers where applicable. Cross-field invariants must be explicit:
inbound plus outbound allocations cannot exceed total peer capacity; pending
handshakes cannot exceed their reserved capacity; per-peer maxima multiplied
by maximum peers must fit within aggregate budgets or be subject to a shared
global budget.

Do not use a permissive default for production. A missing production policy
must prevent public listener startup. Local loopback development may use an
explicitly named development profile, but it must never be implicitly promoted
to a public profile.

## 3. Shared admission controller

Add a manager-owned admission controller with atomic reservation/release
operations for each resource class. Admission must reserve capacity before
creating a peer task or beginning expensive handshake work.

Required invariants:

1. Active peers plus reserved inbound/outbound slots never exceed the total cap.
2. Inbound and outbound counts never exceed their own caps.
3. Pending handshakes and dials have separate bounded reservations.
4. Every reservation is released exactly once on success, rejection,
   cancellation, timeout, exception, and shutdown.
5. Concurrent accept/connect races cannot oversubscribe a quota.
6. Failed admission closes or rejects the socket without allocating a
   long-lived peer task.
7. Shutdown prevents new reservations and drains/releases existing ones.

The current asyncio callbacks execute on one event loop, but the controller
should still make reservation transitions synchronous and indivisible with
respect to await points. If future code introduces threads or multiple loops,
the concurrency model must be redesigned and tested rather than assumed safe.

## 4. Node-wide budgets and backpressure

Per-peer token buckets should charge a shared node-wide budget as well as the
peer-local budget. Use monotonic time. A message must pass both budgets before
the body is read or expensive parsing begins.

Charge more than raw bytes where operations have materially different costs.
For example, parsing a large block, validating many transactions, and
processing a small ping must not all have the same work cost. The work-cost
model must be explicit, bounded, versioned as implementation policy, and
tested; it must not alter consensus validity.

Memory reservations must cover bytes retained after the socket read, including
decoded or queued copies where present. Ownership transfer between transport
and application queues must transfer the reservation rather than release and
reacquire it later. Release reservations on consumption, rejection,
cancellation, disconnect, and failed callbacks.

Outbound writes require a bounded pending-byte and waiter budget. A slow
reader must trigger backpressure or disconnect policy before unbounded
application callers accumulate behind `writer.drain()`. Never silently drop
consensus-relevant data; define explicit retry, disconnect, and resynchronization
semantics for each message class.

## 5. Listener and deployment boundary

The local CLI's loopback validation is not an intrinsic protection in
`PeerManager.start_server()` or `BlackrootNodeRuntime.listen()`. Before any
public listener is considered:

- require an explicit deployment mode and validated production resource policy;
- validate bind-address policy at the listener boundary, not only in CLI code;
- define OS-level file-descriptor limits and reserved capacity;
- define listener backlog and connection churn behavior;
- define firewall, network segmentation, monitoring, and operator controls;
- ensure the application-level peer cap is not represented as protection
  against kernel accept-queue or upstream bandwidth exhaustion.

No public bind mode should be enabled by this design document alone.

## 6. Telemetry and fail-safe behavior

Expose bounded counters/gauges for active and reserved peers by direction,
pending handshakes, rejected admissions by reason, bytes/messages/work charged,
receive and send queue bytes, pending writers, task count, timeouts, and
resource-budget exhaustion. Telemetry itself must be bounded and must not
retain arbitrary peer payloads or attacker-controlled unbounded labels.

On budget exhaustion, behavior must be deterministic and fail closed:
reject new work, apply backpressure, or disconnect according to the message
class policy. Avoid process-wide crashes and avoid mutating chain or UTXO state
for a message rejected at the transport/resource layer.

## 7. Required tests before implementation approval

### Admission and concurrency
- simultaneous inbound accepts at each quota boundary;
- concurrent outbound dials and mixed inbound/outbound races;
- cancellation at every await point during reservation and connection setup;
- exact-once reservation release for all failure and shutdown paths;
- repeated connect/disconnect churn without leaked tasks, sockets, or counters.

### Aggregate budget behavior
- many peers each staying below their local rate but collectively exceeding
  the node-wide rate;
- aggregate burst exhaustion and monotonic-clock edge cases;
- weighted work accounting for large and small messages;
- reservation transfer across read, decode, callback, queue and completion;
- memory accounting under duplicated buffers and rejected parser inputs.

### Slow-peer and queue behavior
- peers that send headers slowly, stop mid-payload, or never complete handshake;
- peers that stop reading while the node sends;
- bounded pending writer waiters and queued bytes;
- callback handlers that block, raise, or never complete;
- overload shutdown with outstanding reads, writes and callbacks.

### Resource exhaustion and recovery
- descriptor pressure with reserved descriptors retained for shutdown/logging;
- task and memory ceilings under churn and aggregate traffic;
- clean recovery after cancellation, timeout, callback failure and shutdown;
- no chain/UTXO mutation when transport admission or resource charging fails;
- instrumentation-backed load tests on each supported deployment profile.

Use deterministic fake clocks for token accounting and property-based tests for
reservation invariants. Add fuzzing for frame parsing and command decoders.
Record measured peak memory, descriptor count, task count, throughput, and
latency under each test profile. A test that merely confirms a configured
counter is not a resource-exhaustion test.

## 8. How numeric limits are selected

No numeric values are approved here. For each proposed deployment profile:

1. identify supported hardware, OS, file-descriptor limits, and expected peer
   population;
2. measure baseline node memory, task, descriptor and bandwidth consumption;
3. measure per-peer worst-case retained memory and parser/validation cost;
4. reserve explicit capacity for storage, RPC/administration, logging, metrics,
   and shutdown;
5. run adversarial tests with safety headroom and documented service objectives;
6. obtain independent security review and operator approval;
7. publish the selected profile, rationale, test evidence, and rollback plan.

Never derive a production cap solely from a developer laptop, local testnet
configuration, or a single successful stress run.

## 9. Implementation sequence

1. Add immutable policy schema and validation tests without changing defaults.
2. Add a manager-owned admission controller and unit/property tests.
3. Add shared node-wide rate and weighted-work budgets.
4. Add receive-memory ownership reservations and bounded outbound queues.
5. Add listener-boundary deployment-mode checks and explicit public-bind denial
   until a reviewed production profile exists.
6. Add telemetry and deterministic overload behavior.
7. Run adversarial tests and instrumented load tests on supported platforms.
8. Obtain independent security review; update launch gates only when evidence
   and approvals exist.

Each step must be a separate reviewable change. No step closes the Mainnet gate
by itself.

## 10. Explicit stop conditions

Stop and keep public networking disabled if any quota can be oversubscribed,
any reservation can leak or be released twice, any queue grows without a
configured bound, a slow peer can cause unbounded task/memory growth, a budget
failure can mutate chain state, or the measured deployment envelope is not
reproducible. A passing unit suite is not a substitute for adversarial load
testing or independent review.

## 11. Concrete send/receive reservation contract

This section narrows the implementation contract for the send-queue finding recorded in the source audit. It remains a proposal; it introduces no numeric limits and does not authorize production networking.

### Send path

The implementation must not encode a full frame and then wait on an unaccounted lock. The intended sequence is:

1. Validate command and payload type/length without making a retained frame copy.
2. Obtain a bounded send-waiter reservation and reserve the exact encoded frame byte count (header plus payload) against both peer and node-wide pending-send budgets. Reject immediately if either reservation fails.
3. Only after successful reservation, construct or enqueue the frame. The reservation owns the frame until the writer has completed or the operation has failed.
4. A single writer task per peer drains a bounded queue. Producers do not each wait directly on the stream writer lock. Queue admission and byte reservation must be one cancellation-safe operation with no await between the final capacity check and ownership transfer.
5. On successful drain, write failure, cancellation before queue ownership, cancellation after queue ownership, peer close, and manager shutdown, release the waiter and byte reservations exactly once. If a producer is cancelled after the writer owns the frame, cancellation must not cause the producer and writer both to release the same reservation.
6. Define whether cancellation after queue admission cancels the queued frame or merely stops waiting for its result. The choice must preserve protocol ordering and must not silently discard messages whose delivery is required for session correctness.

The queue needs explicit per-peer item and byte limits plus node-wide byte and waiter limits. A count-only queue is insufficient because frame sizes vary. The policy must also define a bounded drain deadline and shutdown deadline; a timeout closes the peer and releases all queue ownership deterministically. Do not rely on asyncio.Lock waiter behavior as a resource bound.

### Receive path and ownership transfer

For inbound data, reserve node-wide and peer receive capacity after validating the fixed header and before reading the declared payload. The reservation must cover the payload while it is read, decoded, and held by the application handler. If decoding or dispatch creates additional retained copies, either avoid those copies or account for them explicitly. Transfer reservation ownership to the handler/queue when dispatch is asynchronous; release only when the last accounted owner finishes, rejects, or is cancelled.

A peer disconnect must not release capacity still owned by a handler task. Conversely, a handler failure must not strand capacity. The node-wide budget must remain effective when many peers each stay below their local allowance.

### Required observable invariants

Tests must prove, not merely inspect counters, that:

- peer and node-wide pending send bytes never exceed configured budgets;
- peer and node-wide send waiter counts never exceed configured budgets;
- peer and node-wide receive reservations never exceed configured budgets;
- failed reservations occur before frame allocation or payload-body reads;
- all reservation paths release exactly once under cancellation at each await boundary, drain timeout, handler failure, disconnect, and shutdown;
- queue ordering is preserved for admitted messages;
- a slow reader cannot cause unbounded retained frames or waiting tasks;
- a slow handler cannot cause unbounded retained inbound payloads;
- concurrent peers cannot multiply local allowances beyond global caps.

Use test doubles that deliberately block write drain and handler completion, then release, cancel, or fail them in controlled order. Add property-based state-machine tests for reservation ownership transitions. Follow with instrumented adversarial load tests that record actual retained bytes, tasks, and file descriptors. Unit tests and fake counters alone do not establish a production memory ceiling.

## 12. Reservation primitive implementation status

A small synchronous reservation primitive now exists in
`src/blackroot_p2p_resources.py`, with focused tests in
`tests/test_p2p_resources.py`. It atomically charges count and byte capacity
across a set of budgets on one event loop, rejects without partial charges,
and detects double release. Its limits are explicit constructor inputs; it
selects no defaults.

This is only a reusable accounting primitive. It is not yet wired into
`PeerConnection`, `PeerManager`, socket reads, outbound writes, application
handler ownership, or shutdown. It is not thread-safe, cross-process, or a
production resource policy. The tests cover basic atomic reservation and
release behavior, not async cancellation at transport await boundaries or
measured memory ceilings. Do not treat this increment as closing any P2P or
Mainnet launch gate.
