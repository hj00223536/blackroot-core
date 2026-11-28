# BLACKROOT network identity proposal (not activated)

Status: proposal for review only. These values are NOT consensus constants and must not be used to receive funds.

## Proposed identity

| Parameter | Proposed value | Status |
|---|---|---|
| Network name | BLACKROOT | Project name |
| Currency ticker | BRT | Proposed |
| P2PKH address format | Base58Check, 1-byte version + 20-byte HASH160 + 4-byte double-SHA256 checksum | Proposal |
| P2PKH version byte | 0x26 | Proposal; collision review required |
| P2SH address format | Not enabled | Current script prototype does not define P2SH spending |
| SegWit / Bech32 | Not enabled | No corresponding consensus implementation |
| P2P message start | 42 52 54 31 ("BRT1") | Proposal; uniqueness review required |
| Default P2P port | 28444 | Proposal |
| Default RPC port | 28445 | Proposal; must bind localhost and require authentication |
| Protocol version | 1 | Proposal |
| Public chain ID | Must be derived from the finally approved genesis block and parameters | Pending |

## Address construction

For the currently implemented legacy P2PKH script only:

1. Generate a compressed secp256k1 public key using a reviewed cryptographic library.
2. Compute HASH160 = RIPEMD160(SHA256(compressed_public_key)).
3. Prefix the 20-byte HASH160 with the proposed 0x26 version byte.
4. Append the first four bytes of SHA256(SHA256(version || HASH160)).
5. Encode the result using Base58.

This describes a candidate encoding only. It is not an instruction to generate a key or send funds. No wallet should display a production receive address until this proposal is reviewed, approved, and covered by independent test vectors.

## Required review before freezing

- Check address-prefix and message-magic collisions against existing networks and common software.
- Decide whether P2SH, SegWit, or only legacy P2PKH is supported in the first release.
- Confirm network ports and protocol version against the eventual node implementation.
- Derive and publish the chain ID only after the final genesis block is independently reproduced.
- [x] Add an independent Node.js 22 Base58Check/P2PKH vector for the proposed 0x26 encoding, including checksum, wrong-version, and payload-length rejection. The vector is exercised in CI; it does not approve or freeze the provisional prefix.
- [ ] Complete external prefix-collision review and broader cross-client tests before freezing the address version.
- Update the normative protocol specification and all node/wallet implementations atomically.
- Obtain independent protocol and security review.

## Safety boundary

This proposal does not activate a network, allocate or mint BRT, create a founder balance, or establish a market price or liquidity. Do not send real assets to addresses generated from these provisional parameters.


## P2P handshake identity proposal (not implemented)

The current frame magic is a useful early rejection filter, but it is only four bytes and is not sufficient as the authenticated chain-identity decision. The current `version` payload does not carry `network_id` or `genesis_hash`; therefore two peers configured with the same magic but different genesis identities can currently complete `version/verack`.

### Proposed fail-closed identity check

Before enabling synchronization on any non-loopback listener, the protocol review should decide and freeze all of the following together:

1. Add a fixed-width 32-byte `network_id` and 32-byte `genesis_hash` to a versioned handshake format. The values must come from the node's validated immutable network configuration, not from peer input or caller-overridable metadata.
2. Require exact equality for both fields before sending/accepting the handshake completion acknowledgement. A mismatch closes the connection and must not dispatch application messages, request headers, or schedule synchronization.
3. Keep the four-byte message magic check as an inexpensive frame filter, not as the sole identity check. Collision review remains required before freezing its value.
4. Make the wire-format change an explicit protocol-version boundary. Do not silently append fields to the existing version-1 payload: old decoders may reject trailing bytes or parse ambiguously. Version 1 remains loopback-only until a migration policy is approved; the new format must not be enabled by configuration alone before its version and compatibility policy are frozen.
5. Separately decide whether peers must use an exact protocol version or a reviewed compatibility range. The current minimum-version-only behavior accepts higher versions and must not be mistaken for negotiated feature compatibility. Unknown feature bits or incompatible required capabilities must fail closed.

### Required negative and integration tests

- Same magic, different `network_id`: reject before handshake completion and before any application callback.
- Same magic and `network_id`, different `genesis_hash`: reject before handshake completion and before synchronization.
- Different magic: retain the existing frame-level rejection test.
- Matching identities: complete handshake and permit application messages only after both acknowledgements.
- Old/new protocol combinations: verify the explicitly approved compatibility matrix; no implicit fallback or downgrade.
- Mutated, truncated, oversized, and malformed identity fields: reject without partial connection state or resource leaks.
- End-to-end loopback sync: prove a peer with mismatched identity cannot trigger header/body requests or alter local chain state.

No identity field, wire format, network identifier, protocol version, or public endpoint is activated by this proposal. The actual values and compatibility policy remain pending owner approval and independent review.
