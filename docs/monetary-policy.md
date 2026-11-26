# BLACKROOT BRT monetary policy

**Status: owner-approved monetary schedule; consensus integration is being tested. Network activation is not authorized.**

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

Height 0 has no mining subsidy. The founder allocation is a separate genesis output and must not be counted as mining rewards. Unclaimed subsidy is not carried forward. Fees transfer existing value and do not increase supply.

## Consensus enforcement

The reference block validator calculates the coinbase ceiling as the height subsidy plus transaction fees. Because each valid height has one accepted block and the subsidy is fixed only for heights 1 through 2,000,000, scheduled mining issuance cannot exceed 20,000,000 BRT on a single valid chain. The 40,000,000 BRT money range is used for transaction/output range checks.

Genesis construction must separately create and prove the 20,000,000 BRT founder output. It is not yet present in the current genesis candidate. No private key or receiving address is stored in source control.

## Remaining launch gates

- Implement the founder genesis output after a secure wallet has generated and independently verified a receiving address.
- Publish independent transaction/genesis vectors and verify founder output spendability.
- Complete P2P, full-node, consensus, script, security, and operational review.
- Do not claim a live network, wallet balance, market price, exchange listing, or liquidity before independently verified deployment.
