# BLACKROOT genesis trust-anchor governance proposal

**Status: PROPOSAL ONLY. No owner key is configured, no trust anchor is approved, and no genesis issuance or network launch is authorized.**

## 1. Security objective

The detached Ed25519 approval verifier accepts public keys supplied by its caller. Cryptographic verification can establish that a signature matches a supplied public key, but it cannot establish that the key belongs to the project owner or that the key was approved through a legitimate process.

This proposal defines governance evidence required before any public key may be treated as an owner trust anchor. It does not select a real key, identify a key holder, or grant authority to issue BRT.

## 2. Trust-anchor record

A future trust configuration should be a separately versioned, reviewed artifact containing, at minimum:

- configuration schema version;
- target project and network identity;
- monotonically increasing trust-configuration sequence;
- key identifier equal to SHA-256 of the exact 32 raw Ed25519 public-key bytes;
- public key bytes in one canonical encoding;
- permitted approval scopes;
- activation status and effective review decision;
- revocation status and, when revoked, the effective revocation decision;
- predecessor configuration digest, where rotation is used.

The configuration must reject duplicate identifiers, duplicate public keys, unknown fields, malformed encodings, unsupported algorithms, invalid scopes, and ambiguous status transitions. A key identifier is an integrity label, not proof of identity.

## 3. Independent approval of the trust anchor

Before a key is trusted:

1. Generate the signing key in an offline, reviewed environment under the owner's exclusive control. Do not generate it in GitHub Actions, source code, chat, or a hosted repository workflow.
2. Verify the public key fingerprint through an independent channel and record the exact raw public-key bytes.
3. Record the owner's explicit decision to designate that fingerprint for the narrowly scoped `genesis-founder-allocation` approval.
4. Have an independent reviewer verify the configuration, fingerprint, scope, and custody procedure.
5. Publish the trust configuration and its digest through the project's reviewed governance process.
6. Pin the exact approved configuration digest in the release-verification environment independently of the manifest and detached approval package.

A signature package must never be allowed to introduce, replace, or self-authorize its own trust anchor.

## 4. Rotation, revocation, and compromise

- Rotation creates a new trust-configuration version and requires a separately reviewed decision.
- A new key must not silently inherit the old key's authority; its permitted scopes must be explicitly approved.
- Revocation is fail-closed: once the verifier's approved configuration marks a key revoked, signatures from that key are rejected for new activation decisions.
- A compromised key requires stopping pending activation, preserving evidence, publishing a revocation decision, and reviewing every artifact signed by that key.
- Recovery must not depend solely on the compromised key. The project must define an independent owner identity and recovery process before enabling trust.
- Historical verification must preserve the exact trust-configuration version used at the time, while new activation must use the currently approved non-revoked configuration.
- No automatic fallback to an older trust configuration is permitted when the current configuration is missing or invalid.

## 5. Verifier requirements

A production verifier must receive the expected trust-configuration digest from a separately pinned release policy, not from the manifest, approval record, or package checksum index. It must:

1. validate the trust configuration's exact schema and canonical digest;
2. verify the configured network identity and configuration sequence;
3. reject revoked, inactive, unknown, or scope-incompatible keys;
4. recompute the key identifier from raw public-key bytes;
5. verify the detached Ed25519 approval against the validated manifest's network and digest;
6. bind the verification report to the exact trust-configuration digest and manifest digest;
7. fail closed if trust data is unavailable, stale, malformed, or inconsistent.

The current verifier prototype accepts caller-supplied key mappings and a revoked-key set. It snapshots the approval record and trust inputs before checking them, validates every configured key identifier against its exact 32-byte public key (including entries not selected by the current approval), and rejects malformed revoked-key identifiers. This prevents mutable mapping inputs and malformed unused entries from being silently accepted. It still does not parse or authenticate a trust-configuration artifact, enforce sequence numbers, establish key custody, or pin a trust-configuration digest. These remain open implementation and review requirements.

## 6. Separation of decisions

Three separate decisions must remain distinguishable:

- **Key designation:** approval that a public key is an owner-controlled trust anchor for a defined scope.
- **Genesis approval:** a valid detached signature over one exact manifest digest, network identity, and scope.
- **Release authorization:** a separate human decision to launch a specific testnet or mainnet candidate after all technical, operational, security, and legal gates pass.

None of these decisions implies either of the others. In particular, a valid genesis signature is not a public launch authorization.

## 7. Required tests and review

Before implementation is accepted, add tests for:

- altered trust-configuration bytes and digest mismatch;
- duplicate key identifiers and duplicate public keys;
- unknown or unsupported fields and algorithms;
- scope escalation and cross-network substitution;
- inactive, revoked, and unknown keys;
- trust-configuration rollback and sequence downgrade;
- missing trust configuration and unavailable pinned digest;
- key rotation and compromise recovery;
- verification-report binding to the exact trust configuration and manifest.

Require an independent implementation to reproduce public-key identifiers and signature vectors, plus external cryptographic and governance review.

## 8. Stop conditions

Until the trust model is approved and independently reviewed:

- do not add a real owner public key to the repository;
- do not create a real detached approval record;
- do not build or activate a founder genesis output;
- do not initialize production issuance state;
- do not claim that the founder allocation is credited, owned, or spendable;
- do not announce public testnet or mainnet readiness.

Private keys, seed phrases, wallet passwords, and signing secrets must never be requested in chat or committed to source control.
