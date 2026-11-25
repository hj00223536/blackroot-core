"""Bounded multi-peer assignment for block-body downloads.

The pool chooses among caller-supplied, already-connected peer identifiers.
It does not open connections or trust peer-supplied data: received block bodies
must still pass the normal header and UTXO validation path.
"""
from __future__ import annotations

from collections.abc import Hashable, Sequence


class MultiPeerBlockRequestPool:
    """Assign each block request to one eligible peer with bounded load."""

    def __init__(self, *, max_total: int = 512, max_per_peer: int = 64) -> None:
        for name, value in (("max_total", max_total), ("max_per_peer", max_per_peer)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if max_per_peer > max_total:
            raise ValueError("max_per_peer cannot exceed max_total")
        self.max_total = max_total
        self.max_per_peer = max_per_peer
        self._assignments: dict[bytes, Hashable] = {}
        self._loads: dict[Hashable, set[bytes]] = {}
        self._rotation = 0

    @property
    def pending_hashes(self) -> tuple[bytes, ...]:
        return tuple(self._assignments)

    def peer_load(self, peer_id: Hashable) -> int:
        return len(self._loads.get(peer_id, ()))

    def assigned_peer(self, block_hash: bytes) -> Hashable | None:
        return self._assignments.get(block_hash)

    def assign(self, block_hash: bytes, available_peers: Sequence[Hashable]) -> Hashable:
        """Assign a hash to the least-loaded eligible peer; return its ID."""
        if not isinstance(block_hash, bytes) or len(block_hash) != 32:
            raise ValueError("block_hash must be exactly 32 bytes")
        if block_hash in self._assignments:
            raise ValueError("block already has an assigned source")
        if len(self._assignments) >= self.max_total:
            raise ValueError("maximum global block requests reached")
        peers = tuple(dict.fromkeys(available_peers))
        if not peers:
            raise ValueError("no eligible peers available")
        for peer_id in peers:
            try:
                hash(peer_id)
            except TypeError as exc:
                raise TypeError("peer identifiers must be hashable") from exc
        eligible = [
            peer_id for peer_id in peers
            if self.peer_load(peer_id) < self.max_per_peer
        ]
        if not eligible:
            raise ValueError("all eligible peers reached their request limit")
        minimum = min(self.peer_load(peer_id) for peer_id in eligible)
        least_loaded = [peer_id for peer_id in eligible if self.peer_load(peer_id) == minimum]
        chosen = least_loaded[self._rotation % len(least_loaded)]
        self._rotation += 1
        self._assignments[block_hash] = chosen
        self._loads.setdefault(chosen, set()).add(block_hash)
        return chosen

    def complete(self, block_hash: bytes, peer_id: Hashable) -> bool:
        """Release an assignment only when the assigned peer supplied it."""
        assigned = self._assignments.get(block_hash)
        if assigned is None or assigned != peer_id:
            return False
        del self._assignments[block_hash]
        hashes = self._loads[peer_id]
        hashes.remove(block_hash)
        if not hashes:
            del self._loads[peer_id]
        return True

    def release_peer(self, peer_id: Hashable) -> tuple[bytes, ...]:
        """Release all assignments held by a disconnected or banned peer."""
        hashes = tuple(self._loads.pop(peer_id, ()))
        for block_hash in hashes:
            self._assignments.pop(block_hash, None)
        return hashes

    def cancel(self, block_hash: bytes) -> bool:
        """Cancel one assignment regardless of source."""
        if not isinstance(block_hash, bytes) or len(block_hash) != 32:
            raise ValueError("block_hash must be exactly 32 bytes")
        peer_id = self._assignments.get(block_hash)
        if peer_id is None:
            return False
        return self.complete(block_hash, peer_id)
