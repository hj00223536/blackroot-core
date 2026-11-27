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

## 13. Outbound transport integration status

PeerConnection now accepts an explicit pair of send budgets (peer_budget, node_budget). When supplied, send() reserves one pending-writer item and the exact frame byte count (24-byte envelope plus payload) against both budgets before calling the frame encoder. The reservation is retained while waiting for the send lock and through writer.drain(). Reservation exhaustion rejects before encoding. Encoding errors release the reservation. If a write has been handed to the stream and drain is cancelled or fails, the peer is closed before the reservation is released, because delivery and buffered ownership are otherwise ambiguous.

Focused tests cover blocked drains, per-peer capacity, a shared node budget across two peers, cancellation, and encoding failure. This remains opt-in: PeerManager does not yet construct or inject a shared reviewed budget, and receive-side reservations, handler ownership, bounded shutdown, measured transport memory, and public listener policy remain unimplemented. The legacy path without send_resource_budgets is still unaccounted. No production numeric limits have been selected; this does not close the P2P resource gate.

## 14. Inbound receive reservations and manager wiring

PeerConnection now optionally accepts a distinct (peer, node) receive-budget pair. After validating the fixed 24-byte message header and applying the existing per-peer rate checks, it reserves both budgets before reading the declared payload body. The reservation conservatively charges 24 + 3 × payload_length bytes to account for the header, input payload, combined decode frame, and decoded payload copy during peak decoding. The reservation remains owned until handle_message completes, including awaited application callbacks; read/decode failure and cancellation release it.

PeerManager can now inject a caller-owned shared node budget plus a caller-supplied factory that creates a fresh per-peer budget for each direction (send and receive). It rejects incomplete pairs and validates each factory result. No numeric limits are selected by the manager. This is still opt-in: callers can omit all budgets, the manager does not enforce a production policy profile, and the legacy unbudgeted path remains available. Handler-created copies beyond the transport decode copy are not measured or charged. The design still needs explicit ownership transfer for queued/retained application data, bounded callback task counts, listener policy, load testing, and independent review.

Focused tests cover rejection before body consumption, capacity held through an async handler, cancellation during payload read, and manager injection of shared node/per-peer budgets. These tests do not constitute adversarial load or production memory-ceiling evidence.

## 15. Receive reservation close/dispatch ownership

The transport now distinguishes a decoded inbound message waiting to enter its handler from a message actively owned by its handler. Closing a peer releases a pending reservation if dispatch has not started. Once dispatch begins, close does not release the reservation; the handler's finally block remains the owner and releases it on completion, failure, or cancellation. A guard rejects concurrent handler dispatch on one peer. Focused tests cover close-before-dispatch release and verify that close during an active asynchronous handler does not prematurely free its budget.

This closes one reservation-lifecycle gap only. It does not account application-created copies retained after callback return, callback-created background tasks, or external queues. Those require an explicit ownership-transfer API and bounded queue/task policy; arbitrary Python references cannot be measured reliably by this transport layer.

## 16. Explicit inbound ownership transfer API

`PeerConnection.take_receive_reservation()` is available only while an application message handler is actively dispatching. It removes the reservation from transport ownership and returns the `ResourceReservation` to the handler, which may pass it alongside the payload to a bounded downstream queue/consumer. The consumer must release it exactly once, normally in `try/finally`, after its last use of the retained payload. If the handler does not transfer ownership, the transport releases the reservation when dispatch finishes. If the handler transfers ownership and then fails, cancellation or exception does not silently reclaim the transferred reservation: the new owner is responsible for cleanup. This makes ownership explicit rather than guessing when application references disappear.

The API does not itself create a bounded queue, count arbitrary callback-created tasks, or prevent a handler from retaining an uncharged copy. Callers must use bounded queues and transfer the reservation atomically with the retained payload; an unbounded queue or a consumer that forgets release can still exhaust capacity. The new test demonstrates that a transferred reservation remains charged after handler return and is released by the consumer. This remains opt-in and is not a production P2P policy.

## 17. Bounded application queue prototype

`src/blackroot_p2p_queue.py` adds an opt-in single-consumer FIFO with a required positive `max_items` capacity. It accepts only bytes payloads and a live `ResourceReservation`; ownership transfers only when `put_nowait` succeeds. If admission fails because the queue is full or closed, the caller retains the reservation and must release it or retry. The queue never creates worker tasks.

The consumer receives a `ReservedMessage`. `task_done()` acknowledges the in-flight message and releases its reservation if the consumer has not already released it; a second `get()` is rejected until acknowledgement. A context manager is also available for deterministic release. `close()` stops admission, releases all still-queued messages, and wakes the one waiting consumer; a message already handed to the consumer remains charged until that consumer acknowledges it. The queue is intentionally single-consumer and does not define a production worker lifecycle, retry policy, or multi-queue scheduling.

