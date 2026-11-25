# BLACKROOT protocol design

**Document status:** draft; not a production consensus specification.

## Design targets

| Item | Current target |
|---|---|
| Network | Independent chain |
| Asset | BRT (provisional ticker) |
| Ledger | UTXO |
| Consensus | Proof of Work |
| Work hash | SHA-256d |
| Target block interval | 600 seconds |
| Retarget interval | 2,016 blocks |
| Initial subsidy | 5,000,000,000 atomic units (50 BRT) |
| Halving interval | 210,000 blocks |
| Precision | 100,000,000 atomic units per BRT |
| Premine | None proposed |
| Supply ceiling | 2,100,000,000,000,000 atomic units (21 million BRT) |

These are design targets, not a frozen network specification or a promise
that any token has been issued or has monetary value.

## Block header

The reference module uses the conventional 80-byte header layout:

1. version: unsigned 32-bit little-endian integer
2. previous block hash: 32 bytes in wire/internal little-endian order
3. merkle root: 32 bytes in wire/internal little-endian order
4. timestamp: unsigned 32-bit little-endian Unix time
5. compact target (nBits): unsigned 32-bit little-endian integer
6. nonce: unsigned 32-bit little-endian integer

The block identifier is SHA256(SHA256(header)); display formatting reverses
the digest bytes, as in Bitcoin-style conventions.

## Proof of Work and header-chain prototype

A candidate header is checked for a positive, canonically encoded target no
greater than the configured proof-of-work limit, then its SHA-256d hash is
compared to that target using the prototype's little-endian numeric convention.

The in-memory HeaderChain prototype tracks known header branches, accumulated
work, median-time-past, and the proposed fixed retarget schedule. It can select
a greatest-chainwork header branch. It does not validate block bodies, scripts,
UTXO transitions, or persistent reorganization atomically; the future-time
bound is opt-in. These helpers are not a complete production consensus engine.

## Existing P2P building blocks

The repository contains bounded message framing, version/verack sequencing,
asyncio TCP peer sessions, a bounded peer manager, and selected header/block
synchronization components with loopback integration tests. The handshake is
not cryptographic peer authentication. Peer discovery, Sybil/eclipse
resistance, production peer reputation/ban policy, and a supervised runnable
node application are not complete.

## Rules still requiring a normative specification

- Exact genesis parameters and the approval process for the current candidate
  vector (see docs/testnet-genesis-candidate.md)
- Testnet network identifier, four-byte message-start value, address encodings,
  ports, protocol version, payload limits, and peer policy
- Exact retarget boundary behavior, future-time policy, clock adjustment, and
  any minimum-difficulty exceptions
- Normative transaction format, signature hashing, script language, sighash
  flags, witness rules, and consensus limits
- Coinbase maturity and subsidy-plus-fees validation policy
- Relative sequence-lock semantics: BIP68 height locks and timestamp-based relative locks are implemented in the block-validation path. Time locks use the parent-chain MTP of the candidate block and the persisted MTP immediately preceding UTXO creation; missing metadata fails closed. The SQLite UTXO schema is version 3 and schema-v2 databases require a verified reindex from genesis rather than an invented MTP history.
- UTXO database format, undo data, reorg recovery, and atomic block-level
  best-chain state transitions
- Peer discovery, bans, rate limits, DoS controls, and adversarial testing
- Mempool policy and fee calculation
- Wallet derivation, address checksums, backup/restore, and hardware-wallet
  compatibility
- Upgrade/versioning and activation process

A versioned engineering inventory of known parameters and unresolved launch gates is maintained in docs/testnet-protocol-v0.1-draft.md. That document is explicitly non-normative and does not authorize activation.

No implementation may silently change a consensus rule after launch. Every
consensus change needs a versioned specification, test vectors, compatibility
analysis, and public review.
