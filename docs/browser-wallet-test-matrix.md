# BLACKROOT browser-wallet security test matrix

**Status: planned acceptance criteria — no wallet implementation is approved for real funds.**

This matrix is a release gate for the first single-account, test-network-only browser wallet. A test passing in isolation does not replace independent cryptographic review or an end-to-end audit.

## 1. Key generation and custody

| ID | Test | Required result |
|---|---|---|
| KEY-01 | Generate keys only in a secure browser context | Refuse key generation when Web Crypto is unavailable or the page is not a secure context |
| KEY-02 | Entropy source | Use browser Web Crypto; no Math.random, timestamps, UUIDs, or server-generated entropy |
| KEY-03 | Invalid scalar handling | Reject zero and values greater than or equal to the secp256k1 group order; retry using a reviewed library pattern |
| KEY-04 | Public-key derivation | Compressed public key matches independent known-answer vectors |
| KEY-05 | Session lock | Lock clears in-memory secret references as far as the runtime permits and requires re-authentication |
| KEY-06 | No secret persistence | Automated browser inspection finds no private key, seed, passphrase, or decrypted vault in localStorage, sessionStorage, IndexedDB, cookies, URL, logs, or crash payloads |

## 2. Cryptography and dependencies

| ID | Test | Required result |
|---|---|---|
| CRYPTO-01 | Dependency pinning | Exact reviewed versions and integrity hashes are locked; no floating ranges in the release artifact |
| CRYPTO-02 | Reproducible build | Independent clean builds produce byte-identical static assets, or documented deterministic exceptions |
| CRYPTO-03 | Curve operations | All secp256k1 operations are delegated to a maintained, reviewed dependency; no application-owned curve arithmetic |
| CRYPTO-04 | Signature vectors | Valid and invalid ECDSA vectors agree with an independent implementation |
| CRYPTO-05 | Nonce safety | Signing uses the dependency's reviewed deterministic/randomized nonce implementation; no custom nonce code |
| CRYPTO-06 | Dependency audit | Vulnerability and license reports are reviewed and attached to the release evidence |

## 3. Encrypted backup and restore

| ID | Test | Required result |
|---|---|---|
| VAULT-01 | Export format | Versioned envelope includes KDF identifier/parameters, random salt, cipher identifier, fresh nonce, and ciphertext |
| VAULT-02 | Encryption | AES-256-GCM with a fresh random 96-bit nonce; authenticated metadata is bound as additional authenticated data |
| VAULT-03 | Password derivation | PBKDF2-HMAC-SHA-256 parameters are benchmarked on supported phones and have a documented minimum |
| VAULT-04 | Wrong password | Restore fails without exposing plaintext or partial key material |
| VAULT-05 | Tamper detection | Changes to ciphertext, nonce, salt, parameters, or authenticated metadata are rejected |
| VAULT-06 | Round trip | Export then restore reproduces the same public key and address vectors |
| VAULT-07 | Backup UX | User is told that loss of the password/file means loss of access; export requires explicit confirmation |
| VAULT-08 | Plaintext handling | No automatic plaintext file, clipboard write, download, or browser-storage backup is permitted |

## 4. Address and network identity

| ID | Test | Required result |
|---|---|---|
| NET-01 | Network selection | Wallet displays the exact frozen network name and chain identifier |
| NET-02 | Address prefix | Reject unknown or provisional prefixes; no receive address is displayed before identity freeze |
| NET-03 | Checksum and payload | Reject wrong version, wrong payload length, malformed Base58, and invalid checksum |
| NET-04 | Cross-client vectors | Address vectors are reproduced by a separately maintained implementation |
| NET-05 | Network mismatch | Reject node responses and transaction data from a different chain identity |

## 5. Transaction safety (disabled until node API and consensus are frozen)

| ID | Test | Required result |
|---|---|---|
| TX-01 | Construction | Inputs, outputs, fees, change, locktime, and sequence follow the frozen specification |
| TX-02 | Display | Destination, amount, fee, change, and network are shown separately before signing |
| TX-03 | User confirmation | Signing and broadcast require an explicit confirmation of the exact transaction summary |
| TX-04 | Unsupported scripts | Unknown scripts and unsupported sighash modes are rejected |
| TX-05 | Signature verification | Wallet signatures are independently verified by the node and test vectors |
| TX-06 | Broadcast | No broadcast control is enabled until node API, mempool policy, and end-to-end tests pass |

## 6. Browser and release hardening

- Strict Content Security Policy; no inline or remotely hosted executable scripts.
- No analytics, advertising, third-party widgets, remote fonts, or runtime CDN dependencies on the wallet origin.
- Dependency and static-analysis checks run in CI.
- XSS and DOM-injection tests cover every untrusted node/API field.
- No secrets in telemetry, error messages, screenshots, or support bundles.
- Release artifacts are versioned, checksummed, reproducible, and signed through a separately reviewed release process.
- Security review includes mobile browsers and the actual hosting origin, not only unit tests.

## 7. Release decision checklist

- [ ] Network identity and address format frozen and independently reproduced.
- [ ] Cryptographic dependency selected, pinned, audited, and externally reviewed.
- [ ] All KEY, CRYPTO, VAULT, NET and browser-hardening tests pass.
- [ ] Node API and transaction rules frozen before enabling TX tests.
- [ ] Independent security review findings are resolved.
- [ ] Testnet trial and backup/restore drills complete.
- [ ] Explicit release approval recorded.

**Until every applicable gate is satisfied, the wallet remains a non-custodial UI prototype with no real-funds support. Never commit private keys, recovery phrases, passphrases, or decrypted backups to source control.**