Focused tests cover capacity rejection without stealing ownership, queued/in-flight close behavior, consumer ordering, acknowledgement-driven release, and wakeup. This is an application-layer building block, not an end-to-end bounded task system. The caller must supervise exactly one worker, acknowledge in `finally`, and use the transferred reservation with the payload. No numeric production limits are selected and the P2P/Mainnet gates remain open.

## 18. Queue consumer cancellation handling

The bounded queue now provides `async with queue.consume() as message:`. Its context manager acknowledges the in-flight message in `finally`, releasing the reservation even if the worker is cancelled or raises while processing. A task cancelled while blocked waiting for the next message releases the single-consumer slot so a replacement worker can be started. The consumer remains single-task/single-inflight; the runtime must supervise worker replacement and must not spawn unbounded replacements. Tests cover cancellation during message processing and while waiting.

## 19. Optional PeerManager queue integration

`PeerManager` now accepts an explicit `application_queue_factory(peer)` when receive peer/node budgets are also configured. It creates one `ReservedMessageQueue` per managed peer and installs a dispatch callback that transfers the current `PeerConnection` receive reservation into that queue. The queue can be retrieved with `application_queue_for(peer)`. Existing message callbacks and this queue mode are mutually exclusive to avoid ambiguous ownership.

If queue admission fails (including a full or closed queue), the callback releases the just-transferred reservation and propagates the failure; the peer session then follows the manager's normal failure/close path. On peer teardown the manager closes that peer's queue, releasing messages still queued. A message already handed to the application consumer remains the consumer's responsibility and is released by `async with queue.consume()` or explicit acknowledgement.

The manager does not start application workers. The embedding runtime must start and supervise one bounded worker per queue (or a separately reviewed bounded worker pool), retain task handles, stop workers on shutdown, and avoid unbounded task creation. Queue item caps and receive byte budgets are explicit caller inputs; there is still no measured production resource profile.

## 20. Retained application worker prototype

`PeerManager.start_application_worker(peer, handler)` now starts and retains one consumer task for a managed peer's configured application queue. It invokes sync or async handlers sequentially, so a single peer cannot create an unbounded callback-task fan-out through this API. The task is tracked by the manager; handler failure is recorded, closes the queue, and closes the peer. The queue's consume context releases the in-flight reservation on success, exception, or cancellation.

Manager shutdown closes peer queues through peer teardown, then cancels and awaits any remaining application worker tasks. This gives a deterministic cancellation boundary for queue-owned payloads, but it does not make arbitrary handler side effects transactional or safe to interrupt. Applications must make handlers cancellation-aware and idempotent where required. Worker restart is intentionally not automatic; a failed worker/peer requires normal peer reconnection and explicit new worker creation. The API does not define a global worker concurrency cap beyond the configured peer admission limit, nor does it supply production queue capacities or byte budgets.

Manager shutdown now closes all application queues before closing peer streams, preventing new queue admission and releasing queued-but-not-yet-consumed payload reservations at the start of teardown. It then closes peers, waits for peer tasks, cancels and awaits remaining worker tasks; the queue context releases any in-flight message on worker cancellation. A focused test exercises shutdown while a handler is blocked and confirms the reservation returns to zero. This still does not make external handler side effects reversible.

## 21. Worker teardown on peer disconnect

A peer session now closes its application queue and cancels/awaits its retained worker before completing peer teardown. This matters when a handler is blocked indefinitely: merely closing the queue would release queued messages but leave the in-flight handler and its reservation alive. The worker's `queue.consume()` `finally` now provides the reservation release path on this disconnect-triggered cancellation. The manager also removes the per-peer worker-start marker on disconnect so churn does not accumulate stale peer references. Tests cover a blocked handler, disconnect, cancellation, reservation release, and admission-state cleanup.

Cancellation still cannot reverse external side effects already performed by a handler. Handlers must be cancellation-aware and idempotent as appropriate. This remains a bounded per-peer worker prototype, not a complete node-wide scheduling/resource policy.

## 22. Concurrent manager shutdown callers

`PeerManager.close()` creates one retained shutdown task and makes every caller
await that same task. Awaiters use `asyncio.shield()`: cancelling an individual
caller therefore does not cancel teardown, close sockets early, or mark the
manager complete while peer sessions and workers remain active. The completion
event is set by the retained shutdown task in `finally`, including when
shutdown raises. Tests block peer close, verify concurrent callers wait, then
cancel the first caller and verify a later caller still waits for the original
shutdown to finish. This is event-loop-local synchronization; it is not a
cross-thread lifecycle primitive. If the shutdown operation itself fails, all
callers awaiting it observe that failure; the manager does not silently retry
partially completed teardown.

## 23. Per-peer queue identity

The manager now requires `application_queue_factory` to return a pristine, unused queue for each peer. It rejects a queue that is already assigned to another managed peer, has been closed, contains queued messages, or has already established a consumer/in-flight message. This prevents two peer dispatch paths from accidentally sharing a single-consumer queue and prevents reassigning a previously closed queue. A focused test verifies that a factory returning one shared queue is rejected on the second peer. This identity check is local to the manager instance and does not replace global resource accounting.


