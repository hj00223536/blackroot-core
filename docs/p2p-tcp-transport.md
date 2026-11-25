# Asyncio TCP peer transport

`PeerConnection` owns one asyncio TCP stream. It sends the local `version`
message, validates the remote version, exchanges `verack`, and only then
allows application messages. It responds to eight-byte `ping` payloads with
matching `pong` payloads. Framing, network magic, checksums, payload limits,
handshake deadlines, and idle deadlines are enforced.

A caller may supply `on_message(command, payload)` to route authenticated-
by-handshake (not cryptographically authenticated) application messages to
existing codecs such as the headers and block-body handlers.

## Scope and security limits

- `connect_peer` opens one outbound TCP connection; no listener, peer
  discovery, DNS seed, address book, inbound admission, or multi-peer manager
  is included.
- Version/verack is protocol sequencing, not peer identity authentication.
  There is no encryption, Sybil resistance, eclipse protection, peer scoring,
  or persistent ban list.
- Application handlers must still validate headers, blocks, and transactions.
  A completed handshake does not make peer data trustworthy.
- The default idle timeout is 120 seconds and handshake timeout is 10 seconds.
  Operators should configure limits appropriate to the eventual network.
- Network magic, protocol version, genesis, address format, and consensus
  parameters remain provisional. Do not expose this prototype to untrusted
  public peers or use it to protect funds.
