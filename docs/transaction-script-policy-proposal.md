# BLACKROOT transaction and script policy proposal

**Status: PROPOSAL ONLY — not frozen consensus and not a launch authorization.**

This document records the behavior visible in the current prototype and the decisions required before PF-07 can close. It intentionally does not silently promote prototype limits into permanent consensus rules.

## 1. Current transaction format

The prototype currently supports a legacy, non-witness transaction encoding:

- signed 32-bit little-endian version;
- canonical CompactSize input count;
- inputs containing raw 32-byte txid, uint32 output index, CompactSize scriptSig, and uint32 sequence;
- canonical CompactSize output count;
- outputs containing uint64 little-endian value and CompactSize scriptPubKey;
- uint32 little-endian lock_time;
- txid = SHA-256d of the serialized transaction, displayed in reversed byte order.

The parser rejects truncated data, non-canonical CompactSize encodings, unsupported vector counts, scripts above the current 10,000-byte limit, transactions above the current 4,000,000-byte limit, and trailing bytes. The block prototype separately has a provisional 1,000,000-byte serialized block ceiling and 100,000-transaction count ceiling. These size/count limits are not yet approved as final network rules.

Witness serialization, witness txids, transaction weight, and witness commitment rules are not implemented. The owner must choose either a deliberately legacy-only first protocol or a versioned witness-capable format before protocol freeze.

## 2. Current script authorization

The block validator invokes a deliberately restricted P2PKH verifier:

- only the exact 25-byte P2PKH scriptPubKey template is accepted;
- scriptSig must contain exactly two direct pushes: signature-plus-sighash byte and public key;
- only SIGHASH_ALL is accepted;
- compressed and uncompressed secp256k1 public keys are parsed;
- DER signature parsing is strict and high-S signatures are rejected;
- unsupported script forms and sighash modes fail closed.

This is not a general Script virtual machine. P2SH, multisig, CLTV/CSV opcodes, SegWit, Taproot, arbitrary script execution, and alternate sighash modes must not be advertised as supported. The current secp256k1 arithmetic and ECDSA verifier are hand-written prototype code and have not received an independent cryptographic audit. It must not protect real funds.

## 3. Current block-level checks observed

The current block transaction validator checks:

- exactly one coinbase transaction, in position zero;
- coinbase scriptSig length from 2 through 100 bytes;
- duplicate transaction IDs within a block;
- Merkle-root match;
- UTXO existence, duplicate input spends, and input/output value conservation;
- P2PKH authorization for every ordinary transaction input;
- coinbase maturity when complete authenticated UTXO provenance is supplied;
- absolute nLockTime finality using candidate height or parent-chain median-time-past;
- BIP68-style relative height/time sequence locks for version >= 2;
- fees and coinbase reward not exceeding subsidy plus fees;
- no same-block spending of the current block's coinbase output.

The persistent UTXO connection path supplies provenance and applies block validation; callers using the standalone accounting-only helper must not be treated as consensus validation.

## 4. Decisions required before freezing PF-07

| Decision | Current prototype | Required owner/protocol decision |
|---|---|---|
| Transaction versions | signed int32; no version matrix | Define allowed versions and activation/unknown-version behavior |
| Serialization | legacy only | Explicitly freeze legacy-only v1 or design a separately versioned witness format |
| CompactSize | canonical encoding required | Freeze all boundary and malformed vectors |
| Input/output counts | 1..100,000 each | Approve bounded counts and resource accounting |
| Script size | 10,000 bytes | Approve per-script and aggregate transaction/block limits |
| Transaction size | 4,000,000 bytes | Reconcile with 1,000,000-byte block ceiling; define exact serialized-size metric |
| Script language | P2PKH only | Decide whether v1 intentionally supports only P2PKH; define future script-versioning path |
| Signature rules | strict DER, low-S, secp256k1, SIGHASH_ALL | Obtain independent cryptographic review and cross-implementation vectors |
| Public keys | compressed and uncompressed | Decide whether uncompressed keys remain valid in v1 |
| Absolute locktime | height/time threshold; time compares to parent MTP | Freeze exact comparison semantics and edge vectors |
| Relative sequence locks | BIP68-like behavior for version >= 2 | Freeze disable/type/mask constants, 512-second granularity and boundary semantics |
| Coinbase | first transaction, one null-prevout input, script length 2..100 | Define height commitment, extra nonce, duplicate coinbase identity and genesis exception |
| Coinbase maturity | provenance-based validation | Choose and freeze maturity interval and test reorg/replay behavior |
| Fees | input minus output value; coinbase ceiling subsidy + fees | Define overflow, fee aggregation, and any relay/mining policy separately from consensus |
| Same-block spends | ordinary transactions are applied in order; coinbase added last | Explicitly freeze ordering and dependency semantics |
| Duplicate txids | rejected within block; persistent UTXO collision checks exist | Add mutation and reorg vectors for duplicate txid/outpoint edge cases |

## 5. Required test package

Before PF-07 can be marked closed, add immutable positive and negative vectors for:

1. every CompactSize transition (252/253, 65,535/65,536, 2^32-1/2^32), non-canonical encodings, truncation, and trailing data;
2. transaction serialization/txid and Merkle roots, including odd leaf counts and duplicate txids;
3. P2PKH valid signatures, modified messages, wrong keys, malformed DER, high-S, wrong sighash, malformed pushes, and unsupported script types;
4. input duplication, missing UTXOs, value overflow, outputs greater than inputs, and UTXO outpoint collisions;
5. locktime immediately below/equal/above height and MTP thresholds;
6. relative sequence lock disable/type/mask behavior and exact 512-second boundaries;
7. coinbase position/count/script length/maturity and subsidy-plus-fees limits;
8. ordered same-block dependencies and reorganization rollback/replay;
9. identical vectors in a separately maintained independent implementation.

## 6. Safety and release gates

- Do not generate or commit private keys, seed phrases, or founder wallet material in GitHub.
- Do not use the prototype script verifier for real funds.
- Do not claim that P2PKH-only support is a complete Bitcoin-compatible Script implementation.
- Keep transaction relay/miner policy separate from consensus validity.
- Require independent cryptographic and protocol review before any public testnet that could be mistaken for a value-bearing network.
- PF-07 remains OPEN until the owner decisions, vectors, cross-client reproduction, and external review are complete.
