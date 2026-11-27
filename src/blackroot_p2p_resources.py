"""Synchronous, event-loop-local P2P resource reservation primitives.

Transport and application-queue paths can use these primitives when callers
explicitly inject peer and node budgets. They choose no policy limits, provide
no thread/process coordination, and require explicit reservation ownership.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def _positive_limit(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_amount(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


class ResourceBudget:
    """One count-and-byte budget; operations are synchronous and loop-local."""

    def __init__(self, *, max_items: int, max_bytes: int, name: str) -> None:
        _positive_limit("max_items", max_items)
        _positive_limit("max_bytes", max_bytes)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be non-empty text")
        self.name = name
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.items_in_use = 0
        self.bytes_in_use = 0

    def can_reserve(self, *, items: int = 1, byte_count: int = 0) -> bool:
        _non_negative_amount("items", items)
        _non_negative_amount("byte_count", byte_count)
        if items == 0:
            raise ValueError("items must reserve at least one item")
        return (
            self.items_in_use + items <= self.max_items
            and self.bytes_in_use + byte_count <= self.max_bytes
        )

    def _apply(self, items: int, byte_count: int) -> None:
        self.items_in_use += items
        self.bytes_in_use += byte_count

    def _release(self, items: int, byte_count: int) -> None:
        if items > self.items_in_use or byte_count > self.bytes_in_use:
            raise RuntimeError("resource budget accounting underflow")
        self.items_in_use -= items
        self.bytes_in_use -= byte_count


@dataclass(frozen=True)
class _Charge:
    budget: ResourceBudget
    items: int
    byte_count: int


class ResourceReservation:
    """Own a set of atomic budget charges until explicitly released."""

    def __init__(self, charges: tuple[_Charge, ...]) -> None:
        self._charges = charges
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            raise RuntimeError("resource reservation released more than once")
        for charge in self._charges:
            charge.budget._release(charge.items, charge.byte_count)
        self._released = True

    def __enter__(self) -> "ResourceReservation":
        if self._released:
            raise RuntimeError("cannot re-enter a released resource reservation")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def reserve_resources(
    requests: Iterable[tuple[ResourceBudget, int, int]],
) -> ResourceReservation | None:
    """Atomically reserve (budget, item_count, byte_count) across budgets.

    Returns None without changing any budget when any requested capacity is
    unavailable. No await occurs, so this is atomic only within one event loop;
    it is not thread-safe or cross-process coordination.
    """
    charges: list[_Charge] = []
    seen: set[int] = set()
    for budget, items, byte_count in requests:
        if not isinstance(budget, ResourceBudget):
            raise TypeError("each request must name a ResourceBudget")
        if id(budget) in seen:
            raise ValueError("a budget may appear only once per reservation")
        seen.add(id(budget))
        if not budget.can_reserve(items=items, byte_count=byte_count):
            return None
        charges.append(_Charge(budget, items, byte_count))
    if not charges:
        raise ValueError("at least one budget request is required")
    for charge in charges:
        charge.budget._apply(charge.items, charge.byte_count)
    return ResourceReservation(tuple(charges))
