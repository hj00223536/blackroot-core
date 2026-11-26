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

## Source-level ingress and replay audit (2026-11-26)

The current source and focused tests establish the following narrower facts:

- `HeaderChain.add_to_branch()` rejects a non-genesis header when neither an explicit adjusted-time value nor an injected provider is available, unless the explicitly named test-only bypass is enabled. Provider output is type/range checked before the future-time comparison.
- `HeaderChain.add_batch()` samples its injected provider once for a non-empty batch and applies that same value to every header. Its in-memory rollback restores both the DAG and best-tip pointer if any member fails.
- `PeerHeaderSync` independently requires a clock callback before accepting a peer `headers` message, validates its returned value, and passes one sample into the atomic batch path. The focused coordinator tests cover missing/invalid clocks, future-header rejection without chain mutation, and rollback of a batch with a valid prefix followed by a future header.
- `PersistentHeaderStore` samples its provider once while replaying stored headers and once while rebuilding known branches for a new admission. That one sample is applied to every non-genesis header in the replay/rebuild, including historical side branches. A provider exception or invalid value therefore aborts that operation; the code does not silently disable the future-time check.
- `PersistentNodeState.add_header()` delegates to the persistent header store, so its normal network-mode path inherits the store/provider requirement. The local CLI currently supplies the host UTC clock; this is not peer-adjusted time.

The focused tests currently cover MTP boundaries, the 11-header window, explicit and injected future-time checks, one-sample batch behavior, invalid provider values, persistent replay/admission clock sampling, and P2P fail-closed behavior. This audit does **not** prove that every possible future block/body/import API is an ingress path or that all are protected; a complete call-graph audit remains required.

### Replay/clock questions still unresolved

1. Applying the *current* clock sample to every historical header means a local clock rollback or an unavailable/throwing provider can prevent database reopen/replay even when the stored chain was accepted earlier. The desired recovery behavior must be specified; do not weaken validation ad hoc.
2. The proposal does not yet distinguish live admission's future-time rule from deterministic historical/reindex validation. Define whether historical replay uses the same current-time bound, a separately authenticated checkpoint policy, or another deterministic rule.
3. Add explicit tests for provider exceptions, clock rollback across reopen/replay, exact future-boundary behavior through persistent replay and coordinated import, and every discovered block/header ingress path.
4. Before public networking, define peer-time sampling, outlier rejection, minimum peer count, maximum permitted network adjustment, and behavior during isolation. The host clock supplied by the current CLI is only a provisional local reference.

No consensus constants or runtime behavior are changed by this audit note. The two-hour future allowance and all other time rules remain proposals pending owner approval and independent review.

## Block-body ingress and reorganization audit (2026-11-26)

The current block-body path is separate from header-time admission:

- Peer header synchronization validates downloaded headers through `HeaderChain.add_batch()` with one adjusted-time sample for the batch. The node runtime passes its configured adjusted-time callback into the P2P sync service; callers that omit it cannot accept peer header batches.
- Normal requested-body admission rejects unsolicited bodies, verifies the requested hash is still on the selected best chain, checks the serialized body header against the exact validated header entry, then delegates to the store's validated connection path.
- `UTXOStore.connect_validated_block()` rechecks the selected best-chain header and active-tip linkage, derives parent MTP from the supplied `HeaderChain`, then invokes transaction/body validation and atomic UTXO persistence.
- Fork-body download verifies the exact known header and Merkle commitment before archiving. The later `reorganize_to_best()` requires a strictly greater-work branch, matches each replacement body to its header, derives MTP from the header DAG, and applies the UTXO switch atomically. Transaction/script validation occurs while connecting replacement blocks; failures roll back the UTXO reorganization.

Focused tests currently cover unsolicited and mismatched bodies, wrong-peer fork responses, invalid Merkle commitments, invalid transaction bodies, atomic reorganization, and rollback on invalid replacement bodies.

### Remaining ingress and recovery gates

1. This is a source-level audit of the inspected public P2P and persistent-state paths, not proof that every import, bootstrap, snapshot, migration, or future API is covered. Inventory all call sites of low-level `connect_block()` and `reorganize()`; those methods explicitly do not authenticate header PoW/difficulty/ancestry themselves.
2. Ensure production-facing code cannot call those low-level storage primitives without a validated header-chain boundary. Add negative tests for each discovered caller and for coordinated-database rollback across header, body archive, UTXO, and recovery-journal writes.
3. Define deterministic replay semantics separately from live future-time admission. The current host-clock callback is provisional and is not a peer-adjusted network-time algorithm.
4. Keep block size, transaction/script subset, retarget timing, network identity, and all other provisional consensus parameters un-frozen until owner approval, complete vectors, an independently maintained implementation, and external review.

This audit note changes documentation only; it does not change consensus or runtime behavior and does not authorize public Testnet/Mainnet launch.

## Integration status

- [x] Injected adjusted-time provider supported by the in-memory header DAG.
- [x] Provider wired through persistent header-store replay and candidate reconstruction, including every existing side-branch header.
- [x] Legacy snapshot-set validation and coordinated staging import accept an explicit provider and replay all headers against one clock sample.
- [x] Provider parameter exposed by persistent node-state constructors.
- [x] P2P header-sync path requires a provider and validates the returned value.
- [x] Loopback node runner passes one provisional local UTC clock to both persistent header replay and live P2P header admission.
- [x] Coordinated persistent-state test covers provider-based admission and replay of a non-genesis header.
- [ ] Production peer-time sampling, outlier policy, trust model and lifecycle wiring.
- [ ] Full migration workflow tests must pass on Python 3.12 and 3.13 after the strict-time changes. The local node's `time.time()` provider is only a provisional testnet clock, not a network-adjusted production source. A first CI regression exposed that the coordinated-import wrapper did not forward the explicit provider; the API and active-genesis test now pass it, and the rerun is pending.
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
