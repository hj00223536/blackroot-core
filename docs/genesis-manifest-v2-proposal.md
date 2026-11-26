# BLACKROOT Genesis manifest v2 proposal

**Status: DESIGN PROPOSAL ONLY. Not frozen, not accepted by the current v1 validator, and not an issuance or launch authorization.**

## 1. Why a v2 format is proposed

The current v1 manifest contains an `approval_record` string. That field is only a non-empty reference and is not cryptographic approval. The detached Ed25519 verifier now exists as a prototype, but it is intentionally separate from the structural manifest validator.

A v2 format should make this separation explicit rather than pretending that a text reference is approval.

## 2. Proposed v2 manifest fields

The proposed v2 manifest retains the consensus-critical fields from v1 and changes the approval representation:

- `manifest_version`: exactly integer `2`.
- `manifest_digest`: domain-separated digest of every other manifest field.
- `network_id`, `genesis_block_hash`, `genesis_coinbase_tx`.
- `founder_output_index`, `founder_amount_sats`, `founder_script_pub_key`.
- `total_supply_cap_sats`, `mining_schedule_id`.

The v2 manifest **does not contain** an approval signature, signature hash, approval-record hash, URI, or mutable repository reference. This avoids circular hashing: the owner signs the already-computed manifest digest in a separate detached approval record.

The current v1 required-field set and validator remain unchanged until an explicit migration is designed, reviewed, and tested.

## 3. Detached approval record

The detached record uses the exact field set and Ed25519 message defined in [genesis-approval-record-spec.md](genesis-approval-record-spec.md). It must bind:

- the exact v2 `network_id`;
- the exact v2 `manifest_digest`;
- the fixed `genesis-founder-allocation` scope;
- a signing key identifier found in separately pinned trust configuration.

The approval record is distributed alongside the manifest as part of a reviewed activation package. The package may contain a checksum index, but the checksum index is not a substitute for the signature or trust anchor.

## 4. Required validation sequence

1. Parse the v2 manifest strictly and reject unknown/missing fields, duplicate keys, floats, malformed encodings, and non-canonical values.
2. Recompute the v2 manifest digest.
3. Validate all network, genesis transaction, founder output, supply, and mining schedule fields against independently frozen constants.
4. Validate the 80-byte header, Merkle commitment, proof of work, and all remaining consensus rules using the final independent client.
5. Parse the detached approval JSON strictly.
6. Verify the detached signature using a public key pinned in separately reviewed trust configuration; never accept a trust anchor supplied only by the manifest or approval record.
7. Confirm the approval record's network ID and digest exactly match the validated v2 manifest.
8. Require a separate human release approval after independent review. Cryptographic owner approval alone does not authorize a public launch.
9. Only a separately reviewed one-time initializer may write genesis state, atomically, after all preceding checks and fresh-database checks pass.

The current helper `verify_validated_genesis_manifest_approval()` implements only step 6/7's prototype signature-binding portion. It does not implement steps 1–5, 8, or 9 and is not called automatically by node startup.

## 5. Migration and compatibility

- Do not reinterpret v1 manifests as v2.
- Do not silently add/remove fields or change the digest domain under the same version.
- Publish fixed v1 and v2 test vectors and cross-language canonicalization tests.
- Decide whether v1 is permanently rejected for production or supported only for historical fixtures.
- Require an explicit protocol decision and migration note before changing the production parser.
- No database migration or genesis output is part of this proposal.

## 6. Acceptance gates

This proposal remains OPEN until:

- the owner approves the v2 field set and digest domain;
- monetary and network constants are frozen;
- independent Python and non-Python implementations reproduce valid and invalid vectors;
- the trust-anchor fingerprint, custody, revocation, rotation, and recovery procedures are reviewed;
- external protocol and cryptographic review is complete;
- the v2 validator and initializer are implemented and tested separately;
- the testnet and mainnet release gates are independently satisfied.

No owner key is configured, no real approval record exists, no founder output is created, and no network launch is authorized by this document.
