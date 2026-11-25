"""Node-owned SQLite connection and explicit transaction boundary.

The coordinator exposes a guarded connection facade to stores. Participating
stores may execute SQL but cannot independently commit, roll back, or close
the node-owned connection.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteTransactionCursor:
    """Cursor facade that does not expose its owning raw connection."""

    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def description(self):
        return self._cursor.description

    def __iter__(self):
        return iter(self._cursor)

    def close(self):
        self._cursor.close()


class SQLiteTransactionConnection:
    """Restricted view of a coordinator-owned SQLite connection."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def execute(self, *args, **kwargs):
        return SQLiteTransactionCursor(self._connection.execute(*args, **kwargs))

    def executemany(self, *args, **kwargs):
        return SQLiteTransactionCursor(self._connection.executemany(*args, **kwargs))

    def executescript(self, *args, **kwargs):
        raise RuntimeError(
            "executescript is disabled on a coordinator-owned connection; "
            "it may implicitly commit the outer transaction"
        )

    def cursor(self, *args, **kwargs):
        return SQLiteTransactionCursor(self._connection.cursor(*args, **kwargs))

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
            # Concurrent processes may open a new database simultaneously.
            # journal_mode changes need a database lock and can fail immediately
            # even when busy_timeout is configured, so retry only this transition.
            deadline = time.monotonic() + self.timeout
            while True:
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0].lower()
                if mode == "wal":
                    break
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
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
