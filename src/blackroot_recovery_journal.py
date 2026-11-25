"""Durable intent journal for coordinating separate header and UTXO stores.

The journal is a write-ahead reconciliation aid, not a cross-database
transaction. It records one expected UTXO-tip transition before the UTXO
transaction commits. On restart, the observed tip must equal either endpoint;
any third state fails closed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


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

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
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

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10.0)
        db.execute("PRAGMA busy_timeout=10000")
        return db

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
        with self._connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
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
                db.commit()
            except Exception:
                db.rollback()
                raise

    def reconcile(self, observed_tip: Tip) -> str:
        """Resolve pending intent against actual UTXO tip; reject third states."""
        _validate_tip(observed_tip, "observed_tip")
        with self._connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT old_height, old_hash, new_height, new_hash "
                    "FROM recovery_intent WHERE singleton=1"
                ).fetchone()
                if row is None:
                    db.commit()
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
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    def pending(self) -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM recovery_intent WHERE singleton=1"
            ).fetchone() is not None
