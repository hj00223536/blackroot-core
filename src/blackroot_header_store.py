"""SQLite-backed, replay-verified persistence for the experimental header DAG.

This store persists header fields only. Every reopen rebuilds the in-memory
HeaderChain from genesis in height order and rechecks proof of work, linkage,
difficulty, timestamps, hashes, heights, and cumulative work. It is a prototype,
not a production consensus database.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .blackroot_chain import BlockHeader, HeaderChain
from .blackroot_sqlite import SQLiteTransactionConnection


class PersistentHeaderStore:
    SCHEMA_VERSION = 1

    def __init__(
        self, path: str | Path, pow_limit: int, genesis: BlockHeader, *,
        connection: SQLiteTransactionConnection | None = None,
        adjusted_time_provider: Callable[[], int] | None = None,
    ):
        if not isinstance(genesis, BlockHeader):
            raise TypeError("genesis must be a BlockHeader")
        if not isinstance(pow_limit, int) or isinstance(pow_limit, bool) or pow_limit <= 0:
            raise ValueError("pow_limit must be a positive integer")
        self.path = str(path)
        if adjusted_time_provider is not None and not callable(adjusted_time_provider):
            raise TypeError("adjusted_time_provider must be callable")
        self.pow_limit = pow_limit
        self.adjusted_time_provider = adjusted_time_provider
        self._external_connection = connection
        if connection is not None and not isinstance(connection, SQLiteTransactionConnection):
            raise TypeError("connection must be a SQLiteTransactionConnection")
        if connection is not None and not connection.in_transaction:
            raise RuntimeError("coordinator-owned header initialization requires an active outer transaction")
        self._chain: HeaderChain | None = None
        self._initialize(genesis)

    @contextmanager
    def _connection_scope(self) -> Iterator[sqlite3.Connection | SQLiteTransactionConnection]:
        """Borrow the coordinator connection or close a locally owned handle."""
        db = self._connect()
        try:
            yield db
        finally:
            if self._external_connection is None:
                db.close()

    def _connect(self):
        if self._external_connection is not None:
            return self._external_connection
        db = sqlite3.connect(self.path, timeout=10.0)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    @contextmanager
    def _write_scope(self) -> Iterator[sqlite3.Connection | SQLiteTransactionConnection]:
        if self._external_connection is not None:
            if not self._external_connection.in_transaction:
                raise RuntimeError("coordinator-owned header writes require an active outer transaction")
            yield self._external_connection
            return
        with self._connection_scope() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                if db.in_transaction:
                    db.rollback()
                raise

    @staticmethod
    def _verify_sqlite_integrity(db: sqlite3.Connection) -> None:
        """Reject SQLite page/index corruption before replaying persisted headers."""
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"persistent header SQLite integrity check failed: {integrity!r}")
        foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"persistent header foreign-key check failed: {foreign_key_errors!r}"
            )

    @property
    def chain(self) -> HeaderChain:
        """Return the current in-memory validated DAG."""
        if self._chain is None:
            raise RuntimeError("persistent header store has not been initialized")
        return self._chain

    def _initialize(self, genesis: BlockHeader) -> None:
        with self._connection_scope() as db:
            if self._external_connection is None:
                db.execute("PRAGMA journal_mode = WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS header_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS headers (
                    block_hash BLOB PRIMARY KEY CHECK(length(block_hash) = 32),
                    height INTEGER NOT NULL CHECK(height >= 0),
                    version INTEGER NOT NULL,
                    prev_hash BLOB NOT NULL CHECK(length(prev_hash) = 32),
                    merkle_root BLOB NOT NULL CHECK(length(merkle_root) = 32),
                    timestamp INTEGER NOT NULL CHECK(timestamp >= 0),
                    bits INTEGER NOT NULL CHECK(bits >= 0 AND bits <= 4294967295),
                    nonce INTEGER NOT NULL CHECK(nonce >= 0 AND nonce <= 4294967295),
                    chainwork TEXT NOT NULL
                ) WITHOUT ROWID
            """)
            self._verify_sqlite_integrity(db)
            metadata = dict(db.execute("SELECT key, value FROM header_metadata"))
            expected = {
                "schema_version": str(self.SCHEMA_VERSION),
                "pow_limit": str(self.pow_limit),
                "genesis_hash": genesis.hash.hex(),
            }
            if not metadata:
                initial = HeaderChain(self.pow_limit, genesis, adjusted_time_provider=self.adjusted_time_provider)
                db.executemany(
                    "INSERT INTO header_metadata(key, value) VALUES(?, ?)",
                    expected.items(),
                )
                self._insert_node(db, initial, genesis.hash)
                self._chain = initial
            else:
                if metadata != expected:
                    raise RuntimeError("persistent header store parameters do not match supplied network genesis")
                if db.execute("SELECT COUNT(*) FROM headers").fetchone()[0] == 0:
                    raise RuntimeError("persistent header store is missing its genesis header")
                self._replay(db, genesis)
            if self._external_connection is None:
                db.commit()

    @staticmethod
    def _insert_node(db: sqlite3.Connection, chain: HeaderChain, block_hash: bytes) -> None:
        node = chain.node(block_hash)
        if node is None:
            raise ValueError("cannot persist an unknown header")
        header = node.header
        db.execute(
            "INSERT INTO headers(block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (block_hash, node.height, header.version, header.prev_hash,
             header.merkle_root, header.timestamp, header.bits, header.nonce,
             str(node.chainwork)),
        )

    def _replay(self, db: sqlite3.Connection, genesis: BlockHeader) -> None:
        replayed = HeaderChain(self.pow_limit, genesis, adjusted_time_provider=self.adjusted_time_provider)
        genesis_node = replayed.node(genesis.hash)
        rows = db.execute(
            "SELECT block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork "
            "FROM headers ORDER BY height, block_hash"
        ).fetchall()
        genesis_rows = 0
        replay_adjusted_time = (
            self.adjusted_time_provider()
            if self.adjusted_time_provider is not None else None
        )
        for block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork in rows:
            header = BlockHeader(version, bytes(prev_hash), bytes(merkle_root), timestamp, bits, nonce)
            actual_hash = header.hash
            if actual_hash != bytes(block_hash):
                raise RuntimeError("persistent header hash mismatch during replay")
            if height == 0:
                genesis_rows += 1
                if (actual_hash != genesis.hash or height != genesis_node.height
                        or str(genesis_node.chainwork) != chainwork
                        or header.serialize() != genesis.serialize()):
                    raise RuntimeError("persistent genesis metadata mismatch during replay")
                continue
            try:
                replayed.add_to_branch(header, adjusted_time=replay_adjusted_time)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"persistent header replay rejected {actual_hash.hex()}: {exc}") from exc
            node = replayed.node(actual_hash)
            if node is None or node.height != height or str(node.chainwork) != chainwork:
                raise RuntimeError("persistent header metadata mismatch during replay")
        if genesis_rows != 1:
            raise RuntimeError("persistent header store must contain exactly one genesis")
        self._chain = replayed

    def add_to_branch(
        self, header: BlockHeader, *, adjusted_time: int | None = None,
        max_future_seconds: int = 7_200,
    ) -> str:
        """Validate on a replayed candidate, persist atomically, then publish it."""
        live_chain = self.chain
        candidate = HeaderChain(
            self.pow_limit, live_chain.best_chain()[0],
            adjusted_time_provider=self.adjusted_time_provider,
        )
        # Rebuild all known branches against one clock snapshot so replay does
        # not depend on clock drift between individual stored headers.
        replay_adjusted_time = adjusted_time
        if replay_adjusted_time is None and self.adjusted_time_provider is not None:
            replay_adjusted_time = self.adjusted_time_provider()
        nodes = (node for node in live_chain.nodes if node.height > 0)
        for node in nodes:
            candidate.add_to_branch(
                node.header, adjusted_time=replay_adjusted_time
            )
        display_hash = candidate.add_to_branch(
            header, adjusted_time=replay_adjusted_time,
            max_future_seconds=max_future_seconds,
        )
        block_hash = header.hash
        with self._write_scope() as db:
            # Another process may have committed headers after this
            # instance loaded its in-memory DAG. Never append from stale
            # state: require an explicit replay before retrying.
            persisted_hashes = {
                bytes(row[0]) for row in db.execute(
                    "SELECT block_hash FROM headers"
                ).fetchall()
            }
            live_hashes = {node.header.hash for node in live_chain.nodes}
            if persisted_hashes != live_hashes:
                raise RuntimeError(
                    "persistent header store changed concurrently; reload before retrying"
                )
            self._insert_node(db, candidate, block_hash)
        # With an externally-owned transaction, publish only after the caller
        # commits and explicitly reloads. A later outer rollback must not leave
        # this in-memory DAG ahead of durable storage.
        if self._external_connection is None:
            self._chain = candidate
        return display_hash

    def persist_chain(self, chain: HeaderChain) -> None:
        """Persist headers accepted by the live sync chain without replacing it.

        P2P header synchronization validates into a shared in-memory HeaderChain.
        This method durably records that validated DAG before block bodies can be
        connected, so a restart can replay the same header ancestry.
        """
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if chain.get(0).hash != self.chain.get(0).hash:
            raise ValueError("cannot persist a chain with a different genesis")
        if chain.pow_limit != self.pow_limit:
            raise ValueError("cannot persist a chain validated under a different proof-of-work limit")
        if chain.adjusted_time_provider is not self.adjusted_time_provider:
            raise ValueError("cannot persist a chain with a different adjusted-time provider")
        if chain.allow_unchecked_time_for_tests:
            raise ValueError("cannot persist a chain using the test-only unchecked-time mode")
        live_nodes = sorted(chain.nodes, key=lambda node: (node.height, node.header.hash))
        with self._write_scope() as db:
            rows = db.execute(
                "SELECT block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork FROM headers"
            ).fetchall()
            persisted = {bytes(row[0]): row[1:] for row in rows}
            live_hashes = {node.header.hash for node in live_nodes}
            if not set(persisted).issubset(live_hashes):
                raise RuntimeError("persistent header store contains headers absent from live sync chain")
            for node in live_nodes:
                block_hash = node.header.hash
                header = node.header
                expected = (
                    node.height, header.version, header.prev_hash, header.merkle_root,
                    header.timestamp, header.bits, header.nonce, str(node.chainwork),
                )
                if block_hash in persisted:
                    actual = persisted[block_hash]
                    normalized = (actual[0], actual[1], bytes(actual[2]), bytes(actual[3]),
                                  actual[4], actual[5], actual[6], actual[7])
                    if normalized != expected:
                        raise RuntimeError("persisted header metadata conflicts with live validated chain")
                else:
                    self._insert_node(db, chain, block_hash)

    def reload(self) -> HeaderChain:
        """Replay persisted headers after an externally-owned transaction commits."""
        with self._connection_scope() as db:
            self._verify_sqlite_integrity(db)
            self._replay(db, self.chain.best_chain()[0])
        return self.chain
