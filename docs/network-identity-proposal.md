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
- Add independent encode/decode vectors, malformed-checksum tests, and cross-implementation tests.
- Update the normative protocol specification and all node/wallet implementations atomically.
- Obtain independent protocol and security review.

## Safety boundary

This proposal does not activate a network, allocate or mint BRT, create a founder balance, or establish a market price or liquidity. Do not send real assets to addresses generated from these provisional parameters.
