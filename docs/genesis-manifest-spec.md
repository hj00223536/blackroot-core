# BLACKROOT genesis manifest specification

**Status: PROPOSAL ONLY — not frozen, not implemented, and not an issuance authorization.**

This document defines the public review artifact required before a future genesis initializer may create the founder output. It does not select a founder address, create a key, alter the current genesis candidate, or authorize a network launch.

## 1. Purpose and separation of concerns

The manifest binds one reviewed founder allocation to one exact genesis transaction and one exact network identity. It is public consensus/configuration data. It is not a wallet, proof of ownership, private-key backup, or substitute for the project's recorded owner approval.

The current Testnet v1 candidate contains only a zero-value OP_RETURN output. It has no spendable founder output. Do not treat this proposal as changing that candidate.

## 2. Required fields

A future version-1 manifest should contain these fields, with no unknown fields accepted:

| Field | Type | Rule |
|---|---|---|
| `manifest_version` | integer | Exactly `1` |
| `manifest_digest` | 64-char lowercase hex | Digest of every other manifest field under the frozen canonicalization rule below |
| `network_id` | lowercase hex string | Frozen, unique network identifier; must not be a display label |
| `genesis_block_hash` | 64-char lowercase hex | Exact frozen genesis hash in documented display byte order |
| `genesis_coinbase_tx` | lowercase hex | Complete canonical serialized coinbase transaction |
| `founder_output_index` | integer | Zero-based index into the decoded transaction outputs |
| `founder_amount_sats` | integer | Exactly 2,000,000,000,000,000 sats only if the 20,000,000 BRT policy is finally approved |
| `founder_script_pub_key` | lowercase hex | Exact public locking-script bytes at that output |
| `total_supply_cap_sats` | integer | Must match the frozen monetary consensus constant |
| `mining_schedule_id` | lowercase hex string | Digest/identifier of the frozen mining schedule specification |
| `approval_record` | string | Immutable repository release/governance record identifying explicit owner approval |

The amount above is a proposal-level conversion using 100,000,000 atomic units per BRT. It is not an issued balance. A manifest must be rejected if its amount, cap, or schedule disagrees with the frozen consensus rules.

## 3. Canonical digest

Before implementation, the project must freeze a canonical serialization rule. The proposed choice is RFC 8785 JSON Canonicalization Scheme (JCS), UTF-8, with duplicate object keys rejected and no floating-point values.

Compute the manifest identifier as:

`SHA256(UTF8("BLACKROOT-GENESIS-MANIFEST-V1\\0") || JCS(manifest_without_digest))`

The digest field itself is excluded from the hashed object. The exact domain-separation bytes, JCS version, lowercase-hex rules, and test vectors must be frozen before any production code relies on this formula. A digest detects changes; it does not prove who approved the manifest.

## 4. Validation requirements

A future initializer must fail closed unless all checks pass:

1. Parse strictly; reject duplicate keys, unknown fields, malformed hex, non-integers, negative values, and out-of-range output indexes.
2. Decode the coinbase transaction using the consensus transaction decoder and reserialize it byte-for-byte; reject non-canonical encodings.
3. Recompute the transaction ID, Merkle root, and genesis block hash using the frozen consensus rules.
4. Confirm the selected output exists and its value and script bytes exactly match the manifest.
5. Confirm the genesis block hash, network identifier, monetary cap, and mining schedule match the locally frozen network configuration.
6. Confirm the founder output plus the maximum scheduled mining issuance does not exceed the total supply cap.
7. Confirm the approval record exists in the reviewed release/governance history and explicitly approves this exact manifest digest.
8. Confirm the database is genuinely fresh: no blocks, active-chain state, UTXOs, previous initialization marker, bootstrap issuance, or conflicting chain metadata.
9. Commit genesis identity, the exact genesis UTXO set, immutable initialization record, and issuance evidence atomically in one database transaction.
10. On reopen, verify the stored record and genesis data against the same frozen manifest; never reissue or silently repair disagreement.

An exact repeated initialization may be idempotent only when the persisted manifest digest and every committed field match. Any altered manifest, duplicate outpoint, partial legacy database, or mismatch must fail without mutation.

## 5. Security and key handling

- Generate the founder private key locally using a vetted wallet/key-generation implementation, outside GitHub and outside CI.
- Never place private keys, seed phrases, passwords, or signing secrets in the manifest, repository, issues, CI variables, or logs.
- Only the public locking script may be published, after explicit owner review and confirmation that it is the intended receive condition.
- Do not send funds to an address derived from prototype cryptography. The current custom P2PKH verifier is not independently audited and must not protect real funds.
- A public manifest digest is not a signature and does not establish owner identity by itself.

## 6. Required tests before implementation is accepted

- Valid manifest round-trip and deterministic digest vectors.
- Duplicate JSON keys, unknown fields, malformed hex, float values, and non-canonical transaction rejection.
- Wrong network ID, genesis hash, txid/Merkle root, output index, amount, or script rejection.
- Cap and mining-schedule mismatch rejection.
- Missing or unapproved approval record rejection.
- Fresh-database initialization commits all records atomically.
- Exact reopen is idempotent and does not reissue.
- Modified manifest, pre-populated database, duplicate outpoint, and partial initialization fail without mutation.
- Startup integrity checks detect any changed manifest, genesis identity, output, or issuance record.
- Network-facing P2P/RPC/transaction paths cannot invoke the initializer or obtain its capability.

## 7. Activation gate

This proposal remains OPEN until the owner-approved monetary policy, network identity, final genesis transaction, founder public locking script, canonicalization rules, approval record, implementation, independent client vectors, and external security review are complete. Even then, a separate explicit release decision is required before any public testnet or mainnet launch.
