# Peer manager and inbound TCP listener

`PeerManager` owns a bounded set of `PeerConnection` sessions. It can start
an asyncio TCP listener for inbound peers and open outbound connections.
Each session receives a fresh local handshake nonce, runs the existing
version/verack protocol, enforces message bounds and timeouts, and is removed
when it closes. The manager enforces a configurable total peer cap (16 by
default), including concurrent outbound connection reservations.

## Inbound rate limits

Each `PeerConnection` owns independent monotonic-clock token buckets:
control-message count, data-message count, and data payload bytes. Defaults
are 20 control messages/second with a burst of 40, 20 data messages/second
with a burst of 40, and 2 MiB/second with a burst of 4 MiB. All six values
are configurable on `PeerConnection`, `connect_peer`, and `PeerManager`.
The manager passes the policy to inbound and outbound sessions; each session
still has its own independent buckets.

The inbound receive path charges the budget after validating the fixed header
and command-specific payload ceiling, but before reading the payload body.
A rejected frame closes the session through the existing protocol-error path.
These defaults are provisional, not benchmarked production policy. They
require multi-peer synchronization and load testing before public deployment.
They apply to inbound traffic accepted by a peer session; they are not an
outbound bandwidth shaper.

## Example lifecycle

A caller creates a manager with the provisional network magic and local
version, awaits `start_server(host, port)` to listen, and/or awaits
`connect(host, port)` to initiate an outbound session. The manager retains
session tasks. Application messages are forwarded to the configured
`on_message` handler. `close()` stops the listener and closes sessions.

## Limitations

This is a minimal TCP session manager, not a public peer network. It has no
peer discovery, DNS seeds, address book, encryption, peer authentication,
Sybil/eclipsing defenses, persistent bans, peer scoring, or connection
diversity policy. The peer cap is per manager process. Inbound sockets are
not exposed to untrusted public networks until protocol parameters and
security policy have undergone independent review. Consensus, genesis,
transaction script, and wallet work remain incomplete.

## Peer task failure isolation

The manager supervises each peer task independently. Unexpected exceptions
from a peer session are retained in a bounded in-memory diagnostic history
(`background_errors`, newest 100 retained) and passed to the configured
`on_peer_error` callback. Failures in the error callback, peer close path,
or disconnect callback are also retained and do not prevent removal of the
peer from the manager's active set. Cancellation still propagates after the
cleanup path runs.

This is process-local diagnostic evidence, not durable logging or a peer
reputation/ban system. Operators must export diagnostics through their own
logging/monitoring integration before production use.
