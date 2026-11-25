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
