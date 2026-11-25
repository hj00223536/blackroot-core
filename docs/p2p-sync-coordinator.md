# P2P sync coordinator

`PeerSyncCoordinator` binds the existing header synchronization and block-body
request tracker into a per-peer message dispatcher.

## Supported messages

- `inv`: decodes bounded inventory. Unknown block hashes trigger one
  `getheaders` request while a header request is pending. Known best-chain
  block hashes trigger bounded `getdata` requests.
- `headers` / `getheaders`: delegated to `PeerHeaderSync`.
- `getdata`: serves block bodies through an explicitly supplied
  `block_provider(hash) -> bytes | None`; unavailable items receive `notfound`.
- `block`: decoded and accepted only when its header hash has an outstanding
  request and matches the currently selected best-chain header. The attached
  UTXO store performs full block/transaction validation before connection.
- `notfound`: cancels matching outstanding block requests.

Transaction inventory is parsed but not requested or relayed because a mempool
and transaction relay policy do not yet exist. Unknown inventory does not
cause automatic dialing. Callers must bind the callback to a handshaken
`PeerConnection`, attach the correct UTXO store, and manage peer lifecycle.

## Limitations

This is a prototype coordinator, not a complete synchronization service.
Request expiry/retry scheduling, peer scoring, multi-peer source selection,
mempool relay, compact blocks, reorg-aware request cancellation, persistent
network parameters, and production anti-DoS policy remain future work.


## Multi-peer block request assignment

`MultiPeerBlockRequestPool` provides a bounded assignment layer for callers
that manage several already-connected peers. The caller supplies eligible peer
IDs for each block hash; the pool selects a least-loaded peer with rotating
tie-breaking, enforces global and per-peer limits, and records exactly one
source for each request. A response can complete an assignment only when it
comes from the assigned peer. Disconnect cleanup releases every assignment
owned by that peer so another eligible source can be selected.

This scheduler is a separate coordination primitive; it is not yet wired into
`PeerSyncCoordinator` or `PeerManager`. Received payloads still require
independent header, block, and UTXO validation. It does not establish peer
honesty, network diversity, or Sybil resistance.


## Integrated multi-peer block downloads

`MultiPeerBlockScheduler` connects peer selection to actual `getdata`
dispatch. It filters to connected peers, assigns each block to one least-loaded
source, records the request in the shared best-chain body tracker, and sends
the request to that peer. If sending fails, both assignment and tracker state
are rolled back. Incoming bodies are accepted only from the assigned peer and
still pass the existing block/header/UTXO validation path. Disconnect cleanup
releases the source's assignments and tracker entries for later reassignment.

The scheduler is an opt-in node-level component. The application must supply
the current connected-peer mapping and invoke `peer_disconnected` from its
peer lifecycle callback. It does not automatically discover peers, retry on a
timer, or provide Sybil resistance.


## Three-node loopback verification

`tests/test_p2p_three_node_integration.py` starts three real asyncio TCP
nodes on loopback: one requesting node and two serving peers. It completes
the version/verack handshake with both peers, routes a block-body request to
the scheduler-selected source, receives the body over that TCP connection,
and verifies that the other peer received no request. The receiving node then
passes the body through the scheduler's assigned-source check and the existing
block-body validation/UTXO connector boundary.

This is a local integration test using a test genesis and a mocked persistent
store connector. It is not evidence of public internet interoperability,
production consensus readiness, or a live mainnet.


## Higher-work branch and UTXO reorganization tests

`tests/test_utxo_reorganization_integration.py` builds a validated header DAG
with an active one-block branch and a competing two-block branch. It checks
that the UTXO database switches to the strictly higher-work branch, that a
missing replacement body leaves the active database unchanged, and that
repeating a completed switch is idempotent. These are local storage/consensus
integration tests; they do not yet prove automatic fork-body acquisition and
reorganization orchestration across remote peers.


## Multi-peer best-fork body acquisition and activation

`MultiPeerReorganizationSync` operates after candidate headers have already
been accepted into the `HeaderChain`. It compares the active UTXO tip with
the DAG's best-work tip, derives the fork's connecting headers, and requests
every missing body from connected peers using the bounded assignment pool.
A response is accepted only from its assigned peer, and its serialized header
and Merkle commitment must match the validated DAG entry. Accepted bodies are
archived by hash. Once all bodies required for the best branch are present and
there are no outstanding assignments, the coordinator invokes
`UTXOStore.reorganize_to_best`, which performs the database switch atomically.

