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

## Current in-memory HeaderChain behavior

The in-memory HeaderChain stores headers by hash, permits extending any known
parent through add_to_branch, accumulates per-header work, and selects the
branch with greatest cumulative work (with a deterministic raw-hash tie-break).
best_chain() returns the selected header path, and reorganization(old_tip_hash)
reports headers to disconnect in tip-first order and headers to connect in
fork-first order.

It enforces median-time-past using up to the 11 timestamps ending at the
candidate's parent. At a 2,016-block boundary it samples the ancestor at
candidate_height - 2,016 and uses the parent timestamp to calculate the
timespan. The optional future-time bound is enforced only when the caller
supplies adjusted_time; it is not enabled automatically.

This is header-only scaffolding. It does not validate full block bodies,
scripts, UTXOs, or persistent side branches. The reported reorganization paths
are not authorization to mutate the persistent UTXO database. Atomic,
fully validated block-level reorganization must be implemented before a node
can use this as consensus.

## Required validation before network activation

Publish exact vectors for every boundary, including compact-target
overflow/canonical encodings, pow-limit edges, retarget clamps, timestamp edge
cases, and competing-branch selection. Compare the implementation against an
independent reference implementation and obtain external consensus/security
review. Define network-specific exception rules and a normative clock-adjustment
and future-time policy. Existing unit tests are regression evidence only.
