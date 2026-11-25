"""Policy-filtered, bounded in-memory peer address book.

This stores candidate endpoints only. It never connects to, trusts, or relays
an address automatically. The default policy accepts only globally routable
unicast IPs and rejects stale or implausibly future-dated records.
"""
from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .blackroot_p2p_addr import PeerAddress

DEFAULT_MAX_ENTRIES = 10_000
DEFAULT_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_FUTURE_SKEW_SECONDS = 10 * 60


def is_eligible_address(address: PeerAddress) -> bool:
    """Return whether an endpoint uses a globally routable unicast IP."""
    if not isinstance(address, PeerAddress):
        return False
    ip = address.ip
    return bool(ip.is_global and not ip.is_multicast and not ip.is_unspecified)


@dataclass(frozen=True)
class AddressBookEntry:
    address: PeerAddress
    last_seen: int
    source: str


class PeerAddressBook:
    """Bounded address book with freshness checks and endpoint deduplication."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        future_skew_seconds: int = DEFAULT_FUTURE_SKEW_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        for name, value in (
            ("max_entries", max_entries),
            ("max_age_seconds", max_age_seconds),
            ("future_skew_seconds", future_skew_seconds),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if max_entries < 1 or max_age_seconds < 1:
            raise ValueError("max_entries and max_age_seconds must be positive")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.max_entries = max_entries
        self.max_age_seconds = max_age_seconds
        self.future_skew_seconds = future_skew_seconds
        self._clock = clock
        self._entries: dict[tuple[str, int], AddressBookEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[AddressBookEntry, ...]:
        """Return entries in deterministic endpoint order."""
        return tuple(self._entries[key] for key in sorted(self._entries))

    def add(
        self,
        address: PeerAddress,
        *,
        source: str,
        now: int | None = None,
    ) -> bool:
        """Add or refresh one eligible endpoint; return whether it was accepted."""
        if not isinstance(address, PeerAddress):
            raise TypeError("address must be a PeerAddress")
        if not isinstance(source, str) or not source or len(source) > 128:
            raise ValueError("source must be non-empty text of at most 128 characters")
        current = int(self._clock()) if now is None else now
        if not isinstance(current, int) or isinstance(current, bool) or current < 0:
            raise ValueError("now must be a non-negative integer")
        if not is_eligible_address(address):
            return False
        if address.timestamp > current + self.future_skew_seconds:
            return False
        if current - address.timestamp > self.max_age_seconds:
            return False

        key = address.endpoint
        existing = self._entries.get(key)
        if existing is not None:
            if address.timestamp < existing.address.timestamp:
                return False
            self._entries[key] = AddressBookEntry(address, current, source)
            return True
        if len(self._entries) >= self.max_entries:
            return False
        self._entries[key] = AddressBookEntry(address, current, source)
        return True

    def add_many(
        self,
        addresses: Iterable[PeerAddress],
        *,
        source: str,
        now: int | None = None,
    ) -> int:
        """Add eligible addresses and return the number accepted."""
        accepted = 0
        for address in addresses:
            if self.add(address, source=source, now=now):
                accepted += 1
        return accepted

    def prune(self, *, now: int | None = None) -> int:
        """Remove expired entries and return the number removed."""
        current = int(self._clock()) if now is None else now
        if not isinstance(current, int) or isinstance(current, bool) or current < 0:
            raise ValueError("now must be a non-negative integer")
        expired = [
            key for key, entry in self._entries.items()
            if current - entry.address.timestamp > self.max_age_seconds
        ]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def get(self, endpoint: tuple[str, int]) -> AddressBookEntry | None:
        """Look up a normalized (IP text, port) endpoint."""
        if not isinstance(endpoint, tuple) or len(endpoint) != 2:
            raise ValueError("endpoint must be an (ip, port) tuple")
        ip = ipaddress.ip_address(endpoint[0])
        key = (str(ip), endpoint[1])
        return self._entries.get(key)
