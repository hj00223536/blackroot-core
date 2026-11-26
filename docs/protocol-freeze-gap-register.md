# BLACKROOT protocol-freeze gap register

**Status: OPEN — engineering register only. No testnet or mainnet activation is authorized.**

This register converts the current prototype observations into explicit decisions and evidence required before freezing BLACKROOT consensus. It deliberately does not choose unreviewed consensus values.

## Release-blocking decisions

| ID | Area | Current repository evidence | Required decision/evidence | Status |
|---|---|---|---|---|
| PF-01 | Header serialization | 80-byte header prototype with little-endian integer fields and SHA-256d | Normative byte-level format, version handling, immutable vectors reproduced independently | OPEN |
| PF-02 | Proof of work | Compact-target decoding and PoW checks exist | Freeze PoW limit, canonical compact encoding, target comparison and genesis rules | OPEN |
| PF-03 | First difficulty period | Retarget currently occurs at candidate heights divisible by 2,016; first interval uses parent height 2,015 timestamp minus genesis timestamp | Explicitly approve or change first-period boundary; vectors at heights 2,015–2,017 and reorg cases | OPEN |
| PF-04 | Difficulty arithmetic | Timespan currently clamped to 1/4–4x the nominal 2,016 × 600 seconds; integer division precedes compact encoding. A standalone Node.js 22 verifier now reproduces clamp and first-boundary arithmetic fixtures in CI | Freeze constants, rounding/truncation, limit capping and edge-case vectors; obtain independent external implementation and protocol review | OPEN |
| PF-05 | Time validity | Median of up to 11 parent-chain timestamps; future bound depends on supplied adjusted time and defaults to 7,200 seconds | Specify MTP, mandatory clock provider, peer-time adjustment and identical enforcement at every entry point | OPEN |
| PF-06 | Chain selection | Greatest cumulative work; deterministic raw-hash tie-break for equal work | Freeze tie-break, reorg policy/limits and recovery semantics; cross-client vectors | OPEN |
| PF-07 | Transaction and scripts | Legacy serialization and a limited strict P2PKH/SIGHASH_ALL subset are implemented | Normative transaction format, supported script language, sighash modes, locktime/sequence, coinbase maturity, size and count limits | OPEN |
| PF-08 | Genesis issuance | Current genesis candidate has zero-value OP_RETURN; height-zero mining subsidy is zero | Securely generate founder key outside source control; bind exact 20,000,000 BRT output to fixed genesis identity; verify spendability and serialization independently | OPEN |
| PF-08A | Bootstrap authorization | `add_genesis_output()` is a trusted pre-chain storage primitive; static AST regression tests scan direct references and common literal-string reflection patterns in current `src/*.py` files, but do not create an authorization boundary. Tests now explicitly assert that both existing and zero-valued `bootstrap_issued_sats` counters are not genesis-initialization markers; the counter is mutable accounting metadata, not an issuance ledger. | Replace the primitive with a one-time genesis initializer that verifies an owner-approved immutable manifest and commits genesis identity, exact outputs, an immutable initialization record, and auditable issuance evidence atomically; prove network-facing code cannot acquire its capability | OPEN |

The proposed public manifest format and fail-closed validation requirements are documented in [genesis-manifest-spec.md](genesis-manifest-spec.md). This is a review specification only; no founder output or initializer is implemented.
| PF-09 | Address identity | Base58Check encode/decode vectors pass; version byte 0x26 remains provisional | External prefix-collision review, public-key format decision, checksum and independent cross-client vectors | OPEN |
| PF-10 | P2P identity | Candidate magic and ports are documented as proposals; local prototype listener is loopback-only | Collision review, message framing/limits, handshake compatibility, peer policy and frozen testnet-only identity | OPEN |
| PF-11 | Network configuration | Strict JSON testnet configuration checks explicit values and rejects non-loopback listener hosts | Add configuration schema/version migration policy and define how frozen identity is authenticated and distributed | OPEN |
| PF-12 | Independent implementation | Python tests and independent Node.js vectors run in CI | A separately maintained client or independent external implementation must reproduce final consensus vectors | OPEN |
| PF-13 | Security and operations | Selected SQLite, reorg, process-exit, loopback P2P and CI regressions exist | External protocol/crypto review, fuzzing, fault injection, backup/restore drills, reproducible signed releases and incident runbooks | OPEN |

## Monetary rules already selected (not a launch authorization)

- Founder allocation intended: 20,000,000 BRT, separate from mining subsidy.
- Mining schedule: 10 BRT at each height 1 through 2,000,000 inclusive; zero at height 0 and after height 2,000,000.
- Maximum scheduled mining issuance: 20,000,000 BRT.
- Proposed total ceiling: 40,000,000 BRT.
- Fees are transfers of existing value and are not new issuance.
- Persistent schema-v5 accounting records scheduled active-chain subsidy budgets and trusted bootstrap issuance; this accounting does not itself mint the founder allocation.
- Founder output remains absent. No founder balance, usable receive address, cash liquidity, market price or exchange listing is established.

Difficulty adjustment has a separate [policy proposal](difficulty-adjustment-policy-proposal.md). Its first-boundary convention remains subject to explicit owner approval and independent review.

PF-07 has a detailed [transaction and script policy proposal](transaction-script-policy-proposal.md). The current verifier is a restricted P2PKH prototype, not a complete Script engine, and has not received independent cryptographic review.

## Required evidence package for protocol freeze

1. A versioned normative specification that resolves PF-01 through PF-11.
2. Deterministic genesis, header, transaction, script, address and difficulty vectors, including invalid vectors.
3. Independent reproduction of every frozen vector by a separately maintained implementation.
4. CI results for supported Python versions and the independent implementation, with immutable commit references.
5. External review findings and documented remediation for consensus and cryptography.
6. A testnet-only identity distinct from any future mainnet identity, with an explicit reset policy.

## Safe sequencing

1. Resolve protocol decisions without creating founder key material in GitHub.
2. Complete external prefix and protocol review.
3. Generate the founder key locally in a reviewed wallet implementation only after the identity is frozen; never transmit its private key or recovery phrase.
4. Construct the fixed founder genesis output from the public key/hash only, then independently verify its exact serialization and spendability.
5. Run a private, valueless testnet and complete the remaining testnet gates before considering a public testnet.
6. Treat mainnet as a separate approval decision after security, operational and qualified Iraqi legal review.

## Explicit stop conditions

- Do not use the proposed 0x26 address prefix for real funds.
- Do not publish a public testnet endpoint or mainnet genesis while any required protocol decision remains open.
- Do not claim the founder allocation is minted, credited or spendable until the fixed genesis output is implemented and independently verified.
- Do not promise BRT price, liquidity, buyers, exchange listing or investment returns.
- Never commit private keys, seed phrases, wallet passwords or decrypted wallet backups to GitHub.

## Related records

- [Provisional consensus decisions](consensus-decisions.md)
- [Network identity proposal](network-identity-proposal.md)
- [Testnet launch gates](testnet-launch-gates.md)
- [Mainnet launch gates](mainnet-launch-gates.md)
- [Monetary policy](monetary-policy.md)
- [Browser wallet security plan](browser-wallet-security-plan.md)


- [Time-validity policy proposal](time-validity-policy-proposal.md)
- [Wallet readiness audit](wallet-readiness-audit.md)
- [Browser wallet security test matrix](browser-wallet-test-matrix.md)
- [Browser wallet cryptography dependency decision](browser-wallet-cryptography-decision.md)
- [Trusted bootstrap issuance capability design](bootstrap-issuance-capability-design.md)
