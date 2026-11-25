# P2P block-body request tracking

`BlockBodyRequestTracker` is the bounded state boundary between a future P2P
transport and the experimental block/UTXO validation path.

## Flow

1. A transport first accepts headers through `accept_headers_payload`.
2. It calls `request(block_hash, header_chain)` only for a header on the
   currently selected best-work chain. The tracker caps outstanding requests
   (128 by default) and rejects duplicate or unknown requests.
3. On receipt, the transport passes the requested hash and raw block payload
   to `accept_payload`.
4. The tracker enforces the provisional block-size ceiling, parses the complete
   block, checks its header hash and exact serialized header against the
   validated DAG entry, and calls `UTXOStore.connect_validated_block`.
5. The request is cleared only after the store successfully validates and
   atomically connects the block. Failures leave the request pending for retry
   or explicit cancellation.

Unsolicited bodies, bodies for a different hash, malformed payloads, and
headers that are no longer on the selected best chain are rejected before
persistent state is touched.

## Deliberate limitations

This is not network transport: it does not send `getdata`, open sockets,
authenticate peers, apply timeouts, or manage peer penalties. A transport must
implement those responsibilities and must call this tracker only after its
own framing/checksum layer succeeds.

The block format and 1 MB size ceiling are provisional. The current consensus
and script implementation is incomplete and is not safe for production funds.
The selected HeaderChain must be initialized from independently agreed genesis
and network parameters. A successful local connection does not establish that
the network is live or decentralized.
