"""Bounded request tracking and validation for peer block-body payloads.

This module deliberately does not open sockets or send network messages. It
provides the safe stateful boundary a future transport can call after receiving
a block payload: only requested, best-chain headers may be connected.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from .blackroot_blocks import Block, MAX_BLOCK_SIZE
from .blackroot_chain import HeaderChain

DEFAULT_MAX_OUTSTANDING_BLOCKS = 128


class BlockBodyRequestTracker:
    """Track bounded block-body requests against the current validated best chain."""

    def __init__(self, max_outstanding: int = DEFAULT_MAX_OUTSTANDING_BLOCKS, *, clock: Callable[[], float] = time.monotonic):
        if (
            not isinstance(max_outstanding, int)
            or isinstance(max_outstanding, bool)
            or max_outstanding < 1
        ):
            raise ValueError("max_outstanding must be a positive integer")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.max_outstanding = max_outstanding
        self._clock = clock
        self._pending: dict[bytes, tuple[int, float]] = {}

    @property
    def pending_hashes(self) -> tuple[bytes, ...]:
        """Return a stable snapshot of outstanding block hashes."""
        return tuple(self._pending)

    def request(self, block_hash: bytes, chain: HeaderChain) -> int:
        """Mark a known best-chain block body as requested and return its height."""
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if not isinstance(block_hash, bytes) or len(block_hash) != 32:
            raise ValueError("block_hash must be exactly 32 bytes")
        node = chain.node(block_hash)
        if node is None:
            raise ValueError("cannot request a body for an unknown header")
        if chain.get(node.height).hash != block_hash:
            raise ValueError("cannot request a body outside the selected best chain")
        if block_hash in self._pending:
            raise ValueError("block body is already outstanding")
        if len(self._pending) >= self.max_outstanding:
            raise ValueError("maximum outstanding block-body requests reached")
        self._pending[block_hash] = (node.height, self._clock())
        return node.height

    def expire(self, timeout: float, *, now: float | None = None) -> tuple[bytes, ...]:
        """Remove and return requests whose age reached timeout seconds."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        current = self._clock() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ValueError("now must be a number")
        expired = tuple(
            block_hash for block_hash, (_, requested_at) in self._pending.items()
            if current - requested_at >= timeout
        )
        for block_hash in expired:
            del self._pending[block_hash]
        return expired

    def cancel_all(self) -> tuple[bytes, ...]:
        """Clear all outstanding requests, e.g. when their peer disconnects."""
        cancelled = tuple(self._pending)
        self._pending.clear()
        return cancelled

    def cancel(self, block_hash: bytes) -> bool:
        """Cancel a pending request; return whether one existed."""
        if not isinstance(block_hash, bytes) or len(block_hash) != 32:
            raise ValueError("block_hash must be exactly 32 bytes")
        return self._pending.pop(block_hash, None) is not None

    def accept_payload(
        self,
        block_hash: bytes,
        payload: bytes,
        chain: HeaderChain,
        store,
    ) -> tuple[int, int]:
        """Decode and connect a requested body; return (height, fees).

        The pending request is removed only after the UTXO store has
        successfully validated and atomically connected the body. Failed,
        unsolicited, stale-fork, oversized, and mismatched payloads do not
        mutate the request tracker or persistent chain state.
        """
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if not isinstance(block_hash, bytes) or len(block_hash) != 32:
            raise ValueError("block_hash must be exactly 32 bytes")
        if block_hash not in self._pending:
            raise ValueError("unsolicited block body")
        if not isinstance(payload, bytes):
            raise TypeError("block payload must be bytes")
        if len(payload) > MAX_BLOCK_SIZE:
            raise ValueError("block payload exceeds provisional size limit")

        expected_height, _requested_at = self._pending[block_hash]
        node = chain.node(block_hash)
        if node is None or node.height != expected_height:
            raise ValueError("requested header is no longer available")
        if chain.get(expected_height).hash != block_hash:
            raise ValueError("requested header is no longer on the selected best chain")

        block = Block.deserialize(payload)
        if block.header.hash != block_hash:
            raise ValueError("block body hash does not match requested header")
        if block.header.serialize() != node.header.serialize():
            raise ValueError("block body header does not match validated header entry")

        connector = getattr(store, "connect_validated_block", None)
        if not callable(connector):
            raise TypeError("store must provide connect_validated_block")
        fees = connector(block, expected_height, chain)
        del self._pending[block_hash]
        return expected_height, fees
