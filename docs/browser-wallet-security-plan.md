# BLACKROOT BRT Browser Wallet — Security and Implementation Plan

Status: design only; not a usable wallet and not approved for mainnet funds.

## User requirement

The founder wants a browser-based wallet that can be opened on a phone without a terminal. The owner-approved monetary design is 20,000,000 BRT for the founder and 20,000,000 BRT for mining, with a proposed 40,000,000 BRT maximum supply. The reference subsidy helper now represents the 20,000,000 BRT founder issuance allowance at genesis height 0 and 10 BRT mining rewards at heights 1–2,000,000. CI validation is pending.

## Current blockers verified in the repository

- The repository has an Arabic HTML wallet shell, but no browser wallet application, secure key manager, encrypted vault, transaction signer, or production wallet build pipeline.
- The current testnet genesis candidate still has a zero-value OP_RETURN output. It does not create the founder allocation and cannot pay the founder.
- Address version 0x26 is provisional and must not be used to receive real funds.
- The current custom secp256k1 implementation is experimental and is not an independently audited wallet cryptography library.
- No production node RPC, public testnet, or mainnet exists.

## Security requirements for the browser wallet

1. Private keys and recovery material must be generated and used only in the browser's local execution context.
2. Private keys, seed phrases, passphrases, and decrypted wallet material must never be sent to a server, API, analytics service, GitHub, issue tracker, or ChatGPT.
3. The wallet must not load cryptographic code from a runtime CDN. Dependencies must be pinned, reviewed, bundled into the released application, and covered by reproducible build checks.
4. Use a maintained, reviewed secp256k1 implementation and hash implementation; do not copy the repository's custom curve arithmetic into the wallet.
5. Do not generate a mainnet key or display a receive address until the network's address version, checksum, key format, and chain identity are frozen and tested against independent vectors.
6. A wallet must clearly show the active network (development/test/main), chain identifier, and whether it is connected to a trusted node.
7. No balance or transaction status may be fabricated. Until a functioning node API exists, show “not connected” rather than a guessed zero or cached balance.
8. Provide encrypted export/import only after a reviewed key-derivation and encryption design, and warn users to keep offline backups. Never auto-save plaintext keys to browser storage.
9. Never ask the founder to paste a private key or recovery phrase into a chat, GitHub, or support form.
10. A mainnet release requires an independent security review, dependency audit, browser-origin review, and end-to-end tests.

## Implementation sequence

- [ ] Freeze chain identity and address encoding (network magic, address prefix/version, checksum, public-key format, ports, protocol version).
- [x] Record the owner-approved 40,000,000 BRT monetary ceiling and exact 20,000,000 BRT mining emission schedule in the reference implementation; CI and full integration review remain pending.
- [ ] Implement and test founder genesis output construction and spendability. The current genesis candidate remains zero-value OP_RETURN.
- [ ] Implement and test address encode/decode with independent test vectors.
- [ ] Add a browser app with pinned, bundled cryptographic dependencies and no secret-bearing network requests.
- [ ] Add local key creation, receive-address display, encrypted backup, and restore tests.
- [ ] Implement transaction construction and signing against the final consensus transaction format.
- [ ] Implement a read-only node API and verify balances/UTXOs against node data.
- [ ] Add transaction broadcast only after full-node validation and mempool policy are complete.
- [ ] Complete external review and testnet trials before any mainnet use.

## Explicit non-claims

This plan does not mean a founder wallet exists, that 20,000,000 BRT have been minted or credited, that a balance exists, or that BLACKROOT mainnet is live. It does not provide market liquidity or a market price.
