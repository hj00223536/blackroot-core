# Inventory message codec

The P2P prototype now supports bounded inventory vectors for `inv`,
`getdata`, and `notfound` payloads. Each vector contains a little-endian
uint32 type and a 32-byte hash. This implementation currently recognizes only
transaction (1) and block (2) inventory types, caps each payload at 50,000
vectors, requires canonical CompactSize counts, and rejects truncation,
trailing bytes, and unknown types.

## Integration boundary

This is a wire codec only. It does not request data, relay transactions,
serve blocks, or establish whether an object is valid. A dispatcher must
apply per-peer request limits, outstanding-request tracking, timeouts,
duplicate suppression, and consensus validation before storing or relaying
received objects. Witness and other extended inventory types are not yet
supported.
