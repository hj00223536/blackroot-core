# BLACKROOT time-validity policy proposal

**Status: PROPOSAL ONLY — not frozen consensus and not authorization to launch a network.**

This document records the current header-chain behavior and the decisions required before time validity can be treated as production consensus.

## Current prototype behavior

- A candidate header timestamp must be strictly greater than the median timestamp of up to the 11 headers ending at its parent (MTP).
- Network-mode header admission now fails closed when `adjusted_time` is omitted for a non-genesis header; the explicit `allow_unchecked_time_for_tests=True` constructor option exists only for offline fixtures.
- The current helper default for `max_future_seconds` is 7,200 seconds (two hours).
- `HeaderChain` now accepts an injected `adjusted_time_provider` callable. When configured, normal non-genesis admission obtains its reference time from that provider. `PersistentHeaderStore` and `PersistentNodeState` now accept and pass the provider through initialization, replay, and candidate-chain rebuilding. The chain still cannot authenticate the provider or decide how peer time is sampled; production clock sourcing and peer-time adjustment remain unresolved. Explicit `adjusted_time` remains available for deterministic validation and batch admission.
- The in-memory header DAG does not establish a peer-time sampling or clock-synchronization policy.

These are prototype facts, not a complete network time policy.

## Decisions required before protocol freeze

| Decision | Candidate approach | Status |
|---|---|---|
| MTP window | Median of up to 11 ancestor headers, including the candidate's parent | Existing prototype behavior; requires independent vectors |
| MTP comparison | Require candidate timestamp strictly greater than MTP | Existing prototype behavior; requires normative specification |
| Future-time limit | Two hours beyond a network-adjusted reference time | Candidate only; owner and protocol review required |
| Clock source | Inject a trusted network-adjusted time provider into every block/header acceptance path | Required architecture; provider and trust model not selected |
| Missing clock | Fail closed for network operation rather than silently skipping the future bound | Implemented in header admission by default; explicit test-only bypass remains |
| Peer-time adjustment | Define sampling, outlier rejection, maximum adjustment and behavior with too few peers | OPEN |
| Local clock failure | Define startup, drift, rollback and loss-of-connectivity behavior | OPEN |
| Historical validation | Specify deterministic handling of future-time checks during initial sync and reindex | OPEN |

## Integration status

- [x] Injected adjusted-time provider supported by the in-memory header DAG.
- [x] Provider wired through persistent header-store replay and candidate reconstruction.
- [x] Provider parameter exposed by persistent node-state constructors.
- [x] P2P header-sync path requires a provider and validates the returned value.
- [ ] Production peer-time sampling, outlier policy, trust model and lifecycle wiring.
- [ ] Full node ingress audit proving no alternate path bypasses the clock provider.

## Required implementation properties

1. Every externally reachable header acceptance path must enforce the same frozen time rules.
2. A caller must not be able to bypass the future-time bound by omitting an optional argument.
3. The clock provider must be explicit, testable and isolated from consensus arithmetic. The prototype now supports injection, but production wiring and trust policy are still open.
4. Tests must cover timestamps equal to MTP, one second above MTP, exactly at the future bound, one second beyond it, missing clock, provider-returned invalid values, provider failures and clock rollback.
5. Reorganization and batch insertion must apply the same rules atomically to every header.
6. Independent clients must reproduce the normative boundary vectors.

## Stop conditions

- Do not call timestamp validation production-ready until every production ingress supplies an authenticated network-adjusted clock and the test-only bypass is unreachable from production configuration.
- Do not choose a peer-time algorithm or claim it is secure without specification, adversarial tests and review.
- Do not expose a public testnet until all time-validity decisions and enforcement paths are resolved.
- This proposal does not authorize changing existing consensus constants or launching a network.

## Related documents

- [Protocol-freeze gap register](protocol-freeze-gap-register.md)
- [Difficulty-adjustment policy proposal](difficulty-adjustment-policy-proposal.md)
- [Testnet launch gates](testnet-launch-gates.md)
- [Mainnet launch gates](mainnet-launch-gates.md)
