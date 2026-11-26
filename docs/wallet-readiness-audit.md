# BLACKROOT wallet readiness audit

**Audit status: BLOCKED — design and prototype only. No wallet is approved for real funds.**

## Scope and evidence

This review inspected the current repository versions of:

- `docs/browser-wallet-security-plan.md`
- `docs/transaction-script-policy-proposal.md`
- `pyproject.toml`
- `src/blackroot_chain.py`
- `src/blackroot_node.py`
- `src/blackroot_node_runtime.py`
- `src/blackroot_p2p_service.py`
- `src/blackroot_p2p_header_sync.py`

This is a source-level readiness review, not a penetration test, cryptographic audit, or independent consensus review.

## Findings

### W-01 — No wallet implementation or approved key manager

The wallet security plan describes an HTML shell only. The inspected project metadata declares no Python runtime dependencies, and the reviewed source paths do not provide a browser wallet, encrypted vault, local key manager, transaction signer, or wallet release pipeline.

**Impact:** No safe founder wallet can currently be created or used from this repository.

**Required closure:** Implement a browser wallet with reviewed, pinned, locally bundled cryptographic dependencies; add key-generation, encrypted backup/restore, and secret-isolation tests; obtain external review before real funds.

### W-02 — Prototype cryptography must not secure funds

The transaction/script proposal records a hand-written secp256k1/ECDSA prototype and a restricted P2PKH verifier. It has no independent cryptographic audit.

**Impact:** A passing unit test suite does not establish safe private-key generation, signing, or transaction authorization.

**Required closure:** Select a maintained cryptographic library with a documented security history, pin and audit its exact version, add independent known-answer and negative vectors, and commission external review. Do not reuse the prototype arithmetic for wallet secrets or real signatures.

### W-03 — Network identity and address version remain provisional

The current address version byte and network identity have not been frozen. The candidate genesis still has a zero-value OP_RETURN output.

**Impact:** There is no approved mainnet receive address or founder genesis output. The planned founder allocation is not minted or spendable.

**Required closure:** Freeze network identity, serialization, address format, genesis bytes, and transaction/script rules; reproduce them independently before constructing a founder output.

### W-04 — Node clock is local, not network-adjusted

The CLI supplies `int(time.time())` to persistent replay and P2P header admission. The header-sync coordinator requires a clock provider, but the supplied provider is still the local wall clock.

**Impact:** Future-time checks are not yet based on a specified peer-time algorithm or a defended trust model.

**Required closure:** Specify peer sampling, outlier rejection, minimum peer count, local-clock failure behavior, and deterministic replay semantics; test adversarial peer-time inputs.

### W-05 — No production node API or verified balance path

The wallet plan records that no production node RPC/read-only wallet API exists. The reviewed P2P service synchronizes headers and block bodies but is not a wallet API contract.

**Impact:** A wallet cannot safely establish confirmed balance, UTXO ownership, fee estimates, or broadcast status.

**Required closure:** Define an authenticated/read-only node API, validate responses against a trusted node, and add end-to-end wallet-to-node tests before enabling broadcast.

## Release decision

- [x] Record wallet blockers and evidence.
- [ ] Freeze protocol and network identity.
- [ ] Approve independently reviewed wallet cryptography.
- [ ] Implement local-only key custody and encrypted backup/restore.
- [ ] Implement transaction signing against frozen consensus rules.
- [ ] Implement a verified node API and transaction broadcast.
- [ ] Complete independent security and protocol audits.
- [ ] Complete testnet trials and explicit launch approval.

**Decision: Do not create founder keys, publish a receive address, issue the founder allocation, solicit deposits, or announce a mainnet launch at this stage.** Keep private keys and recovery phrases off GitHub, chat, logs, analytics, and support forms.

## What CI proves

Successful Python 3.12/3.13 and Node.js 22 jobs provide regression evidence for the tests they execute. They do not prove cryptographic safety, consensus completeness, production network time, wallet security, market liquidity, or a market price.
