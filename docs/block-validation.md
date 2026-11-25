# Block transaction validation prototype

The current `src/blackroot_blocks.py` adds a deterministic block container and
an accounting validator.

It checks:
- A single coinbase transaction is first, with a 2–100 byte coinbase script.
- No second coinbase or duplicate transaction IDs appear in the block.
- The header merkle root commits to the exact ordered transaction list.
- Every regular input must pass the currently supported legacy P2PKH ECDSA `SIGHASH_ALL` authorization check; unsupported script forms fail closed.
- Regular transactions then spend existing UTXOs and conserve value; fees are summed.
- The coinbase output total does not exceed the height subsidy plus fees.
- Coinbase outputs are added after regular transactions, so this prototype
  cannot spend the current block's coinbase in the same block.
- Validation works on a copy of the parent UTXO mapping; failure does not mutate it.

## Critical limitations

This is **not complete consensus**. Script support is limited to a prototype
legacy P2PKH verifier; it is not a complete Bitcoin Script interpreter and
requires independent cryptographic review. It does not enforce coinbase
maturity, validate witness data, enforce block weight/serialized block size,
check header proof of work or difficulty schedule, check timestamps, or
atomically persist a block and its UTXO changes. The
coinbase maturity rule and script system must be specified before real funds
or a public network are considered. Do not use this prototype as a live node.
