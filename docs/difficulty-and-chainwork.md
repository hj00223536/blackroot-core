# Difficulty adjustment and chainwork prototype

**Status:** proposed Bitcoin-style rule and reference helpers; not activated
as a network consensus rule.

## Parameters proposed

- Target spacing: 600 seconds.
- Retarget interval: 2,016 blocks.
- Nominal target timespan: 1,209,600 seconds (14 days).
- Actual timespan clamp: one quarter to four times the nominal timespan.
- New target: previous target multiplied by clamped actual timespan and divided
  by nominal target timespan, capped at the network proof-of-work limit.
- Header work: floor(2^256 / (target + 1)).
- Chainwork: sum of each accepted block's work.

## Important boundary details still to decide

The helper function retarget_compact(previous_bits, actual_timespan, pow_limit)
only performs the arithmetic. A normative protocol must still define exactly
which ancestor timestamps are sampled at a retarget boundary, whether the
timespan covers 2,015 or 2,016 timestamp intervals, median-time-past rules,
future timestamp limits, genesis behavior, minimum-difficulty exceptions, and
whether test networks use special rules. These details are consensus-critical.

The in-memory HeaderChain prototype now accumulates per-header work, but it
still accepts only a direct extension of its current tip. It does not maintain
competing branches, compare branch chainwork, validate retarget boundaries,
persist headers, or reorganize the active chain. Its chainwork property is
therefore diagnostic only and must not be treated as production chain selection.

Before a public network exists, publish exact test vectors for every boundary,
including compact-target overflow/canonical encodings, pow-limit edges,
retarget clamps, timestamp edge cases, and competing-branch selection. Compare
the implementation against an independent reference implementation and obtain
external consensus/security review.


## Header DAG prototype and fork choice

The in-memory HeaderChain now stores headers by hash, permits extending any known parent through add_to_branch, accumulates per-header work, and selects the branch with greatest cumulative work (with a deterministic raw-hash tie-break). best_chain() returns the selected header path. reorganization(old_tip_hash) reports headers to disconnect in tip-first order and headers to connect in fork-first order.

This is header-only scaffolding. It does not validate median-time-past, future-time limits, retarget boundaries, full block bodies, scripts, UTXOs, or persistent side branches. The returned paths are not authorization to mutate the persistent UTXO database. Full consensus validation and atomic block-level reorganization must be implemented before any node can use this for consensus.

The header DAG also enforces the median-time-past rule using up to the 11 timestamps ending at the candidate's parent. It intentionally does not yet implement the network-adjusted future-time bound or difficulty-retarget boundary calculation.


## Difficulty enforcement

HeaderChain now requires the parent nBits between retarget boundaries and computes a new compact target at each 2016-block boundary. The measured span is the parent timestamp minus the ancestor timestamp at candidate_height - 2016, clamped by retarget_compact to one quarter through four times the nominal 1,209,600 seconds, then capped at the network proof-of-work limit. Boundary and non-boundary behavior have unit tests.

This remains a reference prototype: network-specific exception rules, future-time bounds, full compact-target canonicality policy, and consensus test vectors still require specification and independent review.
