"""Durable local checkpoint for monotonic trust-configuration transitions.

This SQLite record detects ordinary stale/mismatched updates across restarts.
It is NOT rollback-resistant against an attacker who can restore or replace the
database, its filesystem snapshot, or the host. External authenticated pins
remain mandatory.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS trust_checkpoint (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    network_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    config_digest TEXT NOT NULL,
    previous_config_digest TEXT
)
"""


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")
    return value


class TrustCheckpointStore:
    """Persist one network's latest externally approved trust checkpoint."""

    def __init__(self, path: str | Path, *, timeout: float = 10.0):
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.path = str(Path(path).expanduser())
        self.timeout = float(timeout)
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "TrustCheckpointStore":
        if self._connection is not None:
            raise RuntimeError("trust checkpoint store is already open")
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        try:
            connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(_SCHEMA)
            connection.commit()
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("trust checkpoint store is not open")
        return self._connection

    def initialize(
        self, *, network_id: str, sequence: int, config_digest: str
    ) -> None:
        network = _digest(network_id, "network_id")
        digest = _digest(config_digest, "config_digest")
        if type(sequence) is not int or sequence != 1:
            raise ValueError("initial trust checkpoint sequence must be exactly 1")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT network_id, sequence, config_digest FROM trust_checkpoint WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                raise ValueError("trust checkpoint is already initialized")
            db.execute(
                "INSERT INTO trust_checkpoint "
                "(singleton, network_id, sequence, config_digest, previous_config_digest) "
                "VALUES (1, ?, 1, ?, NULL)",
                (network, digest),
            )
            db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise

    def advance(
        self,
        *,
        network_id: str,
        expected_current_sequence: int,
        expected_current_digest: str,
        new_sequence: int,
        new_config_digest: str,
        new_previous_config_digest: str,
    ) -> None:
        network = _digest(network_id, "network_id")
        current_digest = _digest(expected_current_digest, "expected_current_digest")
        new_digest = _digest(new_config_digest, "new_config_digest")
        predecessor = _digest(new_previous_config_digest, "new_previous_config_digest")
        if type(expected_current_sequence) is not int or expected_current_sequence < 1:
            raise ValueError("expected_current_sequence must be a positive integer")
        if type(new_sequence) is not int or new_sequence != expected_current_sequence + 1:
            raise ValueError("new trust checkpoint sequence must advance by exactly one")
        if new_digest == current_digest:
            raise ValueError("new trust configuration digest must differ from current digest")
        if predecessor != current_digest:
            raise ValueError("new trust configuration predecessor must match current digest")

        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT network_id, sequence, config_digest FROM trust_checkpoint WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise ValueError("trust checkpoint is not initialized")
            stored_network, stored_sequence, stored_digest = row
            if stored_network != network:
                raise ValueError("trust checkpoint network mismatch")
            if stored_sequence != expected_current_sequence or stored_digest != current_digest:
                raise ValueError("trust checkpoint current state mismatch")
            db.execute(
                "UPDATE trust_checkpoint SET sequence = ?, config_digest = ?, "
                "previous_config_digest = ? WHERE singleton = 1",
                (new_sequence, new_digest, predecessor),
            )
            db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise

    def verify_current(
        self, *, network_id: str, expected_sequence: int, expected_config_digest: str
    ) -> None:
        network = _digest(network_id, "network_id")
        digest = _digest(expected_config_digest, "expected_config_digest")
        if type(expected_sequence) is not int or expected_sequence < 1:
            raise ValueError("expected_sequence must be a positive integer")
        row = self._db().execute(
            "SELECT network_id, sequence, config_digest FROM trust_checkpoint WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise ValueError("trust checkpoint is not initialized")
        if row != (network, expected_sequence, digest):
            raise ValueError("trust checkpoint does not match externally pinned current state")

    def current(self) -> tuple[str, int, str, str | None]:
        row = self._db().execute(
            "SELECT network_id, sequence, config_digest, previous_config_digest "
            "FROM trust_checkpoint WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise ValueError("trust checkpoint is not initialized")
        return row
