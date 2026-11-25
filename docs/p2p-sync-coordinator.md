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
