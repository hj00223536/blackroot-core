# Block transaction validation prototype

The current `src/blackroot_blocks.py` adds a deterministic block container and
an accounting validator.

It checks:
- A single coinbase transaction is first, with a 2–100 byte coinbase script.
- No second coinbase or duplicate transaction IDs appear in the block.
- The header merkle root commits to the exact ordered transaction list.
- Every regular input must pass the currently supported legacy P2PKH ECDSA `SIGHASH_ALL` authorization check; unsupported script forms fail closed.
- Regular transactions spend existing UTXOs, conserve value, and contribute bounded fees.
- Coinbase outputs do not exceed the height subsidy plus transaction fees, and each transaction/output total is range-checked against the provisional `MAX_MONEY`.
- When authenticated parent UTXO provenance is supplied, coinbase maturity and BIP68 height/time relative sequence locks are enforced; missing provenance needed by an enabled relative lock fails closed.
- Legacy absolute nLockTime finality is checked using candidate height or parent median-time-past.
- Coinbase outputs are added after regular transactions, so the current block's coinbase cannot be spent in the same block.
- Validation works on a copy of the parent UTXO mapping; failure does not mutate that input snapshot.
- Persistent block connection/reorganization uses coordinated SQLite transactions and has dedicated rollback/recovery tests.

## Critical limitations

This is **not complete consensus**. Script support is limited to a prototype
legacy P2PKH verifier; it is not a complete Script interpreter and requires
independent cryptographic review. The block validator itself does not validate
header proof of work, difficulty, linkage, or timestamp policy: those checks
must be performed by the header-chain layer before a body is eligible for
connection. The local node still uses a provisional system clock rather than
a reviewed network-adjusted time policy. Witness transactions, broader script
features, finalized block resource limits, complete normative serialization
and economic rules, adversarial interoperability, and independent client
verification remain incomplete. The current 1,000,000-byte block ceiling is
provisional, not a frozen protocol parameter.

Tests of selected SQLite atomicity and crash-recovery paths are not proof of
power-loss durability or production operations. Do not use this prototype
with real funds or present it as a public network.
