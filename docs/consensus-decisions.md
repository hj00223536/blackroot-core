# BLACKROOT provisional consensus decisions

**Status: engineering record only — none of these rules are frozen for a public network.**

This document records behavior currently present in the prototype so that test results are not mistaken for an approved protocol. Any change to these rules can change chain validity and must be reviewed as a consensus change.

## Current implementation behavior

| Area | Current prototype behavior | Decision still required |
|---|---|---|
| Header encoding | 80-byte header; little-endian uint32 fields; SHA-256d | Confirm final serialization and versioning rules |
| Proof of work | Bitcoin-style compact target; reject zero, negative and overflow encodings; require target at or below configured proof-of-work limit; compare little-endian SHA-256d integer | Freeze canonical encoding and network-specific limit |
| Retarget interval | Retarget when candidate height is divisible by 2,016 | Confirm interval boundary and first-period convention |
| Retarget timestamps | For candidate height 2,016, measure parent height 2,015 timestamp minus ancestor height 0 timestamp: 2,015 elapsed block intervals | Decide whether this is intended or whether the first retarget should use a different boundary |
| Retarget clamp | Clamp measured seconds to one quarter through four times 2,016 × 600 seconds | Confirm exact clamp policy |
| Retarget arithmetic | Multiply previous decoded target by bounded-timespan, integer-divide by target-timespan, cap at PoW limit, then encode compact nBits | Freeze integer arithmetic and compact truncation behavior with cross-client vectors |
| Compact precision | Encoding discards low-order target precision; decoded target can be slightly below the uncompressed integer result | Confirm canonical compact encoding and reject non-canonical alternatives consistently |
| Median time past | Median of up to 11 timestamps ending at the candidate's parent | Confirm ancestor count and genesis handling |
| Future timestamp | HeaderChain checks a future bound only if caller supplies adjusted_time; default allowance is 7,200 seconds | Define a trusted network-adjusted clock, peer-time algorithm, and mandatory validation path |
| Branch choice | Select greatest cumulative work; equal-work tie-break uses deterministic raw-hash ordering | Confirm tie-break and reorg policy |
| Subsidy | 50 BRT initial subsidy, integer halving every 210,000 heights, 100,000,000 atomic units per BRT | Confirm monetary policy and genesis-height convention |
| Maximum supply | The current integer schedule sums to 20,999,999.9769 BRT, below the nominal 21,000,000 BRT cap | Decide whether this small unissued remainder is intentional |
| Script support | Strict legacy P2PKH/SIGHASH_ALL subset; unsupported scripts and sighash modes rejected | Define full transaction/script language or explicitly freeze a limited language |

## Required protocol decisions before testnet activation

1. **First retarget period:** choose and document the exact start/end block timestamps used at each boundary. Include vectors at heights 2,015, 2,016, 2,017 and across a reorganization.
2. **Timestamp validity:** specify MTP, future-time bound, clock adjustment, missing-clock behavior, and whether all node entry points enforce the same rule.
3. **Difficulty arithmetic:** specify clamp constants, integer division order, compact encoding canonicality, and behavior when target reaches the PoW limit.
4. **Chain selection:** specify cumulative-work comparison, equal-work behavior, and reorganization limits/recovery.
5. **Monetary rules:** specify subsidy at genesis, halving boundaries, fees, coinbase maturity, total issuance, and treatment of unclaimed/invalid rewards.
6. **Script and transaction validity:** publish the complete supported script set, sighash rules, locktime/sequence semantics, serialization, and consensus limits.

## Verification requirements

- Add immutable vectors for every boundary and invalid case.
- Reproduce vectors in a separately maintained client or independent implementation, not merely a second test file in this repository.
- Run cross-version CI and multi-process synchronization/reorganization tests against those vectors.
- Require independent consensus/security review before publishing a public testnet.
- Keep every unresolved item marked provisional; do not describe prototype behavior as a frozen BLACKROOT protocol.

## Non-goal

This document does not authorize a public testnet or mainnet, public mining, deposits, sales, exchange listing, or claims of monetary value.
