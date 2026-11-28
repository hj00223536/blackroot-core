# Genesis authorization verification contract

**Status: IMPLEMENTATION CONTRACT ONLY. It is not a trust anchor, release approval, or issuance authorization.**

## Purpose

`src/blackroot_genesis_authorization.py` composes three existing checks:

1. Genesis Manifest v2 parsing, canonical digest verification, and comparison with caller-supplied frozen chain/economic constants.
2. Trust-configuration parsing, canonical digest verification, and comparison with caller-supplied network, sequence, predecessor, and external digest pin.
3. Detached Ed25519 approval verification using only an active key in that validated trust configuration, bound to the exact validated manifest digest and network.

The function returns a frozen `VerifiedGenesisAuthorization` evidence summary. It is deliberately not an initializer capability, database handle, spendable output, or permission to launch a network.

## Required external release-policy inputs

The caller must obtain all of the following from a separately governed and independently reviewed release-policy channel. None may be copied from the candidate package being checked:

- expected 32-byte lowercase-hex network ID;
- expected Genesis block hash and independently reproduced coinbase txid;
- frozen founder allocation, total supply cap, maximum mining issuance, and mining schedule identifier;
- exact SHA-256 digest of the approved trust configuration;
- expected trust-configuration sequence number;
- expected predecessor digest (or explicit `null` for the independently approved initial configuration).

The release-policy channel must itself define authentication, access control, review quorum, freshness, rollback prevention, key rotation, revocation, backup, and emergency recovery. A value supplied by an unauthenticated environment variable, package checksum file, Git branch, CI artifact, or the candidate manifest is not an independent trust pin.

## Review and execution procedure

1. Freeze the protocol and monetary constants in a separately reviewed release decision. Do not derive them from the manifest under review.
2. Reproduce the Genesis block hash and coinbase txid with an independently maintained implementation.
3. Verify the trust configuration's owner designation, key custody evidence, sequence, predecessor, revocations, and exact digest through the external governance process.
4. Review the detached approval record and confirm that its signing key is active and authorized for the narrow `genesis-founder-allocation` scope.
5. Run the composed verifier with those independently supplied values in a controlled, reproducible environment.
6. Preserve the exact input artifacts, external pin evidence, verifier version/source revision, output summary, reviewer identities, and timestamps in an auditable release record.
7. Require a separate explicit human release decision for any Testnet or Mainnet action. A successful verification result does not make that decision.

## Fail-closed conditions

Stop if any input or external pin is missing, malformed, stale, ambiguous, or inconsistent; if the trust sequence rolls back; if a predecessor does not match; if a key is inactive or revoked; if the approval signature does not bind the exact manifest; or if independently reproduced Genesis values differ.

Do not fall back to a prior trust configuration, infer a missing digest, silently normalize network IDs, or accept a package-provided checksum as an external pin.

## Explicit non-capabilities

The current composed verifier:

- does not authenticate the source or custody of the caller-supplied release-policy pins;
- does not persist anti-rollback state or securely store trust configuration;
- does not perform independent Genesis mining/reproduction itself;
- does not validate the full consensus protocol or deterministic UTXO replay;
- does not initialize or mutate a node database;
- does not create, credit, or prove ownership of a founder balance;
- does not authorize Testnet, Mainnet, exchange listing, fundraising, or sale of tokens.

The RFC 8032 private key used in tests is a public test vector only. It is not an owner key and must never be promoted into a production trust configuration.

## Closure requirements

Before this contract can be treated as operational:

- [ ] Approve and implement an independently authenticated release-policy source for every external pin listed above.
- [ ] Implement durable anti-rollback state with backup/restore and interrupted-update tests.
- [ ] Establish owner identity, offline key custody, independent fingerprint confirmation, revocation, rotation, and recovery governance.
- [ ] Independently reproduce the exact Genesis block, coinbase transaction, and all frozen monetary/consensus parameters.
- [ ] Bind the verified evidence to a one-time atomic initializer only after separate design review and explicit approval; the initializer must reject altered, replayed, partial, or post-activation attempts without mutation.
- [ ] Complete deterministic UTXO replay, full consensus, independent client, security, operational, and Iraqi legal reviews.
- [ ] Obtain a separate written release decision for the exact candidate digest and network role.

Until every applicable item is completed and independently reviewed, the project remains **NOT READY FOR PUBLIC TESTNET OR MAINNET**.
