# Mainnet launch gates

A public mainnet must not be announced until every mandatory gate is met.

- [ ] Complete normative protocol specification
- [ ] Complete full-node implementation and independent implementation review
- [ ] Genesis parameters reproduced by at least two independent implementations
- [ ] Consensus test vectors for valid and invalid blocks/transactions
- [ ] Difficulty-retarget and chainwork tests
- [ ] Persistent UTXO database, crash recovery, and reorg tests
- [ ] Coinbase maturity with persisted creation-height/coinbase provenance and safe schema migration (see docs/coinbase-maturity.md)
- [ ] P2P protocol fuzzing and DoS protections
- [ ] Wallet key generation, signing, backup, and restore review
- [ ] RPC authentication and safe network defaults
- [ ] Reproducible builds, signed binaries, checksums, and release process
- [ ] Independent security audit with findings resolved
- [ ] Public testnet operated long enough to expose operational failures
- [ ] Multiple independent miners and node operators
- [ ] Written legal assessment for each jurisdiction and each planned activity
- [ ] Public disclosure of premine (currently proposed as zero), allocations, and governance
- [ ] Emergency response, upgrade, and vulnerability disclosure policies

A website, repository, genesis block, or successful local mining demo does not by itself constitute a safe or launched cryptocurrency.
