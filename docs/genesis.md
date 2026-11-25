# Genesis block requirements

The BLACKROOT genesis block has **not** been generated. This document records the work required before one can be committed as a network constant.

## Required decisions

- Exact genesis timestamp and human-readable coinbase message
- Genesis coinbase transaction serialization
- Merkle-root construction and byte order
- Initial compact difficulty target
- Nonce and resulting block hash
- Chain/network identifier and message-start bytes
- Whether the genesis coinbase output is intentionally unspendable (recommended for a Bitcoin-style convention)

## Deterministic generation procedure

1. Freeze and publish the complete genesis parameters in a reviewed specification.
2. Serialize the coinbase transaction using the final transaction format.
3. Compute the merkle root from the exact serialized transaction.
4. Serialize the 80-byte header using the specified byte order.
5. Search nonce (and, if necessary, timestamp/extra-nonce fields) until SHA-256d meets the initial target.
6. Have at least two independent implementations reproduce the same transaction ID, merkle root, header bytes, and block hash.
7. Add immutable test vectors and assert them in CI.
8. Publish the genesis parameters and source revision before enabling public peers or mining.

## Verification record

| Field | Status |
|---|---|
| Timestamp/message | Not selected |
| Coinbase transaction | Not implemented |
| Merkle root | Not computed |
| Initial target | Not selected |
| Nonce | Not mined |
| Genesis hash | Not generated |
| Independent reproduction | Not performed |

A fabricated or hand-picked genesis hash is not acceptable. A genesis block is a deterministic protocol constant, not a marketing graphic.
