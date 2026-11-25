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
