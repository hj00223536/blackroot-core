# BLACKROOT monetary policy

## Units

- 1 BROOT = 100,000,000 atomic units.
- Initial subsidy = 5,000,000,000 atomic units (50 BROOT).
- Subsidy halves every 210,000 blocks using integer division by powers of two.
- Subsidy becomes zero after 64 halvings.

## Formula

For block height h:

    halvings = floor(h / 210000)
    subsidy_atomic = floor(5000000000 / 2^halvings)

The reference implementation uses a right shift on the integer atomic-unit subsidy, giving deterministic truncation.

## Supply ceiling

The protocol ceiling is 2,100,000,000,000,000 atomic units (21,000,000 BROOT). Because each subsidy is rounded down to whole atomic units at every halving, the sum of scheduled subsidies is slightly below the ceiling. Fees transfer existing value and do not create new supply.

A full node must reject any block whose coinbase claims more than the allowed subsidy plus fees, and must maintain a supply-accounting invariant. The prototype helper calculates scheduled subsidy only; it does not validate coinbase transactions or total chain issuance.

## Not specified yet

- Whether any tail emission exists (current proposal: no)
- Fee policy and relay minimums
- Coinbase maturity
- Monetary policy change process

Changes to the emission schedule after mainnet launch would be a consensus change and require broad public review.
