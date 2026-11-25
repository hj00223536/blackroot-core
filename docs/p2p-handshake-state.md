# Peer handshake state machine prototype

`src/blackroot_p2p_state.py` tracks the local/remote version and verack
exchange independently of a transport. A handshake is complete only after:

1. The local version payload has been sent.
2. A valid remote version payload has been received.
3. The local verack has been sent.
4. An empty remote verack has been received.

It rejects duplicate version/verack messages, verack-before-version ordering,
non-empty verack payloads, and a remote nonce equal to the local nonce
(self-connection guard).

This nonce check only detects a basic self-connection case; it is not peer
authentication. The state machine does not open sockets, enforce timeouts,
negotiate protocol versions, authenticate identities, protect against Sybil
attacks, or validate chain data. A production transport must also handle
disconnects, partial writes, deadlines, and resource limits.
