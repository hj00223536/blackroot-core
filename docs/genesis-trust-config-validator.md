# BLACKROOT trust configuration validator prototype

**Status: EXPERIMENTAL VALIDATION ONLY. No trust anchor is approved and no genesis issuance or release is authorized.**

## Data model

Version 1 contains exactly:

- `config_version`: integer 1;
- `network_id`: 32-byte lowercase hexadecimal identifier;
- `sequence`: positive safe integer;
- `previous_config_digest`: null for the first configuration, otherwise the exact digest of the preceding configuration;
- `keys`: non-empty array of exact key records;
- `config_digest`: domain-separated SHA-256 digest over the canonical configuration with this field omitted.

Each key record contains exactly `key_id`, `public_key`, `scopes`, and `status`. The key ID is SHA-256 of the raw 32-byte Ed25519 public key. Only the narrowly scoped `genesis-founder-allocation` scope is accepted. Status is `active` or `revoked`. Duplicate IDs and duplicate public keys are rejected.

## External anti-rollback pins

The validator requires the caller to supply all of the following from a separately reviewed release policy:

- expected network ID;
- pinned configuration digest;
- expected sequence number;
- expected predecessor digest (or null for sequence 1).

The package cannot choose these values. A valid digest without an independently supplied pin is not trusted. Sequence 1 must have a null predecessor and a null externally expected predecessor. Every sequence greater than 1 must contain a canonical 32-byte predecessor digest and the caller must pin that exact digest; a later sequence with a null predecessor pin is rejected. A later configuration must match the exact expected sequence and predecessor digest; older, unlinked, or substituted configurations fail closed.

## Independent digest fixture

The canonical first-configuration fixture uses the published RFC 8032 Ed25519 public test key (not an owner key), network ID `11` repeated 32 times, sequence 1, no predecessor, and the sole `genesis-founder-allocation` scope. Its trust-configuration digest is `157f3c321befaaaf8f9180c90fdb0ed3164ff9e71c070a664e14a7fbad1456ab`. Python regression tests and `scripts/verify_genesis_trust_config.mjs` independently reproduce the value; CI runs the Node.js verifier. This is a format test vector, not a trust anchor or activation artifact.

## Approval-verification binding prototype

`verify_approval_with_validated_trust()` now accepts a structurally validated manifest and a validated trust configuration, rejects cross-network use, and passes only active keys with the exact founder-allocation scope to the detached Ed25519 approval verifier. Revoked keys are explicitly rejected. The validated key mapping is exposed read-only. Regression tests cover successful binding, revoked-key rejection, and cross-network substitution. This is still only a library-level prototype: it does not load or authenticate the external pins, persist anti-rollback state, or authorize issuance.

## Prototype boundary

`src/blackroot_genesis_trust.py` performs strict JSON parsing, exact-field checks, key identifier checks, scope/status checks, canonical digest verification, and comparison against caller-supplied pins. It returns validated public-key records but does not load pins from a secure source, establish owner identity, verify governance decisions, manage time-based activation, persist monotonic state, or integrate with the approval verifier or node startup. A caller could still supply malicious pins; the external pinning and review process is not implemented.

The test public key is RFC 8032 published test material only. It is not an owner key. No real trust configuration is included.

## Required next gates

1. Independently review the schema, canonicalization, domain separation, and rollback semantics.
2. Define and secure the external release-policy pin distribution and update procedure.
3. Define quorum/separation-of-duties, key activation and revocation effective times, and recovery independent of a potentially compromised key.
4. Add independent cross-language digest vectors and fuzzing.
5. Only after owner approval and independent review, consider wiring validated active keys into detached approval verification.

This prototype does not create a founder output, initialize issuance state, or authorize testnet/mainnet release.
