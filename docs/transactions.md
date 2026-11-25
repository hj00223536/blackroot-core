# Transaction and UTXO reference prototype

**Status:** experimental encoding/accounting reference only. This is not a
complete or safe transaction-consensus implementation.

## Wire format currently implemented

The prototype encodes a legacy-style transaction as:

1. signed 32-bit little-endian version
2. CompactSize input count
3. each input: 32-byte raw previous transaction digest, uint32 output index,
   CompactSize-prefixed scriptSig, uint32 sequence
4. CompactSize output count
5. each output: uint64 little-endian value, CompactSize-prefixed scriptPubKey
6. uint32 little-endian lock_time

CompactSize uses the one-byte, 0xfd/uint16, 0xfe/uint32, and 0xff/uint64
forms. Transaction IDs are SHA256d(serialized transaction); display form
reverses the raw digest bytes.

The merkle helper combines raw transaction digests with SHA256d(left || right)
and duplicates the final hash at odd-width levels. Empty input returns 32 zero
bytes.

## UTXO accounting implemented

The in-memory reference checks:
- each referenced outpoint exists;
- no outpoint is spent twice in one transaction;
- each output value is within the configured money range;
- aggregate input and output values remain within that range;
- outputs do not exceed inputs; and
- applying a valid transaction removes spent outputs and creates new outputs.

## Critical omissions — do not use for funds

This code does **not** execute scriptPubKey/scriptSig, verify ECDSA/Schnorr
signatures, enforce signature-hash rules, implement SegWit/witness, coinbase
transactions, coinbase maturity, subsidy-plus-fees checks, locktime or sequence
semantics, transaction finality, block weight/size rules, mempool policy,
persistent UTXO storage, undo/reorg handling, or transaction malleability
protections. The strings called scripts are opaque bytes only.

Consequently, the UTXO accounting helper proves only value conservation against
a caller-supplied map. It does not prove that a spender is authorized to spend
the referenced outputs. All values and scripts are untrusted input until a
complete consensus script engine and signature verification are implemented
and independently reviewed.
