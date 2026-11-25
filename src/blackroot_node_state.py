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
from .blackroot_recovery_journal import NodeRecoveryJournal


def _validate_distinct_database_paths(
    header_path: str | Path,
    utxo_path: str | Path,
    recovery_journal_path: str | Path,
) -> None:
    """Reject path aliases: separate stores are not transactionally atomic."""
    paths = {
        "header": Path(header_path).expanduser().resolve(),
        "UTXO": Path(utxo_path).expanduser().resolve(),
        "recovery journal": Path(recovery_journal_path).expanduser().resolve(),
    }
    seen: dict[Path, str] = {}
    for store_name, path in paths.items():
        previous = seen.get(path)
        if previous is not None:
            raise ValueError(
                f"{previous} and {store_name} databases must use distinct paths; "
                "sharing a SQLite file does not provide a shared transaction boundary"
            )
        seen[path] = store_name


class PersistentNodeState:
    """Coordinate replay-verified headers with the persistent active UTXO tip."""

    def __init__(
        self,
        header_path: str | Path,
        utxo_path: str | Path,
        pow_limit: int,
        genesis: BlockHeader,
        recovery_journal_path: str | Path | None = None,
    ) -> None:
        journal_path = (Path(str(utxo_path) + ".recovery.sqlite")
                        if recovery_journal_path is None else recovery_journal_path)
        _validate_distinct_database_paths(header_path, utxo_path, journal_path)
        self.headers = PersistentHeaderStore(header_path, pow_limit, genesis)
        self.utxos = UTXOStore(utxo_path)
        self.recovery_journal = NodeRecoveryJournal(journal_path)
        self.utxos.verify_integrity()
        self._verify_persistent_tip()
        self.recovery_journal.reconcile(self.utxos.tip())

    def _verify_persistent_tip(self) -> None:
        records = self.utxos.active_block_headers()
        if not records:
            return
        expected_parent = bytes(32)
        for expected_height, (height, block_hash, prev_hash, stored_header) in enumerate(records):
            if height != expected_height:
                raise RuntimeError("persistent UTXO active block heights are not contiguous")
            if prev_hash != expected_parent:
                raise RuntimeError("persistent UTXO active block parent linkage is corrupt")
            node = self.headers.chain.node(block_hash)
            if node is None or node.height != height:
                raise RuntimeError(
                    "persistent UTXO block is absent or inconsistent in replayed header DAG"
                )
            if stored_header != node.header.serialize():
                raise RuntimeError(
                    "persistent UTXO block header does not match replayed header DAG"
                )
            if node.header.prev_hash != prev_hash:
                raise RuntimeError("persistent UTXO parent hash disagrees with header DAG")
            if height == 0 and block_hash != self.headers.chain.best_chain()[0].hash:
                raise RuntimeError("persistent UTXO genesis does not match header-store genesis")
            expected_parent = block_hash

        active = self.utxos.tip()
        if active != (records[-1][0], records[-1][1]):
            raise RuntimeError("persistent UTXO tip disagrees with active block records")

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
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise ValueError("height must be a non-negative integer")
        if height > self.headers.chain.height:
            raise ValueError("block height is above persistent best header tip")
        selected = self.headers.chain.get(height)
        if selected.hash != block.header.hash:
            raise ValueError("block body is not selected by persistent best header chain")
        self.utxos.store_block_body(block)
        old_tip = self.utxos.tip()
        new_tip = (height, block.header.hash)
        if old_tip == new_tip:
            raise ValueError("block is already the active UTXO tip")
        self.recovery_journal.prepare(old_tip, new_tip)
        try:
            result = self.utxos.connect_validated_block(block, height, self.headers.chain)
        except Exception:
            self.recovery_journal.reconcile(self.utxos.tip())
            raise
        self.recovery_journal.reconcile(self.utxos.tip())
        return result

    def archive_block_body(self, block: Block) -> bytes:
        """Archive a candidate body only when its header is known in the header DAG."""
        if not isinstance(block, Block):
            raise TypeError("block must be a Block")
        if self.headers.chain.node(block.header.hash) is None:
            raise ValueError("cannot archive a body for an unknown header")
        return self.utxos.store_block_body(block)

    def reorganize_best(self, replacement_blocks: dict[bytes, Block] | None = None) -> tuple[int, bytes]:
        """Switch to the greater-work branch using supplied or archived block bodies."""
        old_tip = self.utxos.tip()
        best_node = self.headers.chain.node(self.headers.chain.best_hash)
        if best_node is None:
            raise RuntimeError("header chain has no best node")
        new_tip = (best_node.height, best_node.header.hash)
        if old_tip == new_tip:
            return self.utxos.reorganize_to_best(self.headers.chain, replacement_blocks)
        self.recovery_journal.prepare(old_tip, new_tip)
        try:
            result = self.utxos.reorganize_to_best(self.headers.chain, replacement_blocks)
        except Exception:
            self.recovery_journal.reconcile(self.utxos.tip())
            raise
        self.recovery_journal.reconcile(self.utxos.tip())
        self._verify_persistent_tip()
        return result
