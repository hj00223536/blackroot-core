"""Fail-closed lifecycle facade for persistent headers and UTXO state.

The default compatibility mode uses separate SQLite files and a recovery
journal. An opt-in coordinated mode places all stores on one node-owned
connection and commits block acceptance/reorganization in one transaction.
Neither mode is a production-ready consensus node.
"""
from __future__ import annotations

from pathlib import Path
import stat
from typing import Callable

from .blackroot_blocks import Block
from .blackroot_chain import BlockHeader
from .blackroot_transactions import merkle_root
from .blackroot_header_store import PersistentHeaderStore
from .blackroot_utxo_db import UTXOStore
from .blackroot_recovery_journal import NodeRecoveryJournal
from .blackroot_sqlite import SQLiteTransactionCoordinator
from .blackroot_data_dir_lock import DataDirectoryLock


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
    seen: list[tuple[Path, str]] = []
    for store_name, path in paths.items():
        for previous_path, previous_name in seen:
            same_file = path == previous_path
            if not same_file and path.exists() and previous_path.exists():
                try:
                    same_file = path.samefile(previous_path)
                except OSError:
                    # Resolution and lexical comparison remain the conservative
                    # checks when the filesystem cannot answer same-file queries.
                    same_file = False
            if same_file:
                raise ValueError(
                    f"{previous_name} and {store_name} databases must use distinct paths; "
                    "sharing a SQLite file does not provide a shared transaction boundary"
                )
        seen.append((path, store_name))


