# Peer header synchronization coordinator

`PeerHeaderSync` composes the getheaders locator codec, headers codec, and
existing atomic consensus-checked header acceptance path for one established
peer. It builds an exponentially stepped locator ending at genesis, sends
`getheaders`, serves bounded `headers` responses after the first locator
hash found on the selected best chain, and validates received `headers`
batches through `accept_headers_payload`. A full 2,000-header batch triggers
another locator request.

## Security and implementation boundary

The coordinator requires a completed transport handshake but does not treat
that handshake as peer identity or trust. It has no per-peer rate limits,
request timeout state, peer scoring, block-body fetching, inventory dispatch,
or transaction relay. HeaderChain consensus rules remain experimental and
must receive independent consensus review before any public network launch.