The integration tests cover two-peer body distribution, completion-triggered
reorganization, rejection of an unassigned source, and release on disconnect.
This remains an opt-in orchestration component: header discovery, automatic
peer lifecycle wiring, timeout/retry policy, peer scoring, and production
consensus hardening remain outstanding.


### Timeout and retry policy

The reorganization downloader now records monotonic request timestamps.
`expire_requests(timeout)` releases assignments that exceed the caller's
timeout, and `retry_expired_requests(peers, timeout)` reassigns those bodies
to currently connected peers and sends fresh `getdata` messages. The caller
must invoke this method from its own timer/event loop; this library component
does not create background tasks. Disconnected-peer cleanup also clears the
corresponding timestamps. Tests cover timeout validation and reassignment when
the original source is no longer connected.


### `notfound` and released-request reassignment

The fork-body downloader now accepts a `notfound` inventory payload together
with its source peer ID. It releases only hashes currently assigned to that
same peer; unrelated or spoofed `notfound` messages do not cancel another
peer's request. The caller can pass the released hashes to
`retry_released_bodies(hashes, peers)`, which assigns them to connected peers
and sends new `getdata` requests. The peer lifecycle owner must call
`peer_disconnected(peer_id)` on disconnect and schedule retries for the
returned hashes. This keeps network scheduling explicit and avoids hidden
background tasks.


### Peer-manager disconnect hook

`PeerManager` now accepts an optional `on_peer_disconnected(peer)` callback.
It is invoked after the connection is closed and removed from the manager's
active peer set; asynchronous callbacks are awaited. A node-level owner can
use this hook to remove the peer from its registry and call both the ordinary
block scheduler's and fork downloader's disconnect cleanup methods. The hook
does not itself select replacement peers or run a retry loop.


## Node-level P2P service wiring

`P2PSyncService` is the opt-in adapter between an existing `PeerManager`,
the validated `HeaderChain`, and `MultiPeerReorganizationSync`. It installs
the manager's per-peer message factory and disconnect callback, maintains a
header-sync coordinator per connection, routes `headers`/`getheaders`,
`block`, and `notfound` messages, and uses the actual connection object as
the request-pool peer identity. A validated header batch triggers requests for
missing bodies on the current best-work fork. A matching block response is
passed to the reorganization downloader; a peer's `notfound` response or
disconnect releases only that peer's assignments and attempts reassignment to
remaining connected peers.

The application starts header synchronization with `start_peer_sync()` and
must call `retry_expired()` from its own timer/event loop. The service does
not create hidden background timers, discover public peers, or enable the
service automatically for every node. Header discovery, body transfer, and
reorganization still depend on the caller constructing a correctly configured
`PeerManager`, persistent chain, and UTXO store.


The node-level service also routes ordinary best-chain `inv` announcements
through `MultiPeerBlockScheduler`: known selected-chain block hashes are
requested from one assigned connected peer, and unsolicited or wrong-source
block bodies are rejected. A matching `notfound` or peer disconnect releases
both the best-chain and fork-body assignments and retries against remaining
peers. For a `notfound` response, the source peer is excluded from the
immediate retry so it is not selected again for the same unavailable body.



## Ordinary best-chain node dispatcher

`NodePeerSyncService` in `src/blackroot_p2p_node_service.py` is a separate,
opt-in adapter for ordinary selected-best-chain block downloads. The embedding
application registers each handshaken peer, installs
`on_peer_message_factory(peer_id)` as the manager's message factory, and
passes `peer_disconnected` as the manager disconnect callback. Known selected
best-chain block announcements in `inv` are routed through one shared
`MultiPeerBlockScheduler`; matching `block` responses are accepted only from
the assigned peer. A matching `notfound` or disconnect releases the request
and immediately attempts reassignment to another connected peer. Timed-out
requests can be retried by explicitly calling `retry_expired(timeout)` from
the application's event loop.

This adapter does not discover unknown headers, serve `getdata`, relay
transactions, or orchestrate higher-work fork bodies. Those remain separate
components and must be wired by the application. Tests in
`tests/test_p2p_node_service.py` cover inventory routing, assigned-source
acceptance, `notfound` reassignment, disconnect reassignment, and rejection of
an unassigned `notfound`. This is not a public-network or mainnet readiness
claim.

### Real TCP service-level reorganization and disconnect recovery

`tests/test_p2p_service_reorg_loopback.py` exercises `P2PSyncService`
with two real loopback TCP serving peers and a requesting node. The test
constructs a higher-work two-block fork, asks the service to fetch its bodies,
and verifies that the UTXO tip changes only after the required bodies arrive
and validate. A second test closes the peer that owns one of the outstanding
requests; the manager's disconnect hook releases that peer's assignments,
reassigns the missing fork bodies to the surviving connected peer, and allows
the reorganization to complete.