## 24. Peer setup failure cleanup

Peer construction now treats application callback/queue setup as a failure-atomic
step. If a queue factory returns an invalid, reused, or non-pristine queue, or
a per-peer message-handler factory fails or returns a non-callable value, the
manager removes and closes any queue it had registered and closes the newly
accepted socket before propagating the setup error. Focused tests verify socket
closure and queue-map cleanup. This is local setup cleanup only; it does not
establish an inbound admission quota, global descriptor budget, or production
P2P resource policy.


## 25. Complete peer setup ownership and inbound callback containment

The setup failure boundary now begins before per-peer resource-budget factory calls and includes both budget factories, PeerConnection construction, and application callback/queue installation. Any exception during these stages closes the accepted socket and removes/closes a partially registered queue. The inbound asyncio accept callback catches ordinary setup/registration exceptions, records them in the manager's bounded background-error history, and closes the socket rather than allowing an unhandled synchronous callback exception to escape. Regression tests cover a raising budget factory, an invalid budget-factory result, and inbound setup failure recording.

This remains lifecycle hardening, not a node-wide resource policy. It does not select numeric caps, bound kernel accept backlog or connection rate, provide global descriptor/memory/work ceilings, or authorize public listener exposure.


Peer task registration is now failure-atomic as well: if asyncio task creation fails after a peer is constructed, the manager closes the coroutine object, removes the peer from its managed set, and closes the peer's socket before propagating the exception. A regression injects task-creation failure and checks that no managed peer/task remains and the socket is closed. This guards a local scheduler/setup failure; it does not establish process-wide task limits or production admission policy.


## 26. Listener startup versus shutdown

Listener startup is now single-flight within the event loop: a second concurrent start request is rejected while the first bind is pending. If manager shutdown begins while `asyncio.start_server` is awaiting, the eventual listener is closed and awaited rather than being installed after shutdown has already completed. This prevents a late-started inbound listener from surviving a completed manager close. Regression tests exercise both close-during-startup and concurrent-start attempts using a controlled delayed server factory.

This does not set a production bind address, backlog, connection-rate limit, or public exposure policy. Public listening remains disabled pending a reviewed deployment profile and measured node-wide resource policy.


Shutdown now also waits for the in-flight listener-start completion event. This matters because merely closing a listener that was already installed is insufficient: an `asyncio.start_server` call can still be pending when close begins. The close operation therefore does not report completion until the pending bind has either failed or returned a server that the startup path closes after observing the manager's closing state. The regression asserts close remains pending until that bind is released and its late server is closed.


## 27. Application worker task-creation rollback

`start_application_worker` now treats task creation as part of worker admission. If `asyncio.create_task` fails, it explicitly closes the unsubmitted coroutine and removes the peer's worker-start marker before propagating the error. A regression injects task-creation failure and verifies the marker and worker-task registry remain empty. This prevents a peer from being permanently marked as having a worker when no worker exists. It does not add a global worker/task ceiling or change the opt-in queue policy.


## 28. Outbound dial shutdown ownership

PeerManager now retains each in-flight outbound connection-attempt task. Shutdown cancels and joins those dial tasks, then waits for the connect-attempt reservation counter to return to zero before completing teardown. Each connect path removes its retained dial task and releases its admission reservation in `finally`, including cancellation and connection errors. This prevents a manager from reporting shutdown complete while an outbound dial remains pending. A controlled regression blocks `asyncio.open_connection`, starts shutdown, and verifies the dial is cancelled, joined, and its reservation is released.

This is lifecycle cancellation, not an outbound connection-rate policy or a measured descriptor/task ceiling. Connect timeouts and peer-count admission remain implementation behavior, not a reviewed public deployment profile.


## 29. Outbound dial task-creation failure

The retained outbound-dial lifecycle now has a focused failure-injection regression for failure of `asyncio.create_task` itself. The connect path closes the unsubmitted `wait_for(open_connection(...))` coroutine, removes no unregistered task, decrements its outbound admission reservation in `finally`, and signals the no-outstanding-connect event when the count returns to zero. The test verifies the coroutine is closed and manager bookkeeping is empty. This is failure containment, not a production outbound rate or global task budget.


## 30. Outbound dial caller-cancellation regression

A second regression cancels the coroutine awaiting `PeerManager.connect()` while its retained dial is blocked. Cancellation propagates to the dial task; the dial task is removed from the manager registry, the outbound reservation returns to zero, and the shutdown-drain event is signalled. Together with the manager-shutdown cancellation and task-creation-failure tests, this covers the three local dial lifecycle exits: explicit caller cancellation, manager shutdown, and task-creation failure. These tests do not bound connection churn or prove behavior under OS-level socket exhaustion; those remain measured stress and deployment-policy work.
