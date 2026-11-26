"""BLACKROOT BRT monetary rules selected by the project owner.

The founder allocation is a separate, one-time genesis output. It is not a
block subsidy. The mining schedule applies only to heights 1 through 2,000,000.
A founder output is not implemented in the current genesis candidate.
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
    """Return mining subsidy only; genesis founder issuance is not a block reward."""
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
