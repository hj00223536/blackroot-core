# Browser wallet cryptography dependency decision

Status: decision record — implementation remains blocked; no cryptographic dependency is installed by this document.

## Decision

Do not implement wallet key generation, signing, or encrypted-vault code yet. The repository has no browser application build manifest or lockfile, and its current static `web-wallet/index.html` is only a non-functional status page. Selecting a package name without a reproducible build, pinned transitive dependency graph, and independent review would create a false impression of wallet readiness.

The wallet implementation contract remains authoritative: use a maintained secp256k1 implementation; do not reuse custom curve/ECDSA code from the node prototype; bundle reviewed dependencies locally; do not load crypto code from a CDN.

## Candidate evaluation gate

Before selecting a dependency, a dedicated browser-app change must:

1. Establish the supported browser targets and a reproducible build toolchain.
2. Evaluate a maintained secp256k1 library and its hash dependency for API suitability, maintenance, security advisories, license, and transitive dependency footprint.
3. Pin exact direct and transitive versions in a committed lockfile; document the reviewed release and advisory-check date.
4. Verify that private-key generation uses browser Web Crypto entropy in a secure context, while curve operations use the selected library.
5. Add independent known-answer vectors for compressed public keys, HASH160/address derivation, deterministic signatures, and signature verification.
6. Add negative tests for malformed keys, invalid signatures, wrong network identifiers, and tampered encrypted backups.
7. Verify production bundles contain no runtime CDN imports, analytics, secret-bearing network calls, or accidental console logging.
8. Obtain independent cryptographic review before enabling real-value use.

## Explicit exclusions

- Do not write custom secp256k1, ECDSA, nonce-generation, or signature-parsing code.
- Do not generate or commit a founder private key, seed, or wallet file.
- Do not expose a receive address while network identity and address prefix remain provisional.
- Do not enable transaction signing or broadcasting before transaction consensus and node API rules are frozen.
- Do not claim that the founder allocation exists or is spendable.

## Exit criteria

This decision record can be replaced by an implementation decision only when the browser build system, exact dependency versions, audit evidence, independent vectors, and test results are committed and reviewed. Until then the correct state is **wallet cryptography not yet selected**.
