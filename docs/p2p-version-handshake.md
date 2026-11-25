# P2P version handshake payload prototype

`src/blackroot_p2p_handshake.py` provides a strict codec for a proposed
version payload. It carries a positive protocol version, service bitfield,
signed timestamp, nonce, starting height, and a UTF-8 user-agent string.

The user-agent is length-prefixed with a little-endian uint16 and limited to
256 encoded bytes. Decoding rejects truncated payloads, trailing bytes,
oversized user agents, invalid UTF-8, and invalid numeric fields. The codec
does not itself send messages or perform a peer handshake.

## Important limitations

- No socket transport, peer discovery, peer authentication, or encryption.
- A nonce is data for a future self-connection check, not identity proof.
- Service flags and protocol version negotiation are not yet normative.
- No time-drift policy, peer scoring, address relay, or Sybil resistance.
- The existing message framing layer must wrap this payload.
- This is experimental and must not be treated as a production network protocol.
