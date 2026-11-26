"""BLACKROOT BRT monetary rules selected by the project owner.

The fixed mining schedule is now the reference subsidy schedule used by
blackroot_consensus.block_subsidy. Founder genesis issuance remains a separate
genesis-construction task and is not minted by this module.
"""
from __future__ import annotations

COIN = 100_000_000
FOUNDER_ALLOCATION = 20_000_000 * COIN
MINING_ALLOCATION = 20_000_000 * COIN
TOTAL_SUPPLY_CAP = FOUNDER_ALLOCATION + MINING_ALLOCATION
MAX_MONEY = TOTAL_SUPPLY_CAP

BLOCK_SUBSIDY = 10 * COIN
FIRST_MINING_HEIGHT = 1
LAST_MINING_HEIGHT = 2_000_000


def block_subsidy(height: int) -> int:
    """Return the consensus-selected subsidy for a non-negative block height."""
    if not isinstance(height, int) or isinstance(height, bool) or height < 0:
        raise ValueError("height must be a non-negative integer")
    if FIRST_MINING_HEIGHT <= height <= LAST_MINING_HEIGHT:
        return BLOCK_SUBSIDY
    return 0


def mining_issuance_through_height(height: int) -> int:
    """Return the maximum scheduled mining issuance through an inclusive height."""
    if not isinstance(height, int) or isinstance(height, bool) or height < 0:
        raise ValueError("height must be a non-negative integer")
    eligible_blocks = max(0, min(height, LAST_MINING_HEIGHT) - FIRST_MINING_HEIGHT + 1)
    return eligible_blocks * BLOCK_SUBSIDY


def total_supply_cap() -> int:
    """Return the total founder-plus-mining supply ceiling in atomic units."""
    return TOTAL_SUPPLY_CAP
