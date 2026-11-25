"""Durable intent journal for coordinating header and UTXO state.

The journal can run standalone or on a node-owned SQLite connection. When
coordinated, its writes participate in the caller's outer transaction.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .blackroot_sqlite import SQLiteTransactionConnection

Tip = tuple[int, bytes] | None


def _validate_tip(tip: Tip, label: str) -> None:
    if tip is None:
        return
    if (not isinstance(tip, tuple) or len(tip) != 2
            or not isinstance(tip[0], int) or isinstance(tip[0], bool)
            or tip[0] < 0 or not isinstance(tip[1], bytes)
            or len(tip[1]) != 32):
        raise ValueError(f"{label} must be None or (non-negative height, 32-byte hash)")


class NodeRecoveryJournal:
    """Persist and reconcile a single in-flight active-tip transition."""

    def __init__(
        self, path: str | Path, *,
        connection: SQLiteTransactionConnection | None = None,
    ):
        self.path = str(path)
        self._external_connection = connection
        if connection is not None and not isinstance(connection, SQLiteTransactionConnection):
            raise TypeError("connection must be a SQLiteTransactionConnection")
        if connection is not None and not connection.in_transaction:
            raise RuntimeError(
                "coordinator-owned recovery-journal initialization requires an active outer transaction"
            )
        with self._connection_scope() as db:
            if self._external_connection is None:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS recovery_intent (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    old_height INTEGER,
                    old_hash BLOB,
                    new_height INTEGER,
                    new_hash BLOB,
                    CHECK((old_height IS NULL AND old_hash IS NULL) OR
                          (old_height >= 0 AND length(old_hash)=32)),
                    CHECK((new_height IS NULL AND new_hash IS NULL) OR
                          (new_height >= 0 AND length(new_hash)=32))
                )
            """)
            if self._external_connection is None:
                db.commit()

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
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def _write_scope(self) -> Iterator[sqlite3.Connection | SQLiteTransactionConnection]:
        if self._external_connection is not None:
            if not self._external_connection.in_transaction:
                raise RuntimeError(
                    "coordinator-owned recovery-journal writes require an active outer transaction"
                )
            yield self._external_connection
            return
        with self._connection_scope() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                if db.in_transaction:
                    db.rollback()
                raise

    @staticmethod
    def _columns(tip: Tip) -> tuple[int | None, bytes | None]:
        return (None, None) if tip is None else tip

    def prepare(self, old_tip: Tip, new_tip: Tip) -> None:
        _validate_tip(old_tip, "old_tip")
        _validate_tip(new_tip, "new_tip")
        if old_tip == new_tip:
            raise ValueError("recovery intent must change the active tip")
        old_height, old_hash = self._columns(old_tip)
        new_height, new_hash = self._columns(new_tip)
        with self._write_scope() as db:
            pending = db.execute(
                "SELECT 1 FROM recovery_intent WHERE singleton=1"
            ).fetchone()
            if pending:
                raise RuntimeError("unresolved recovery intent; reopen and reconcile first")
            db.execute(
                "INSERT INTO recovery_intent(singleton, old_height, old_hash, new_height, new_hash) "
                "VALUES(1, ?, ?, ?, ?)",
                (old_height, old_hash, new_height, new_hash),
            )

    def reconcile(self, observed_tip: Tip) -> str:
        """Resolve pending intent against actual UTXO tip; reject third states."""
        _validate_tip(observed_tip, "observed_tip")
        with self._write_scope() as db:
            row = db.execute(
                "SELECT old_height, old_hash, new_height, new_hash "
                "FROM recovery_intent WHERE singleton=1"
            ).fetchone()
            if row is None:
                return "clean"
            old_tip = None if row[0] is None else (row[0], bytes(row[1]))
            new_tip = None if row[2] is None else (row[2], bytes(row[3]))
            if observed_tip == new_tip:
                result = "committed"
            elif observed_tip == old_tip:
                result = "not_applied"
            else:
                raise RuntimeError(
                    "UTXO tip matches neither endpoint of pending recovery intent"
                )
            db.execute("DELETE FROM recovery_intent WHERE singleton=1")
            return result

    def pending(self) -> bool:
        with self._connection_scope() as db:
            return db.execute(
                "SELECT 1 FROM recovery_intent WHERE singleton=1"
            ).fetchone() is not None
