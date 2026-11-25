# Genesis block status and requirements

**Status: deterministic Testnet v1 candidate vector exists; it is NOT an activated network constant.**

See [testnet-genesis-candidate.md](testnet-genesis-candidate.md) for the exact candidate transaction, header, and hash. The candidate has been checked by the repository's primary encoders and by a separate stdlib-only test that independently reconstructs the bytes and SHA-256d hashes.

That second test is a useful regression cross-check, not an external audit, a separately maintained client, or proof that the candidate parameters are suitable for a public network. The timestamp, coinbase convention, easy proof-of-work limit, and all network settings remain subject to review.

## Remaining decisions before activation

- Review and approve the timestamp and coinbase message convention.
- Decide whether the zero-value OP_RETURN genesis output is the final unspendable-output convention.
- Freeze a unique chain identifier and four-byte P2P message-start value.
- Freeze address encodings, ports, protocol version, payload limits, and peer policy.
- Publish a normative specification for every consensus rule, including retarget boundaries, timestamp policy, block body validation, scripts, and coinbase maturity.
- Build a runnable node CLI that loads only the explicitly selected testnet configuration.
- Verify the exact candidate in a separately maintained client and obtain external consensus/security review.
- Pass a multi-process TCP test in which independently launched nodes verify the same genesis and converge on the same best-chain tip.

## Verification record

| Field | Status |
|---|---|
| Candidate transaction, merkle root, header, and hash | Recorded in candidate document |
| Repository encoder regression test | Passing in CI |
| Separate stdlib-only byte/hash reconstruction | Passing in CI |
| External independent client reproduction | Pending |
| Normative parameter approval | Pending |
| Network identity and P2P settings | Pending |
| Runnable node and multi-process convergence | Pending |

Do not describe this candidate as a launched network genesis. Do not mine public blocks or invite public peers until all activation gates are reviewed and passed.
