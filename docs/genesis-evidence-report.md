# Genesis evidence verification report

**Status: PROTOTYPE ONLY. A passed report is not a release authorization.**

The prototype in `src/blackroot_genesis_evidence_report.py` combines three already separate validation steps:

1. A caller supplies a `ValidatedGenesisManifest` produced by the applicable manifest validator.
2. A caller supplies a `ValidatedTrustConfiguration` produced after checking its digest, network, sequence, predecessor and an independently pinned digest.
3. The detached Ed25519 approval is verified against the active, scoped key from that validated trust configuration.

The resulting deterministic report records the manifest digest and Genesis block hash, trust-configuration digest and sequence, and approval key identifier. It explicitly records that consensus validation, database initialization, issuance and public release authorization were not performed.

## Important limits

- The report is an evidence summary, not a consensus or proof-of-work validator.
- A digest pin and sequence supplied by a caller are only as trustworthy as the external process that supplies them.
- The prototype does not prove who controls a public key or whether the trust policy was approved by the owner.
- It does not initialize a database, create UTXOs, issue founder coins, start a node, or authorize Testnet/Mainnet.
- The JSON serializer is deterministic for the report fields; it is not a signed report and does not provide tamper evidence by itself.
- Test signing material is public RFC 8032 test material only and must never be used for real funds.

Before any release use, the trust-anchor governance, manifest format, approval record, consensus rules, independent review, and a separate human release decision must all be completed. Do not treat `verification_result: passed` as permission to issue or launch.
