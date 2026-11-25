# P2P message framing prototype

`src/blackroot_p2p.py` implements a bounded message envelope parser only:

- Four-byte network magic identifies the intended protocol network.
- Twelve-byte command field accepts 1-12 lowercase ASCII letters, digits, or underscores, followed only by zero padding.
- Four-byte little-endian payload length is checked against a configured maximum before waiting for the body.
- Four-byte checksum is the first four bytes of SHA256d(payload).
- Exact-frame decoding rejects truncation, trailing bytes, invalid command padding, wrong network magic, oversized payloads, and checksum mismatch.
- The incremental parser supports fragmented and concatenated messages while bounding its incomplete-frame buffer to one maximum-sized frame.

The default maximum payload is 2,000,000 bytes. A caller should use a much smaller limit for message types with smaller known payloads and apply per-command limits before decoding expensive structures.

This is not a P2P network implementation. There are no sockets, peer discovery, handshake state machine, peer authentication, request scheduling, timeouts, rate limits, bans, encryption, or message-specific consensus validation. The checksum detects accidental corruption; it is not authentication and does not prevent malicious peers. Do not expose this prototype to the public internet or treat it as mainnet-ready.
