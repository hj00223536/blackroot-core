# Peer manager and inbound TCP listener

`PeerManager` owns a bounded set of `PeerConnection` sessions. It can start
an asyncio TCP listener for inbound peers and open outbound connections.
Each session receives a fresh local handshake nonce, runs the existing
version/verack protocol, enforces message bounds and timeouts, and is removed
when it closes. The manager enforces a configurable total peer cap (16 by
default), including concurrent outbound connection reservations.

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
