# BLACKROOT BRT monetary policy

**Status: owner-approved monetary schedule; reference tests pass, but consensus integration is not production-ready. Network activation is not authorized.**

## Units and allocations

- 1 BRT = 100,000,000 atomic units.
- Founder genesis allocation: 20,000,000 BRT, intended to be spendable and not time-locked.
- Maximum mining allocation: 20,000,000 BRT.
- Maximum total supply: 40,000,000 BRT.

## Mining formula

For block height h:

    subsidy(h) = 10 BRT, when 1 <= h <= 2,000,000
    subsidy(h) = 0 BRT, otherwise

There are exactly 2,000,000 eligible mining heights. The maximum scheduled mining issuance is therefore exactly 20,000,000 BRT. At the proposed 600-second target spacing, that is approximately 38 years if blocks arrive on schedule.

Height 0 has no mining subsidy: `block_subsidy(0)` returns zero. The 20,000,000 BRT founder allocation is a separate intended genesis output, not a block reward. The current genesis candidate still has a zero-value OP_RETURN output, so no founder allocation has been issued. A future founder output must be bound to one exact, frozen genesis transaction and hash and validated separately from ordinary block coinbase subsidy rules. Unclaimed subsidy is not carried forward. Fees transfer existing value and do not increase supply.

## Consensus enforcement

The reference block validator calculates the ordinary coinbase ceiling as the mining subsidy plus transaction fees; at height 0 this ceiling is zero. Genesis founder issuance is not currently implemented. When implemented, it must be validated by exact fixed-genesis identity and transaction/output vectors, never by the ordinary coinbase subsidy helper. The mining schedule limits scheduled mining issuance to 20,000,000 BRT on a single valid chain. The 40,000,000 BRT money range is used for transaction/output range checks.

Genesis construction must separately create and prove the 20,000,000 BRT founder output. It is not yet present in the current genesis candidate. No private key or receiving address is stored in source control.

## Remaining launch gates

- Implement the founder genesis output after a secure wallet has generated and independently verified a receiving address.
- Publish independent transaction/genesis vectors and verify founder output spendability.
- Complete P2P, full-node, consensus, script, security, and operational review.
- Do not claim a live network, wallet balance, market price, exchange listing, or liquidity before independently verified deployment.
