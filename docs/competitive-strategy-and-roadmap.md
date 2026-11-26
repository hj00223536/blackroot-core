# BLACKROOT: competitive strategy and measurable launch roadmap

**Purpose:** Build a technically credible, useful, independently verifiable blockchain. This is a product and engineering strategy, not a promise of price, returns, market capitalization, or superiority over Bitcoin.

## Strategic position

BLACKROOT should not compete by claiming to be "the next Bitcoin" or by manufacturing a high unit price. It should earn adoption through measurable properties:

1. **Verifiable monetary policy:** hard maximum of 40,000,000 BRT; 20,000,000 founder genesis allocation and 20,000,000 mining allocation; 10 BRT per block at heights 1–2,000,000.
2. **Security before speed claims:** fully specified consensus, independently reproduced vectors, audited signing and script implementation, adversarial network tests, and public incident handling.
3. **Usability:** secure self-custody wallet, clear fee estimates, human-readable explorer, reliable backups and recovery, accessible documentation.
4. **Real utility:** choose one initial use case and prove repeat usage before expanding. Do not launch a token sale to fund speculative demand.
5. **Transparent governance:** publish upgrade process, release hashes, treasury/founder holdings, mining issuance, and known risks.

## Performance targets are hypotheses, not claims

Before advertising performance, benchmark a reproducible release on named hardware and network conditions. Publish raw scripts and results.

| Metric | Initial engineering target | Required evidence |
|---|---:|---|
| Block interval | 600 seconds target | Observed testnet distribution over at least 30 days |
| Node synchronization | No consensus divergence | Multi-node soak test and reorg scenarios |
| Transaction validation | 100% agreement across independent clients | Shared valid/invalid vector corpus |
| Wallet key safety | No secrets leave device | Threat model, code review, security test |
| Availability | 99.9% testnet node uptime target | Public monitoring and incident log |
| Transaction throughput | No advertised number until measured | Reproducible load test, latency percentiles, hardware disclosure |
| Fees | No fixed fiat promise | Published on-chain fee policy and observed fee market |

## Roadmap and release gates

### A. Prototype correctness
- Complete Python 3.12/3.13 CI for the approved subsidy change.
- Verify every block-body coinbase is capped at subsidy plus valid fees.
- Reconcile all monetary range checks and genesis accounting to 40,000,000 BRT.
- Remove stale 21,000,000/50 BRT/halving references from normative docs and tests.
- Preserve independent genesis/header vectors and add BRT transaction/coinbase vectors.

### B. Local multi-node test network
- Define a versioned network specification and deterministic test genesis.
- Complete validation-before-state-mutation, full block-body synchronization, fork/reorg recovery, and peer abuse limits.
- Run at least three independent nodes for a 30-day soak test with crash/restart and partition simulations.
- Publish testnet explorer, status page, source revision, release checksums, and known limitations.
- Test coins have no monetary value. No deposits or public sale.

### C. Secure wallet and miner
- Implement key generation with a maintained, audited cryptographic library; never use the current experimental custom secp256k1 code for real funds.
- Encrypt wallet backups locally; provide recovery and address-verification tests.
- Add transaction signing and verification vectors across independent implementations.
- Implement mining template, proof-of-work search and submission only after full node validation is complete.
- Do not store seed phrases or private keys in GitHub, logs, support chats, or CI.

### D. Independent review and public testnet
- Obtain independent consensus, cryptography, wallet and network security reviews.
- Run fuzzing, property-based tests, fault injection, denial-of-service tests and multi-client interoperability.
- Publish findings and remediation commits.
- Obtain qualified local legal advice before public distribution or marketing.

### E. Mainnet decision
- Freeze normative protocol, genesis, monetary rules, network identity and upgrade governance.
- Publish reproducible signed builds and operational runbooks.
- Complete backup/restore and incident-response drills.
- Require a separate explicit launch decision after every blocking item is closed.

## Adoption and market integrity

- Do not promise that BRT will reach a specific price or exceed Bitcoin.
- Do not create fake volume, wash trade, fake users, fake partnerships, or misleading exchange claims.
- Do not imply that founder allocation is liquid cash. The founder allocation is a concentrated 50% of the proposed maximum supply and must be disclosed clearly.
- Do not sell or solicit funds based on an unlaunched prototype.
- Measure adoption by active independent users, repeat transactions, independent node operators, application usage, security findings resolved, and uptime—not social-media hype.

## Immediate next engineering tasks

1. Finish and inspect CI for the consensus and block-reward changes.
2. Add a single canonical money-range and issuance test suite.
3. Correct every remaining stale monetary reference in the repository.
4. Specify genesis transaction construction, including founder output spendability and independent verification.
5. Keep testnet launch blocked until node/body sync and security gates are met.

## Current truth

The reference subsidy schedule is integrated into source control, but CI validation is pending. Founder genesis coins do not yet exist as a spendable output. There is no public testnet/mainnet, live BRT balance, exchange listing, cash liquidity, or defensible market price.
