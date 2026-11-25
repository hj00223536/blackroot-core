# BLACKROOT protocol design

**Document status:** draft; not a production consensus specification.

## Design targets

| Item | Current target |
|---|---|
| Network | Independent chain |
| Asset | BROOT (provisional ticker) |
| Ledger | UTXO |
| Consensus | Proof of Work |
| Work hash | SHA-256d |
| Target block interval | 600 seconds |
| Retarget interval | 2,016 blocks |
| Initial subsidy | 5,000,000,000 atomic units (50 BROOT) |
| Halving interval | 210,000 blocks |
| Precision | 100,000,000 atomic units per BROOT |
| Premine | None proposed |
| Supply ceiling | 2,100,000,000,000,000 atomic units (21 million BROOT) |

## Block header

The reference module uses the conventional 80-byte header layout:

1. version: unsigned 32-bit little-endian integer
2. previous block hash: 32 bytes in wire/internal little-endian order
3. merkle root: 32 bytes in wire/internal little-endian order
4. timestamp: unsigned 32-bit little-endian Unix time
5. compact target (nBits): unsigned 32-bit little-endian integer
6. nonce: unsigned 32-bit little-endian integer

The block identifier is SHA256(SHA256(header)); display formatting reverses the digest bytes, as in Bitcoin-style conventions.

## Proof of Work

A candidate block is valid only if its decoded target is positive, within the selected network maximum target, and the numeric hash interpreted as a little-endian integer is less than or equal to that target. The reference helper validates compact-target encoding and PoW comparison only. It does not implement chain consensus.

## Rules still requiring a normative specification

- Exact genesis header, coinbase transaction, timestamp message, merkle root, nonce, and initial difficulty
- Mainnet/testnet/regtest network magic, address encodings, ports, and chain identifiers
- Difficulty retarget formula, actual-timespan clamps, timestamp median rules, and minimum-difficulty behavior (if any)
- Transaction format, signature hashing, script language, sighash flags, witness rules, and consensus limits
- Coinbase maturity and subsidy-plus-fees validation
- UTXO database format, undo data, reorg handling, and chainwork selection
- P2P message framing, peer discovery, bans, rate limits, and DoS controls
- Mempool policy and fee calculation
- Wallet derivation, address checksums, backup/restore, and hardware-wallet compatibility
- Upgrade/versioning and activation process

No implementation may silently change a consensus rule after launch. Every consensus change needs a versioned specification, test vectors, compatibility analysis, and public review.
