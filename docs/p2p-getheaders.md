# getheaders locator codec

The `getheaders` payload codec now represents the protocol version, an ordered
vector of block locator hashes, and a 32-byte stop hash. The locator is capped
at 101 hashes; CompactSize encoding must be canonical, and truncation or
trailing bytes are rejected. An empty locator is permitted at the codec layer
but higher-level request policy must decide whether it is meaningful.

## Integration boundary

This codec does not construct locators from the local chain, send requests,
choose a peer, or accept returned headers. A future sync coordinator must
build locators from the validated best chain, enforce per-peer request
deadlines and response bounds, and pass received headers through the existing
atomic consensus-checked header acceptance path.
