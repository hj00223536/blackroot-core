# UTXO bootstrap provenance audit

**Status: source audit only — bootstrap provenance is unauthenticated and is not launch-ready.**

## Scope reviewed

This audit covers the experimental SQLite UTXO store's pre-activation bootstrap path and the limits of its current integrity verifier. It does not authenticate any existing database, select a Genesis allocation, or authorize issuance.

## Observed behavior

- `add_genesis_output()` inserts an output directly into `utxos` while no active block exists and increments `metadata.bootstrap_issued_sats`.
- The counter is bounded by the configured total-supply cap and is checked for canonical decimal encoding. It is accounting metadata, not a signed manifest, a Genesis marker, or proof of the origin of any output.
- Bootstrap outputs have `created_height=0`, `is_coinbase=0`, and `created_mtp=NULL`. The unknown MTP is deliberately not fabricated.
- The pre-activation verifier checks that the live UTXO value does not exceed the bootstrap accounting counter. This is only an upper-bound consistency check; it does not prove which outputs were originally issued or reconstruct spent bootstrap outputs.
- Once active blocks exist, the verifier checks block/transaction history and issuance schedule, but bootstrap outputs remain outside the active transaction index. Their origin and historical spend lineage cannot be independently reconstructed from the current tables.
- `apply()` is an accounting-only pre-activation helper. It mutates UTXOs without persisting raw transaction history or provenance, so a database created through this path cannot be treated as a replayable chain state.
- The existing undo checks can compare spent outputs to known active-chain transaction outputs. A bootstrap-origin input has no authenticated source transaction in the active history, so its undo record does not gain provenance merely because it is stored in SQLite.

## Security conclusion

A passing `verify_integrity()` result is not proof of deterministic full UTXO replay, bootstrap authenticity, or correct Genesis issuance. In particular, `bootstrap_issued_sats` must never be interpreted as an initialization marker or evidence that a founder allocation exists. A final UTXO snapshot and its self-reported counter are not independent evidence of origin.

Do not use bootstrap insertion or accounting-only `apply()` to initialize a public network, create a founder balance, or accept real value.

## Required closure work

1. Freeze a canonical bootstrap/Genesis manifest schema and byte-level canonicalization vectors.
2. Authenticate the exact manifest digest through a separately governed trust anchor with anti-rollback, revocation, rotation, and recovery rules.
3. Define a one-time initializer that derives every initial outpoint from the authenticated Genesis transaction/manifest rather than accepting arbitrary caller-supplied outputs.
4. Persist the authenticated manifest digest, network identity, Genesis commitment, initialization state, and auditable issuance record atomically with the initial UTXO state.
5. Make exact reopen idempotent; reject missing, altered, duplicated, partially applied, or post-activation initialization without mutation.
6. Implement deterministic replay from the frozen Genesis and compare the complete reconstructed UTXO set, spent history, undo metadata, provenance, issuance, and active tip against persisted state.
7. Add independent-client vectors, adversarial corruption tests, crash/fault injection, backup/restore drills, and independent security review.

Until these requirements are implemented and independently reviewed, bootstrap provenance and deterministic full replay remain blocking Mainnet gates. No issuance is authorized by this audit.
