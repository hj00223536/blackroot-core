# Difficulty adjustment and chainwork prototype

**Status:** owner-approved difficulty parameters and boundary convention; independent implementation and external review remain open. Not activated as a network consensus rule.

## Parameters proposed

- Target spacing: 600 seconds.
- Retarget interval: 2,016 blocks.
- Nominal target timespan: 1,209,600 seconds (14 days).
- Actual timespan clamp: one quarter to four times the nominal timespan.
- New target: previous target multiplied by clamped actual timespan and divided
  by nominal target timespan, capped at the network proof-of-work limit.
- Header work: floor(2^256 / (target + 1)).
- Chainwork: sum of each accepted block's work.

## Retarget boundary: current implementation record, not a frozen rule

The helper function retarget_compact(previous_bits, actual_timespan, pow_limit)
only performs the arithmetic. The current HeaderChain implementation samples
the parent timestamp and the ancestor at candidate_height - 2,016. Therefore,
for a candidate at height 2,016 it samples block 2,015 and block 0: 2,015
elapsed timestamp intervals are compared with the nominal 2,016 * 600-second
target timespan. A regression test pins this exact behavior.

The owner approved this boundary formula and the stated difficulty parameters on 2026-11-26. This approval does not settle median-time-past rules, future timestamp limits, genesis behavior, minimum-difficulty exceptions, or whether test networks use special rules. These remain separate consensus-critical decisions.

## Current in-memory HeaderChain behavior

The in-memory HeaderChain stores headers by hash, permits extending any known
parent through add_to_branch, accumulates per-header work, and selects the
branch with greatest cumulative work (with a deterministic raw-hash tie-break).
The owner has not approved the chain-selection tie-break or reorganization policy.
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