These tests validate local callback wiring, source ownership, request release,
reassignment, and the reorganization path over TCP. They do not test public
internet peers, malicious network behavior, power-loss atomicity across the
separate header and UTXO databases, or production consensus interoperability.

## Persistent node runtime wrapper

`BlackrootNodeRuntime` in `src/blackroot_node_runtime.py` is the explicit
application lifecycle boundary for the current prototype. It accepts an
already initialized `PersistentNodeState` and configured `PeerManager`,
constructs `P2PSyncService` against the replay-verified header DAG and
persistent UTXO store, and exposes listener startup, outbound peer connection,
header synchronization, timeout retry, and idempotent shutdown. The runtime
does not select genesis/network parameters, create hidden background timers,
or automatically connect to public peers. The embedding application remains
responsible for supervised retry scheduling and for reopening the persistent
state on the next process start.

`tests/test_node_runtime.py` verifies callback wiring, loopback listener
startup, the empty-peer synchronization path, and closed-runtime behavior.
This is lifecycle composition coverage only. Header and UTXO data remain in
separate SQLite databases; there is no cross-database atomic commit or complete
crash-recovery protocol. The runtime is not a production node or a public
mainnet release.

### Runtime restart persistence test

`tests/test_node_runtime.py` now closes a running runtime after connecting
the genesis block, reopens the same header and UTXO SQLite paths through a new
`PersistentNodeState`, and starts a fresh runtime/listener. It asserts that
the replayed genesis header and active UTXO tip match the pre-shutdown state.
This is a clean shutdown/reopen test, not a simulated power loss: SQLite
cross-database atomicity, interrupted writes, fsync guarantees, and automatic
recovery of a header-ahead-of-UTXO crash window remain unresolved.

### Header-ahead-of-UTXO crash-window recovery test

`tests/test_persistent_node_state.py` now simulates the recoverable crash
window where a validated header is committed to the header database but its
body has not yet been connected to the UTXO database. Reopening the state must
preserve the older UTXO tip while replaying the newer best header. The test
then explicitly archives the matching body and completes the normal validated
reorganization. This demonstrates recovery of that specific staged state; it
does not provide atomic commits across the two databases or simulate storage
hardware failure.

### Write-ahead recovery intent journal

`src/blackroot_recovery_journal.py` adds a third SQLite database containing
at most one pending active-tip transition. Before a best-block connection or
best-chain reorganization, `PersistentNodeState` records the old and expected
new UTXO tips. The journal uses SQLite WAL mode and requests
`synchronous=FULL`. After the UTXO transaction, the observed tip is reconciled
against the intent and the intent is cleared.

On startup, after validating the active UTXO records against the replayed
header DAG, the node resolves any pending intent:
- observed tip equals the new endpoint: the UTXO transaction committed;
- observed tip equals the old endpoint: the UTXO transaction did not commit;
- any other tip: startup fails closed.

Tests cover both recoverable crash windows and an unexpected third tip.
This is a write-ahead reconciliation protocol across separate SQLite files,
not a truly atomic multi-database transaction. Its durability still depends
on SQLite, filesystem, and storage-device guarantees; it is not production
crash-safety certification.


### Subprocess crash-checkpoint tests

`tests/test_recovery_journal_process_crash.py` starts a separate Python
process against temporary header, UTXO, and recovery-journal databases. The
child exits immediately after (1) persisting the recovery intent but before
the UTXO transition, and (2) committing the UTXO transition but before
reconciling the journal. The parent process reopens the node state and checks
that the old or new endpoint is recognized and the pending intent is cleared.

These deterministic subprocess termination checkpoints exercise recovery
across process death. They are not a physical power-loss test, do not kill a
process during arbitrary SQLite or filesystem instructions, and do not certify
fsync behavior or storage-device durability. The three databases remain
separate; true cross-database atomicity is not implemented.

### Startup UTXO integrity checks

`UTXOStore.verify_integrity()` runs during `PersistentNodeState` startup before the active tip is reconciled with the recovery journal. It checks SQLite's page-level integrity report, foreign-key constraints, contiguous active block heights and parent links, per-block transaction counts and positions, canonical transaction decoding and txid matches, and every archived block body's serialized size, header hash, and Merkle commitment. Startup fails closed when any of these checks detects corruption.

These checks cover the UTXO database's SQLite and stored-record consistency. They do not independently reconstruct the complete UTXO set by replaying every historical block, prove that the header database and UTXO database were committed atomically, or replace independent consensus and cryptographic review. Header-DAG replay remains the separate header-store validation path.
