"""Coinbase maturity rule primitives.

This module defines the proposed consensus boundary independently of storage.
It is not yet wired into block validation or the SQLite UTXO state transition.
"""
from __future__ import annotations

from dataclasses import dataclass

COINBASE_MATURITY = 100


@dataclass(frozen=True)
class UTXOProvenance:
    """Authenticated creation metadata required to enforce coinbase maturity."""

    created_height: int
    is_coinbase: bool

    def __post_init__(self) -> None:
        if (not isinstance(self.created_height, int)
                or isinstance(self.created_height, bool)
                or self.created_height < 0):
            raise ValueError("created_height must be a non-negative integer")
        if not isinstance(self.is_coinbase, bool):
            raise TypeError("is_coinbase must be a bool")


def validate_coinbase_maturity(
    provenance: UTXOProvenance,
    spending_height: int,
    maturity: int = COINBASE_MATURITY,
) -> None:
    """Raise ValueError when a coinbase UTXO is spent before it matures.

    With maturity 100, an output created at height 0 is spendable starting
    in block 100. The caller must supply authenticated provenance from the
    active branch; missing metadata must never be guessed.
    """
    if not isinstance(provenance, UTXOProvenance):
        raise TypeError("authenticated UTXO provenance is required")
    if (not isinstance(spending_height, int)
            or isinstance(spending_height, bool)
            or spending_height < 0):
        raise ValueError("spending_height must be a non-negative integer")
    if (not isinstance(maturity, int) or isinstance(maturity, bool)
            or maturity < 0):
        raise ValueError("maturity must be a non-negative integer")
    if spending_height < provenance.created_height:
        raise ValueError("UTXO cannot be spent before its creation height")
    if provenance.is_coinbase and spending_height - provenance.created_height < maturity:
        raise ValueError("premature coinbase spend")
