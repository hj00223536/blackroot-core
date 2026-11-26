# BLACKROOT difficulty-adjustment policy proposal

**Status: OWNER-APPROVED PARAMETERS — independent review and protocol freeze still required. This is not an activated network consensus configuration.**

This proposal records the current reference implementation's behavior in a normative, reviewable form so it can be accepted, amended, or rejected before testnet identity is frozen.

## Proposed constants

| Parameter | Proposed value |
|---|---:|
| Target spacing | 600 seconds |
| Retarget interval | 2,016 blocks |
| Target timespan | 1,209,600 seconds (2,016 × 600) |
| Minimum actual timespan | 302,400 seconds (target / 4) |
| Maximum actual timespan | 4,838,400 seconds (target × 4) |
| Arithmetic | Positive integer arithmetic; floor division |
| Compact target | Canonical compact encoding only |
| Maximum target | Explicit network-specific proof-of-work limit |

## Proposed boundary rule

For a candidate block at height h:

1. If h is not divisible by 2,016, the candidate must use its parent's nBits.
2. If h is divisible by 2,016, use the candidate's parent at height h - 1 and its ancestor at height h - 2,016.
3. Compute actual_timespan = timestamp(h - 1) - timestamp(h - 2,016).
4. Clamp that value to the inclusive range [target_timespan / 4, target_timespan × 4].
5. Compute new_target = floor(previous_target × bounded_timespan / target_timespan).
6. Cap new_target at the network proof-of-work limit.
7. Encode the result using canonical compact nBits; reject non-canonical encodings during header validation.

Under this convention, the first retarget at candidate height 2,016 measures 2,015 elapsed timestamp intervals (parent height 2,015 minus genesis height 0), while the target timespan remains 2,016 × 600 seconds. This is the exact current prototype behavior. It must be explicitly accepted or changed before protocol freeze.

## Proposed branch behavior

Retarget timestamps and previous difficulty must be read from the candidate's own parent branch, never from the currently selected best branch unless that is also the candidate's parent branch. A reorganization must therefore validate each candidate header using its own branch ancestry.

## Existing evidence

- Python reference helper: src/blackroot_consensus.py, function retarget_compact.
- Header-chain boundary selection: src/blackroot_chain.py, method HeaderChain.expected_bits.
- Header-chain construction now rejects proof-of-work limits outside the positive uint256 range, matching the standalone PoW helper; regression coverage is in tests/test_chain.py.
- Python regression coverage: tests/test_consensus.py and tests/test_chain.py.
- Independent Node.js arithmetic verifier: scripts/verify_retarget_vectors.mjs.
- CI runs the independent Node.js verifier alongside the other cross-language vectors.

The Node.js vectors cover quarter/nominal/double/four-times clamping and the 2,015-interval first-boundary result. They do not constitute a second full node or an external consensus audit.

## Required additional review before acceptance

- [x] Owner explicitly approved the proposed first-boundary convention and the stated difficulty parameters in ChatGPT on 2026-11-26; this records the owner's decision but is not a cryptographic signature or release authorization.
- [x] Add header-chain boundary coverage at heights 2,015, 2,016 and 2,017.
- [x] Add competing-branch vectors proving retarget calculations use branch-local ancestors.
- [x] Add integer-floor rounding and zero-target fail-closed regression vectors in Python and independent Node.js.
- [x] Existing vectors cover PoW-limit saturation; minimum-target behavior remains an explicit open protocol decision.
- [ ] Reproduce final vectors in a separately maintained implementation.
- [ ] Obtain independent consensus review and document any changes before testnet genesis is generated.

The checked boundary tests verify that candidate height 2,015 inherits its parent's bits, candidate height 2,016 uses the first-boundary calculation, and candidate height 2,017 inherits the newly calculated bits. The competing-branch test builds distinct timestamp histories and checks that each branch receives its own retarget result. These are in-repository regression tests; they do not constitute owner approval or an external implementation.

## Explicit separation from timestamp validity

This proposal addresses only difficulty adjustment. It does not define median-time-past, adjusted network time, the future-time bound, peer-time sampling, or timestamp acceptance at all network entry points. Those remain separate open protocol decisions.

## Safety

This proposal does not launch a testnet or mainnet, create a founder balance, activate mining, or authorize use of provisional address prefixes. No real funds should be sent to this prototype.
