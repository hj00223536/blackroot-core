"""SQLite-backed UTXO persistence prototype.

This stores outpoints and outputs and applies value-accounting updates in an
SQLite transaction. It does NOT verify scripts/signatures, blocks, coinbase
maturity, or consensus validity. Never expose this as a production node DB.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .blackroot_transactions import OutPoint, Transaction, TxOutput, validate_transaction


class UTXOStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS utxos (
                    txid BLOB NOT NULL CHECK(length(txid) = 32),
                    output_index INTEGER NOT NULL CHECK(output_index >= 0 AND output_index <= 4294967295),
                    value INTEGER NOT NULL CHECK(value >= 0),
                    script_pubkey BLOB NOT NULL,
                    PRIMARY KEY (txid, output_index)
                ) WITHOUT ROWID
            """)
            row = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(self.SCHEMA_VERSION),),
                )
            elif row[0] != str(self.SCHEMA_VERSION):
                raise RuntimeError("unsupported UTXO database schema version")

    def add_genesis_output(self, outpoint: OutPoint, output: TxOutput) -> None:
        """Insert a trusted bootstrap output; caller must authenticate its origin."""
        if not isinstance(outpoint, OutPoint) or not isinstance(output, TxOutput):
            raise TypeError("expected OutPoint and TxOutput")
        with self._connect() as db:
            db.execute(
                "INSERT INTO utxos(txid, output_index, value, script_pubkey) VALUES(?, ?, ?, ?)",
                (outpoint.txid, outpoint.index, output.value, output.script_pubkey),
            )

    def get(self, outpoint: OutPoint) -> TxOutput | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT value, script_pubkey FROM utxos WHERE txid=? AND output_index=?",
                (outpoint.txid, outpoint.index),
            ).fetchone()
        return None if row is None else TxOutput(row[0], bytes(row[1]))

    def count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM utxos").fetchone()[0]

    def apply(self, tx: Transaction) -> int:
        """Atomically spend inputs and create outputs; returns fee in atomic units."""
        if not isinstance(tx, Transaction):
            raise TypeError("tx must be a Transaction")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current: dict[OutPoint, TxOutput] = {}
            for txin in tx.inputs:
                outpoint = txin.previous_output
                row = db.execute(
                    "SELECT value, script_pubkey FROM utxos WHERE txid=? AND output_index=?",
                    (outpoint.txid, outpoint.index),
                ).fetchone()
                if row is not None:
                    current[outpoint] = TxOutput(row[0], bytes(row[1]))
            fee = None
            try:
                _, output_total = validate_transaction(tx, current)
                # Validate the complete transaction before mutating persistent state.
                fee = sum(current[item.previous_output].value for item in tx.inputs) - output_total
                for txin in tx.inputs:
                    cursor = db.execute(
                        "DELETE FROM utxos WHERE txid=? AND output_index=?",
                        (txin.previous_output.txid, txin.previous_output.index),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("input changed during UTXO update")
                for index, output in enumerate(tx.outputs):
                    db.execute(
                        "INSERT INTO utxos(txid, output_index, value, script_pubkey) VALUES(?, ?, ?, ?)",
                        (tx.txid, index, output.value, output.script_pubkey),
                    )
            except Exception:
                db.rollback()
                raise
            db.commit()
            return fee
