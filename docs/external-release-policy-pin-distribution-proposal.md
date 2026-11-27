# BLACKROOT external release-policy pin distribution proposal

**Status: PROPOSAL ONLY. No distribution mechanism, release key, quorum, operator, or trust authority is approved. This document does not authorize trust activation, Genesis issuance, Testnet, or Mainnet.**

## 1. Purpose

The trust-configuration validator compares a candidate configuration with caller-supplied expected values. The caller-supplied values are only useful if their origin, freshness, integrity, and rollback behavior are independently established.

This proposal defines the minimum properties an external release-policy pinning system must provide. It deliberately does not select a provider or cryptographic protocol.

## 2. Security boundary

The external policy must be controlled independently of:

- the node data directory and its backups;
- the candidate trust configuration being evaluated;
- the detached Genesis approval being evaluated;
- peer-to-peer messages and blockchain state;
- ordinary application configuration writable by the node process.

A value copied from the local database, local filesystem, peer, manifest, or approval record is not an independent pin.

The external policy is an authorization input, not a convenience cache. If it cannot be authenticated or its freshness cannot be established, trust-dependent startup and issuance must fail closed.

## 3. Minimum policy payload

A future versioned policy payload should bind, at minimum:

- policy schema and canonicalization version;
- project identifier and exact network identifier;
- policy sequence number;
- exact trust-configuration sequence and digest;
- exact predecessor trust-configuration digest (null only for the first configuration);
- permitted purpose/scope, initially limited to trust-configuration acceptance;
- issue time and explicit validity/freshness rules;
- policy signer/key-set identifier and required approval threshold;
- policy revocation/recovery reference;
- a domain-separated digest of the canonical payload.

The policy must not contain private keys, wallet secrets, seed phrases, or signing credentials. It must not silently grant Genesis issuance, founder allocation, software release, or network activation authority.

## 4. Authentication and separation of duties

Before implementation, governance must decide and independently review:

1. who may propose a policy update;
2. who may approve it, and the required quorum;
3. whether proposer and approvers must be distinct;
4. how signer identities and public keys are established;
5. how keys are rotated, revoked, recovered, and audited;
6. how emergency suspension works without allowing a compromised signer to roll policy backward;
7. how policy updates are independently witnessed and published.

A signature proves control of a key; it does not by itself prove that the key belongs to the intended owner or that the policy is legitimate. A test key or repository-embedded key is not an owner trust anchor.

## 5. Freshness and anti-rollback

Authenticity alone is insufficient. The verifier must establish that a policy is current according to a separately governed freshness mechanism.

The design must define:

- monotonic policy sequence semantics;
- how the verifier learns the latest expected sequence or digest independently;
- how stale but correctly signed policies are rejected;
- how network partitions and unavailable pin services are handled;
- how expiry is interpreted when the local clock is wrong;
- how recovery proceeds if the latest policy is lost or its signers are compromised;
- how a full local backup restore is detected.

A locally persisted highest sequence is useful for detecting ordinary downgrade attempts but cannot, by itself, detect restoration of an older complete data-directory snapshot. A separately administered pin, independently verifiable transparency log, or validated hardware monotonic mechanism may be considered; none is selected here.

## 6. Candidate distribution models

| Model | Potential benefit | Required independent review |
|---|---|---|
| Separately controlled deployment/release policy | Operationally simple; policy can be pinned outside node storage | Access control, deployment compromise, freshness, operator separation, rollback of deployment configuration |
| Append-only transparency service | Publicly auditable history and consistency proofs | Log operator trust, witness diversity, split-view detection, proof verification, availability and recovery |
| Hardware-backed monotonic state | Can resist some local snapshot rollback attacks | Actual platform guarantees, provisioning, portability, device replacement, recovery, attestation and failure behavior |
| Combined model | Can reduce dependence on one control | Explicit composition rules; no assumption that combining weak controls creates a strong one |

No model should be accepted solely because it is convenient or signed. The selected design must state its adversary assumptions and demonstrate the claimed properties.

## 7. Verifier contract

A future verifier should accept only a structured result produced by an authenticated policy-verification layer, not arbitrary caller-provided integers or digests.

The acceptance decision must bind the policy to the exact project, network, trust-configuration digest, sequence, predecessor, scope, and freshness evidence. It must reject:

- unknown schema or canonicalization versions;
- duplicate or ambiguous fields;
- non-canonical encodings;
- wrong project or network;
- unapproved scope;
- invalid signatures or insufficient quorum;
- stale, expired, revoked, or superseded policy;
- sequence rollback or same-sequence digest substitution;
- missing predecessor linkage;
- missing, unverifiable, or inconsistent freshness evidence.

The verifier must not fetch replacement policy from peers or silently fall back to local state when verification fails.

## 8. Required test programme

Before production acceptance, add independent test vectors and adversarial tests for:

- canonical payload and domain-separated digest across independent implementations;
- signature and quorum threshold boundaries;
- wrong project/network/scope substitution;
- stale signed policy and sequence downgrade;
- same-sequence policy substitution;
- missing, malformed, expired, revoked, or unavailable policy;
- inconsistent predecessor links;
- transparency inclusion and consistency failures, if selected;
- external pin rollback after restoring an old node backup;
- wrong local clock and time-source failure;
- key rotation, revocation, emergency suspension, and recovery;
- concurrent policy updates and crash interruption;
- fail-closed behavior at every startup and issuance boundary.

Tests must not use published cryptographic test keys as production trust anchors.

## 9. Decision record required before implementation

The owner and independent reviewers must explicitly approve:

- the selected distribution model and threat model;
- policy schema and canonicalization;
- signer identity, quorum, and separation-of-duties rules;
- freshness and anti-rollback source;
- key rotation, revocation, emergency recovery, and audit process;
- operational ownership, availability objectives, and incident procedures;
- independent implementation and test plan.

Until that decision record exists, implementation must not invent an owner identity, embed a trusted key, or treat a locally stored value as an authoritative external pin.

## 10. Stop conditions

This proposal is not an implementation or security audit. No real owner key or release-policy pin is configured. Do not activate a trust anchor, create a founder allocation, initialize production issuance, or announce public Testnet/Mainnet readiness on the basis of this document.
