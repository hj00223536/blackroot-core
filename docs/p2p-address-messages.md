# Peer address message codec

The prototype now includes bounded codecs for `addr` and `getaddr`.

Each `addr` entry encodes a uint32 timestamp, uint64 services bitfield,
16-byte IP address, and big-endian uint16 port. IPv4 uses the standard
IPv4-mapped IPv6 wire representation; decoding normalizes mapped addresses
back to IPv4. CompactSize counts must be canonical, the payload is limited to
1,000 entries, and truncation/trailing bytes are rejected. `getaddr` has an
empty payload.

## Security boundary

The codec only parses endpoint data. It does not validate routability,
freshness, reachability, network membership, or peer identity. Do not dial or
relay decoded addresses automatically. A future address manager must filter
private, loopback, link-local, multicast, documentation, unspecified, and
otherwise disallowed ranges according to an explicit network policy, apply
age and source limits, rate-limit requests, and defend against address
poisoning. Public discovery and seed nodes are intentionally not enabled.
