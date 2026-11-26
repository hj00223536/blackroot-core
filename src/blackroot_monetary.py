"""Proposed BLACKROOT monetary schedule; NOT active consensus rules.

This module is deliberately isolated from blackroot_consensus.py. The proposed
schedule requires explicit protocol approval and integration before activation.
"""
from __future__ import annotations

COIN = 100_000_000
FOUNDER_ALLOCATION = 20_000_000 * COIN
MINING_ALLOCATION = 20_000_000 * COIN
TOTAL_SUPPLY_CAP = FOUNDER_ALLOCATION + MINING_ALLOCATION
PROPOSED_BLOCK_SUBSIDY = 10 * COIN
FIRST_MINING_HEIGHT = 1
LAST_MINING_HEIGHT = 2_000_000


def proposed_block_subsidy(height: int) -> int:
    """Return the draft fixed subsidy for heights 1..2,000,000, else zero."""
    if not isinstance(height, int) or isinstance(height, bool) or height < 0:
        raise ValueError("height must be a non-negative integer")
    if FIRST_MINING_HEIGHT <= height <= LAST_MINING_HEIGHT:
        return PROPOSED_BLOCK_SUBSIDY
    return 0


def proposed_mining_issuance_through_height(height: int) -> int:
    """Return the maximum scheduled mining issuance through an inclusive height."""
    if not isinstance(height, int) or isinstance(height, bool) or height < 0:
        raise ValueError("height must be a non-negative integer")
    eligible_blocks = max(0, min(height, LAST_MINING_HEIGHT) - FIRST_MINING_HEIGHT + 1)
    return eligible_blocks * PROPOSED_BLOCK_SUBSIDY


def proposed_total_supply_cap() -> int:
    """Return the draft founder plus mining cap in atomic units."""
    return TOTAL_SUPPLY_CAP
