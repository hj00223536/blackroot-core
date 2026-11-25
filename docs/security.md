# Security model and release requirements

BLACKROOT is not production-ready. The following risks must be addressed before a public network can safely carry value.

## Consensus and mining risks

- A low-hashrate PoW network can be reorganized by an attacker renting or redirecting sufficient hash power.
- SHA-256d does not itself guarantee decentralization or security.
- Mining concentration, selfish mining, timestamp manipulation, and difficulty-retarget attacks require explicit analysis.
- Chain selection must use a precisely specified cumulative-work rule, not simply the longest chain by block count.

## Node and network risks

- Peer-to-peer parsing must be bounded and fuzz-tested.
- RPC must bind to loopback by default, require authentication for privileged methods, and never be exposed publicly without a hardened gateway.
- Add connection limits, message-size limits, timeouts, peer scoring, and resource quotas.
- Persistent databases must handle crashes, disk-full conditions, and reorganization recovery.
- Releases must be reproducible, signed, and accompanied by checksums and source provenance.

## Wallet risks

- Private keys and seed phrases must be generated locally using a cryptographically secure random source.
- Never send seed phrases or private keys to a server, support agent, website, or chat.
- Backups, restore, address derivation, signature validation, and transaction review require dedicated tests.
- Hardware-wallet support is a later goal, not an existing capability.

## Required assurance

- Independent consensus and cryptography review
- Property-based and fuzz testing
- Cross-implementation consensus test vectors
- Static analysis and dependency review
- Testnet soak period and adversarial testing
- Documented incident response and coordinated disclosure process