class PersistentNodeState:
    """Coordinate replay-verified headers with the persistent active UTXO tip."""

    def __init__(
        self,
        header_path: str | Path,
        utxo_path: str | Path,
        pow_limit: int,
        genesis: BlockHeader,
        recovery_journal_path: str | Path | None = None,
        *,
        database_path: str | Path | None = None,
        adjusted_time_provider: Callable[[], int] | None = None,
        _data_directory_lock: DataDirectoryLock | None = None,
    ) -> None:
        if _data_directory_lock is not None and not _data_directory_lock.is_held:
            raise RuntimeError("provided data-directory lock is not held")
        self._data_directory_lock = _data_directory_lock
        self._coordinator: SQLiteTransactionCoordinator | None = None
        if database_path is not None:
            coordinator = SQLiteTransactionCoordinator(database_path)
            coordinator.__enter__()
            self._coordinator = coordinator
            try:
                with coordinator.transaction() as connection:
                    self.headers = PersistentHeaderStore(
                        database_path, pow_limit, genesis, connection=connection,
                        adjusted_time_provider=adjusted_time_provider
                    )
                    self.utxos = UTXOStore(database_path, connection=connection)
                    self.recovery_journal = NodeRecoveryJournal(
                        database_path, connection=connection
                    )
                    self.utxos.verify_integrity()
                    self._verify_persistent_tip()
                    self.recovery_journal.reconcile(self.utxos.tip())
            except BaseException:
                coordinator.__exit__(None, None, None)
                self._coordinator = None
                raise
            return

        journal_path = (Path(str(utxo_path) + ".recovery.sqlite")
                        if recovery_journal_path is None else recovery_journal_path)
        _validate_distinct_database_paths(header_path, utxo_path, journal_path)
        self.headers = PersistentHeaderStore(
            header_path, pow_limit, genesis,
            adjusted_time_provider=adjusted_time_provider,
        )
        self.utxos = UTXOStore(utxo_path)
        self.recovery_journal = NodeRecoveryJournal(journal_path)
        self.utxos.verify_integrity()
        self._verify_persistent_tip()
        self.recovery_journal.reconcile(self.utxos.tip())

    @property
    def coordinated(self) -> bool:
        return self._coordinator is not None

    @property
    def data_directory_locked(self) -> bool:
        """Whether this state currently owns the exclusive data-directory lock."""
        return (
            self._data_directory_lock is not None
            and self._data_directory_lock.is_held
        )

    @classmethod
    def open_locked(
        cls,
        data_dir: str | Path,
        database_path: str | Path,
        pow_limit: int,
        genesis: BlockHeader,
        *,
        adjusted_time_provider: Callable[[], int] | None = None,
    ) -> "PersistentNodeState":
        """Open coordinated node state while holding its data-directory lock.

        This is the required lifecycle entry point for deployments that need
        single-process ownership. The SQLite database must be directly inside
        the locked directory. Legacy constructors remain available for tests
        and compatibility, and do not provide this process-ownership guarantee.
        """
        directory = Path(data_dir).expanduser().resolve()
        requested_database = Path(database_path).expanduser()
        if not requested_database.is_absolute():
            requested_database = Path.cwd() / requested_database
        if requested_database.parent.resolve() != directory:
            raise ValueError(
                "locked node database must be directly inside the data directory"
            )
        # Preserve the final path component: resolve() here would silently
        # follow a database symlink before SQLite opens it.
        database = directory / requested_database.name
        lock = DataDirectoryLock(directory).acquire()
        try:
            # The private, locked directory prevents unprivileged path swaps;
            # reject pre-existing symlinks and special files before SQLite opens
            # the database or its WAL sidecars.
            for candidate in (
                database,
                Path(str(database) + "-wal"),
                Path(str(database) + "-shm"),
                Path(str(database) + "-journal"),
            ):
                try:
                    candidate_stat = candidate.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(candidate_stat.st_mode):
                    raise RuntimeError(
                        f"SQLite database path must be a regular non-symlink file: {candidate.name}"
                    )
            return cls(
                database,
                database,
                pow_limit,
                genesis,
                database_path=database,
                adjusted_time_provider=adjusted_time_provider,
                _data_directory_lock=lock,
            )
        except BaseException:
            lock.release()
            raise

    @classmethod
    def open_coordinated(
        cls, database_path: str | Path, pow_limit: int, genesis: BlockHeader, *,
        adjusted_time_provider: Callable[[], int] | None = None,
    ) -> "PersistentNodeState":
        """Open all persistent stores on one node-owned SQLite connection."""
        return cls(
            database_path, database_path, pow_limit, genesis,
            database_path=database_path,
            adjusted_time_provider=adjusted_time_provider,
        )

    def close(self) -> None:
        """Close node state and release its process lock, if owned."""
        try:
            if self._coordinator is not None:
                self._coordinator.__exit__(None, None, None)
        finally:
            if self._data_directory_lock is not None:
                self._data_directory_lock.release()
                self._data_directory_lock = None

    def __enter__(self) -> "PersistentNodeState":
        if self._coordinator is not None and not self._coordinator.is_open:
            raise RuntimeError("coordinated node state is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _require_coordinator(self) -> SQLiteTransactionCoordinator:
        if self._coordinator is None:
            raise RuntimeError("operation requires coordinated database mode")
        return self._coordinator

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

    def persist_synced_headers(self, chain) -> None:
        """Durably persist the validated DAG after P2P header synchronization."""
        if self.coordinated:
            with self._require_coordinator().transaction():
                self.headers.persist_chain(chain)
        else:
            self.headers.persist_chain(chain)

    def add_header(
        self,
        header: BlockHeader,
        *,
        adjusted_time: int | None = None,
        max_future_seconds: int = 7_200,
    ) -> str:
        """Validate and persist a header; block body is deliberately separate."""
        if not callable(self.headers.adjusted_time_provider):
            raise RuntimeError(
                "persistent node state requires its configured adjusted-time provider; "
                "caller-supplied timestamps are not accepted"
            )
        if adjusted_time is not None:
            raise ValueError(
                "persistent node state must use its configured adjusted-time provider"
            )
        if not self.coordinated:
            return self.headers.add_to_branch(
                header,
                adjusted_time=adjusted_time,
                max_future_seconds=max_future_seconds,
            )
        with self._require_coordinator().transaction():
            result = self.headers.add_to_branch(
                header,
                adjusted_time=adjusted_time,
                max_future_seconds=max_future_seconds,
            )
        self.headers.reload()
        return result

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
        if self.coordinated:
            with self._require_coordinator().transaction():
                self.utxos.store_block_body(block)
                old_tip = self.utxos.tip()
                new_tip = (height, block.header.hash)
                if old_tip == new_tip:
                    raise ValueError("block is already the active UTXO tip")
                self.recovery_journal.prepare(old_tip, new_tip)
                result = self.utxos.connect_validated_block(
                    block, height, self.headers.chain
                )
                self.recovery_journal.reconcile(self.utxos.tip())
            return result

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
        if merkle_root(tx.txid for tx in block.transactions) != block.header.merkle_root:
            raise ValueError("cannot archive a body whose transactions do not match the known header merkle root")
        if self.coordinated:
            with self._require_coordinator().transaction():
                return self.utxos.store_block_body(block)
        return self.utxos.store_block_body(block)

    def reorganize_best(self, replacement_blocks: dict[bytes, Block] | None = None) -> tuple[int, bytes]:
        """Switch to the HeaderChain-selected best branch using supplied or archived block bodies."""
        if self.coordinated:
            with self._require_coordinator().transaction():
                old_tip = self.utxos.tip()
                best_node = self.headers.chain.node(self.headers.chain.best_hash)
                if best_node is None:
                    raise RuntimeError("header chain has no best node")
                new_tip = (best_node.height, best_node.header.hash)
                if old_tip == new_tip:
                    return self.utxos.reorganize_to_best(
                        self.headers.chain, replacement_blocks
                    )
                self.recovery_journal.prepare(old_tip, new_tip)
                result = self.utxos.reorganize_to_best(
                    self.headers.chain, replacement_blocks
                )
                self.recovery_journal.reconcile(self.utxos.tip())
            self._verify_persistent_tip()
            return result

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
