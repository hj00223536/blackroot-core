"""Node-owned SQLite connection and explicit transaction boundary.

The coordinator exposes a guarded connection facade to stores. Participating
stores may execute SQL but cannot independently commit, roll back, or close
the node-owned connection.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteTransactionConnection:
    """Restricted view of a coordinator-owned SQLite connection."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._connection.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._connection.executescript(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args, **kwargs)

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction

    def commit(self) -> None:
        raise RuntimeError("store cannot commit a coordinator-owned transaction")

    def rollback(self) -> None:
        raise RuntimeError("store cannot roll back a coordinator-owned transaction")

    def close(self) -> None:
        raise RuntimeError("store cannot close a coordinator-owned connection")

    def __enter__(self) -> "SQLiteTransactionConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        # Deliberately do not commit or roll back: the coordinator owns that.
        return None


class SQLiteTransactionCoordinator:
    """Own one SQLite connection and serialize caller-owned write transactions."""

    def __init__(self, path: str | Path, *, timeout: float = 10.0):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.path = str(Path(path).expanduser())
        self.timeout = float(timeout)
        self._connection: sqlite3.Connection | None = None
        self._transaction_active = False
        self._facade: SQLiteTransactionConnection | None = None

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
        self._facade = SQLiteTransactionConnection(connection)
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
            self._facade = None
            self._transaction_active = False

    @property
    def is_open(self) -> bool:
        """Whether the coordinator currently owns an open SQLite connection."""
        return self._connection is not None

    @property
    def connection(self) -> SQLiteTransactionConnection:
        if self._facade is None:
            raise RuntimeError("SQLite coordinator is not open")
        return self._facade

    @contextmanager
    def transaction(self) -> Iterator[SQLiteTransactionConnection]:
        """Commit once on success; roll back on every exceptional exit."""
        connection = self._connection
        facade = self.connection
        if connection is None:
            raise RuntimeError("SQLite coordinator is not open")
        if self._transaction_active or connection.in_transaction:
            raise RuntimeError("nested or externally-started transactions are not supported")
        self._transaction_active = True
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield facade
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            self._transaction_active = False
