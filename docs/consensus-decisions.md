# BLACKROOT provisional consensus decisions

**Status: engineering record — the owner-approved monetary schedule is integrated into the reference subsidy helper, but no public network rules are frozen or activated.**

## Current implementation behavior

| Area | Current prototype behavior | Decision still required |
|---|---|---|
| Header encoding | 80-byte header; little-endian uint32 fields; SHA-256d | Confirm final serialization and versioning rules |
| Proof of work | Bitcoin-style compact target; reject zero, negative and overflow encodings; require target at or below configured proof-of-work limit; compare little-endian SHA-256d integer | Freeze canonical encoding and network-specific limit |
| Retarget interval | Owner-approved: retarget when candidate height is divisible by 2,016 | Independent implementation and external consensus review remain open |
| Retarget timestamps | Owner-approved: for candidate height 2,016, measure parent height 2,015 timestamp minus ancestor height 0 timestamp: 2,015 elapsed block intervals | Independent implementation and external consensus review remain open |
| Retarget clamp | Owner-approved: clamp measured seconds to one quarter through four times 2,016 × 600 seconds | Independent implementation and external consensus review remain open |
| Retarget arithmetic | Owner-approved: multiply previous decoded target by bounded-timespan, integer-divide by target-timespan, cap at PoW limit, then encode compact nBits | Independent implementation and external consensus review remain open |
| Compact precision | Encoding discards low-order target precision; decoded target can be slightly below the uncompressed integer result | Confirm canonical compact encoding and reject non-canonical alternatives consistently |
| Median time past | Median of up to 11 timestamps ending at the candidate's parent | Confirm ancestor count and genesis handling |
| Future timestamp | HeaderChain checks a future bound only if caller supplies adjusted_time; default allowance is 7,200 seconds | Define a trusted network-adjusted clock, peer-time algorithm, and mandatory validation path |
| Branch choice | Select greatest cumulative work; equal-work tie-break uses deterministic raw-hash ordering | Confirm tie-break and reorg policy |
| Subsidy | 10 BRT per block at heights 1 through 2,000,000 inclusive; zero at height 0 and after height 2,000,000 | Complete independent cross-client monetary vectors |
| Maximum supply | 20,000,000 BRT founder genesis allocation plus maximum 20,000,000 BRT scheduled mining issuance; 40,000,000 BRT total ceiling | Implement and verify spendable founder genesis output |
| Script support | Strict legacy P2PKH/SIGHASH_ALL subset; unsupported scripts and sighash modes rejected | Define full transaction/script language or explicitly freeze a limited language |

| Genesis UTXO time provenance | Persistent UTXO storage currently serializes missing creation-MTP metadata as integer zero | Define genesis-output spendability and a nullable/explicitly tagged MTP representation before time-based relative locks can be considered production-safe |

## Independent arithmetic regression evidence

A standalone Node.js 22 script (`scripts/verify_retarget_vectors.mjs`) now reproduces the current compact-target retarget arithmetic, including quarter/nominal/double/four-times clamp vectors and the candidate-height-2016 first-boundary convention (2,015 elapsed intervals against a 2,016-interval target span). CI runs this script separately from the Python implementation. The Node.js verifier and Python 3.12/3.13 suites all passed in [GitHub Actions run 45827374549](https://github.com/hj00223536/blackroot-core/actions/runs/45827374549): 428 Python tests on each version, independent genesis/transaction/P2PKH/address/retarget vectors, and SQLite resource-warning checks with exit code 0. This confirms arithmetic parity for the selected fixtures only; it does not decide whether the first-boundary convention is the desired BLACKROOT rule, validate the full header-chain path, or replace an independently maintained client and external protocol review.

The [difficulty-adjustment policy](difficulty-adjustment-policy-proposal.md) records the owner's approval of its parameters and first-boundary convention on 2026-11-26. Boundary and branch-local regression vectors are present; independent implementation and external consensus review remain open.

## Required protocol decisions before testnet activation

1. **First retarget period:** the owner-approved boundary convention is documented; independently reproduce vectors at heights 2,015, 2,016, 2,017 and across a reorganization.
2. **Timestamp validity:** specify MTP, future-time bound, clock adjustment, missing-clock behavior, and whether all node entry points enforce the same rule.
3. **Difficulty arithmetic:** owner-approved constants and integer arithmetic are documented; independently reproduce compact encoding canonicality and PoW-limit edge behavior.
4. **Chain selection:** specify cumulative-work comparison, equal-work behavior, and reorganization limits/recovery.
5. **Script and transaction validity:** publish the complete supported script set, sighash rules, locktime/sequence semantics, serialization, and consensus limits.
6. **Founder genesis output:** construct and independently verify the spendable founder allocation without committing private key material.

## Verification requirements

- Add immutable vectors for every boundary and invalid case.
- Reproduce vectors in a separately maintained client or independent implementation, not merely a second test file in this repository.
- Run cross-version CI and multi-process synchronization/reorganization tests against those vectors.
- Require independent consensus/security review before publishing a public testnet.
- Keep every unresolved item marked provisional; do not describe prototype behavior as a frozen BLACKROOT protocol.

## Non-goal

This document does not authorize a public testnet or mainnet, public mining, deposits, sales, exchange listing, or claims of monetary value.
