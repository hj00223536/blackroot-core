# Draft BRT issuance schedule

**Status: draft proposal only. Not active consensus and not a launch announcement.**

This document proposes one exact, easily auditable interpretation of the selected 40,000,000 BRT allocation. It still requires the project owner's explicit approval and independent protocol review.

## Supply allocation

| Component | Amount |
|---|---:|
| Founder genesis allocation | 20,000,000 BRT |
| Maximum mining issuance | 20,000,000 BRT |
| Maximum total supply | 40,000,000 BRT |

The founder allocation is intended to be spendable and not time-locked. No founder address or private key is embedded here. The founder output must not be created until a secure wallet produces and verifies the receiving address.

## Draft mining curve

- Fixed block subsidy: **10 BRT** per eligible block.
- Eligible heights: **1 through 2,000,000 inclusive**.
- Number of eligible blocks: 2,000,000.
- Maximum scheduled mining issuance: 2,000,000 × 10 = **20,000,000 BRT**.
- Height 0 has no mining subsidy; the founder allocation is a separate genesis allocation.
- Heights above 2,000,000 have zero scheduled subsidy.
- At a proposed 600-second block interval, 2,000,000 blocks take about 38 years if blocks arrive on schedule.
- Unclaimed or underclaimed subsidy is not carried forward; it remains unissued.
- Transaction fees, if later specified, are transfers of existing BRT and must not increase the supply cap.

## Required consensus enforcement

A production implementation must validate each coinbase against the subsidy and permitted fees, track cumulative issuance without overflow, and reject any block that would exceed the mining allocation or total cap. Genesis serialization must separately prove the founder output and its spendability. Tests must cover the first eligible block, final eligible block, first zero-subsidy block, cumulative issuance, reorg rollback, and independent implementations.

## Important status boundary

The existing `src/blackroot_consensus.py` still contains the previous 21-million-style subsidy constants. The draft helper in `src/blackroot_monetary.py` is intentionally isolated and is not called by block validation. No consensus behavior, genesis block, wallet balance, mining reward, or network activation has changed. Do not use this draft to mine or receive funds until it is approved, integrated, audited, and released.

## Decision requested before integration

Approve or reject the proposed fixed 10 BRT reward for 2,000,000 blocks. A different reward curve changes consensus and must be specified before implementation.
