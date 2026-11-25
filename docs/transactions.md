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

The accounting-only `validate_transaction` and `apply_transaction` helpers do not
execute scripts or authorize spends. Separately, block validation now invokes
the fail-closed legacy P2PKH verifier for every regular transaction input before
accounting. This is a narrow template check, not a general Script engine.
Coinbase maturity is conditional on authenticated provenance being supplied;
SegWit/witness, locktime/sequence semantics, transaction finality, block
weight/size rules, mempool policy, and transaction malleability protections
remain unimplemented. The standalone accounting helpers must never
be treated as proof that an input is authorized.

Consequently, the UTXO accounting helper proves only value conservation against
a caller-supplied map. It does not prove that a spender is authorized to spend
the referenced outputs. All values and scripts remain untrusted until the complete consensus rules and
a general, independently reviewed script engine are implemented.


## Experimental P2PKH authorization module

`src/blackroot_script.py` adds a fail-closed authorization verifier for the
legacy P2PKH template only. It checks the exact locking-script template,
two direct pushes in scriptSig, HASH160(pubkey), secp256k1 ECDSA, strict DER
integer encoding, low-S signatures, and legacy SIGHASH_ALL transaction
digests. Unknown script templates, malformed pushes, wrong keys, invalid
signatures, and unsupported sighash modes fail verification.

This is deliberately a separate API:
`validate_transaction_scripts(tx, utxos)`. It is wired into the current block-validation pipeline for regular inputs, but remains a narrow legacy P2PKH verifier and not a general Script engine.
`validate_transaction`, block connection, or UTXO reorganization, so existing
accounting-only test fixtures remain isolated from this authorization layer.
Do not treat this narrow verifier as complete consensus validation. The block
validator also accepts omitted provenance for legacy/test callers; coinbase
maturity is enforced only when complete authenticated provenance is supplied.
The standalone accounting helpers remain authorization-free.

Limitations: no general Bitcoin Script interpreter, P2SH, SegWit, multisig,
timelocks, script opcodes, sighash variants, or script resource accounting.
The pure-Python elliptic-curve implementation is an auditable prototype, not
a hardened constant-time cryptographic library. Production use requires
independent cryptographic review, differential test vectors, and a vetted
constant-time implementation.
