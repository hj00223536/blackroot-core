"""Node-owned SQLite connection and explicit transaction boundary.

This primitive is not wired into the existing stores yet. It provides the
ownership contract that store adapters must adopt before atomic persistence
can be claimed.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteTransactionCoordinator:
    """Own one SQLite connection and serialize caller-owned write transactions."""

    def __init__(self, path: str | Path, *, timeout: float = 10.0):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.path = str(Path(path).expanduser())
        self.timeout = float(timeout)
        self._connection: sqlite3.Connection | None = None
        self._transaction_active = False

    def __enter__(self) -> "SQLiteTransactionCoordinator":
        if self._connection is not None:
            raise RuntimeError("SQLite coordinator is already open")
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()
            self._connection = None
            self._transaction_active = False

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLite coordinator is not open")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit once on success; roll back on every exceptional exit."""
        connection = self.connection
        if self._transaction_active or connection.in_transaction:
            raise RuntimeError("nested or externally-started transactions are not supported")
        self._transaction_active = True
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            self._transaction_active = False
