"""SQLite-backed, replay-verified persistence for the experimental header DAG.

This store persists header fields only. Every reopen rebuilds the in-memory
HeaderChain from genesis in height order and rechecks proof of work, linkage,
difficulty, timestamps, hashes, heights, and cumulative work. It is a prototype,
not a production consensus database.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .blackroot_chain import BlockHeader, HeaderChain


class PersistentHeaderStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, pow_limit: int, genesis: BlockHeader):
        if not isinstance(genesis, BlockHeader):
            raise TypeError("genesis must be a BlockHeader")
        if not isinstance(pow_limit, int) or isinstance(pow_limit, bool) or pow_limit <= 0:
            raise ValueError("pow_limit must be a positive integer")
        self.path = str(path)
        self.pow_limit = pow_limit
        self._chain = HeaderChain(pow_limit, genesis)
        self._initialize(genesis)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10.0)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    @property
    def chain(self) -> HeaderChain:
        """Return the current in-memory validated DAG."""
        return self._chain

    def _initialize(self, genesis: BlockHeader) -> None:
        with self._connect() as db:
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
            metadata = dict(db.execute("SELECT key, value FROM header_metadata"))
            expected = {
                "schema_version": str(self.SCHEMA_VERSION),
                "pow_limit": str(self.pow_limit),
                "genesis_hash": genesis.hash.hex(),
            }
            if not metadata:
                db.executemany(
                    "INSERT INTO header_metadata(key, value) VALUES(?, ?)",
                    expected.items(),
                )
                self._insert_node(db, self._chain, genesis.hash)
            else:
                if metadata != expected:
                    raise RuntimeError("persistent header store parameters do not match supplied network genesis")
                if db.execute("SELECT COUNT(*) FROM headers").fetchone()[0] == 0:
                    raise RuntimeError("persistent header store is missing its genesis header")
                self._replay(db, genesis)

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
        replayed = HeaderChain(self.pow_limit, genesis)
        rows = db.execute(
            "SELECT block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork "
            "FROM headers ORDER BY height, block_hash"
        ).fetchall()
        genesis_rows = 0
        for block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork in rows:
            header = BlockHeader(version, bytes(prev_hash), bytes(merkle_root), timestamp, bits, nonce)
            actual_hash = header.hash
            if actual_hash != bytes(block_hash):
                raise RuntimeError("persistent header hash mismatch during replay")
            if height == 0:
                genesis_rows += 1
                if actual_hash != genesis.hash:
                    raise RuntimeError("persistent header store contains a different genesis")
                continue
            try:
                replayed.add_to_branch(header)
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
        candidate = HeaderChain(self.pow_limit, self._chain.best_chain()[0])
        # Rebuild all known branches so fork choice and duplicate checks are
        # evaluated against the same DAG without mutating the live instance.
        nodes = sorted(
            (node for node in self._chain._nodes.values() if node.height > 0),
            key=lambda node: (node.height, node.header.hash),
        )
        for node in nodes:
            candidate.add_to_branch(node.header)
        display_hash = candidate.add_to_branch(
            header, adjusted_time=adjusted_time,
            max_future_seconds=max_future_seconds,
        )
        block_hash = header.hash
        node = candidate.node(block_hash)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._insert_node(db, candidate, block_hash)
                db.commit()
            except Exception:
                db.rollback()
                raise
        self._chain = candidate
        return display_hash
