"""Fail-closed lifecycle facade for persistent headers and UTXO state.

The header DAG and UTXO database remain separate SQLite databases, so this
facade does not claim cross-database atomicity. It verifies their relationship
on startup and requires explicit block bodies for best-chain connection or
reorganization. A crash can leave headers ahead of UTXO state; callers resume
by supplying the missing validated bodies.
"""
from __future__ import annotations

from pathlib import Path

from .blackroot_blocks import Block
from .blackroot_chain import BlockHeader
from .blackroot_header_store import PersistentHeaderStore
from .blackroot_utxo_db import UTXOStore


class PersistentNodeState:
    """Coordinate replay-verified headers with the persistent active UTXO tip."""

    def __init__(
        self,
        header_path: str | Path,
        utxo_path: str | Path,
        pow_limit: int,
        genesis: BlockHeader,
    ) -> None:
        self.headers = PersistentHeaderStore(header_path, pow_limit, genesis)
        self.utxos = UTXOStore(utxo_path)
        self._verify_persistent_tip()

    def _verify_persistent_tip(self) -> None:
        active = self.utxos.tip()
        if active is None:
            return
        height, block_hash = active
        node = self.headers.chain.node(block_hash)
        if node is None or node.height != height:
            raise RuntimeError(
                "persistent UTXO tip is absent or inconsistent in replayed header DAG"
            )
        if height == 0 and block_hash != self.headers.chain.best_chain()[0].hash:
            raise RuntimeError("persistent UTXO genesis does not match header-store genesis")

    def add_header(
        self,
        header: BlockHeader,
        *,
        adjusted_time: int | None = None,
        max_future_seconds: int = 7_200,
    ) -> str:
        """Validate and persist a header; block body is deliberately separate."""
        return self.headers.add_to_branch(
            header,
            adjusted_time=adjusted_time,
            max_future_seconds=max_future_seconds,
        )

    def connect_best_block(self, block: Block, height: int) -> int:
        """Connect a body only if its header is selected at that best-chain height."""
        if not isinstance(block, Block):
            raise TypeError("block must be a Block")
        if height > self.headers.chain.height:
            raise ValueError("block height is above persistent best header tip")
        selected = self.headers.chain.get(height)
        if selected.hash != block.header.hash:
            raise ValueError("block body is not selected by persistent best header chain")
        return self.utxos.connect_validated_block(block, height, self.headers.chain)

    def reorganize_best(self, replacement_blocks: dict[bytes, Block]) -> tuple[int, bytes]:
        """Switch UTXO state to the greater-work header branch using supplied bodies."""
        result = self.utxos.reorganize_to_best(self.headers.chain, replacement_blocks)
        self._verify_persistent_tip()
        return result
