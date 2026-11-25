"""SQLite-backed UTXO persistence prototype.

This stores outpoints and outputs and applies value-accounting updates in an
SQLite transaction. It does NOT verify scripts/signatures, blocks, coinbase
maturity, or consensus validity. Never expose this as a production node DB.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .blackroot_transactions import OutPoint, Transaction, TxOutput, validate_transaction
from .blackroot_blocks import Block, validate_block_transactions


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
            db.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    height INTEGER PRIMARY KEY CHECK(height >= 0),
                    block_hash BLOB NOT NULL UNIQUE CHECK(length(block_hash) = 32),
                    prev_hash BLOB NOT NULL CHECK(length(prev_hash) = 32),
                    header BLOB NOT NULL,
                    tx_count INTEGER NOT NULL CHECK(tx_count > 0),
                    total_fees INTEGER NOT NULL CHECK(total_fees >= 0)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS block_transactions (
                    height INTEGER NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK(position >= 0),
                    txid BLOB NOT NULL UNIQUE CHECK(length(txid) = 32),
                    raw_transaction BLOB NOT NULL,
                    PRIMARY KEY(height, position)
                ) WITHOUT ROWID
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS block_undo_spent (
                    height INTEGER NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
                    txid BLOB NOT NULL CHECK(length(txid) = 32),
                    output_index INTEGER NOT NULL CHECK(output_index >= 0 AND output_index <= 4294967295),
                    value INTEGER NOT NULL CHECK(value >= 0),
                    script_pubkey BLOB NOT NULL,
                    PRIMARY KEY(height, txid, output_index)
                ) WITHOUT ROWID
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS block_undo_created (
                    height INTEGER NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
                    txid BLOB NOT NULL CHECK(length(txid) = 32),
                    output_index INTEGER NOT NULL CHECK(output_index >= 0 AND output_index <= 4294967295),
                    PRIMARY KEY(height, txid, output_index)
                ) WITHOUT ROWID
            """)

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

    def tip(self) -> tuple[int, bytes] | None:
        """Return the stored tip height and hash, or None."""
        with self._connect() as db:
            row = db.execute(
                "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
            ).fetchone()
        return None if row is None else (row[0], bytes(row[1]))

    def connect_block(self, block: Block, height: int) -> int:
        """Atomically validate and persist a block and its resulting UTXO set.

        Header PoW, timestamps, scripts, signatures, coinbase maturity and
        chain reorganizations are not checked by this prototype.
        """
        if not isinstance(block, Block):
            raise TypeError("block must be a Block")
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise ValueError("height must be a non-negative integer")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                tip = db.execute(
                    "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
                ).fetchone()
                if tip is None:
                    if height != 0 or block.header.prev_hash != bytes(32):
                        raise ValueError("first block must be height zero with a zero parent")
                else:
                    if height != tip[0] + 1:
                        raise ValueError("block height must directly extend stored tip")
                    if block.header.prev_hash != bytes(tip[1]):
                        raise ValueError("block does not extend stored tip")

                parent: dict[OutPoint, TxOutput] = {}
                rows = db.execute(
                    "SELECT txid, output_index, value, script_pubkey FROM utxos"
                ).fetchall()
                for txid, index, value, script in rows:
                    parent[OutPoint(bytes(txid), index)] = TxOutput(value, bytes(script))

                updated, fees = validate_block_transactions(block, parent, height)

                db.execute(
                    "INSERT INTO blocks(height, block_hash, prev_hash, header, tx_count, total_fees) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (height, block.header.hash, block.header.prev_hash,
                     block.header.serialize(), len(block.transactions), fees),
                )

                # Record inverse operations before committing the new UTXO set.
                # Only inputs present in the parent snapshot are restored on disconnect;
                # outputs created and spent within this same block are not parent UTXOs.
                for tx in block.transactions[1:]:
                    for txin in tx.inputs:
                        previous = txin.previous_output
                        spent_output = parent.get(previous)
                        if spent_output is not None:
                            db.execute(
                                "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey) "
                                "VALUES(?, ?, ?, ?, ?)",
                                (height, previous.txid, previous.index,
                                 spent_output.value, spent_output.script_pubkey),
                            )
                for tx in block.transactions:
                    for index, _output in enumerate(tx.outputs):
                        db.execute(
                            "INSERT INTO block_undo_created(height, txid, output_index) VALUES(?, ?, ?)",
                            (height, tx.txid, index),
                        )

                db.execute(
                    "INSERT INTO blocks(height, block_hash, prev_hash, header, tx_count, total_fees) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (height, block.header.hash, block.header.prev_hash,
                     block.header.serialize(), len(block.transactions), fees),
                )
                for position, tx in enumerate(block.transactions):
                    db.execute(
                        "INSERT INTO block_transactions(height, position, txid, raw_transaction) "
                        "VALUES(?, ?, ?, ?)",
                        (height, position, tx.txid, tx.serialize()),
                    )

                db.execute("DELETE FROM utxos")
                db.executemany(
                    "INSERT INTO utxos(txid, output_index, value, script_pubkey) VALUES(?, ?, ?, ?)",
                    [(op.txid, op.index, output.value, output.script_pubkey)
                     for op, output in updated.items()],
                )
                db.commit()
                return fees
            except Exception:
                db.rollback()
                raise

    def disconnect_tip(self, expected_tip_hash: bytes) -> tuple[int, bytes]:
        """Disconnect exactly the current tip using its recorded UTXO undo data.

        This is a storage primitive, not a complete chain reorganization engine.
        The caller must independently establish that the replacement branch has
        valid consensus, scripts, proof of work, timestamps, and greater chainwork.
        """
        if not isinstance(expected_tip_hash, bytes) or len(expected_tip_hash) != 32:
            raise ValueError("expected_tip_hash must be exactly 32 bytes")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                tip = db.execute(
                    "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
                ).fetchone()
                if tip is None:
                    raise ValueError("cannot disconnect an empty chain")
                height, block_hash = tip[0], bytes(tip[1])
                if block_hash != expected_tip_hash:
                    raise ValueError("expected tip hash does not match stored tip")

                created = db.execute(
                    "SELECT txid, output_index FROM block_undo_created WHERE height=?",
                    (height,),
                ).fetchall()
                for txid, index in created:
                    db.execute(
                        "DELETE FROM utxos WHERE txid=? AND output_index=?",
                        (txid, index),
                    )

                spent = db.execute(
                    "SELECT txid, output_index, value, script_pubkey "
                    "FROM block_undo_spent WHERE height=?",
                    (height,),
                ).fetchall()
                for txid, index, value, script in spent:
                    db.execute(
                        "INSERT INTO utxos(txid, output_index, value, script_pubkey) "
                        "VALUES(?, ?, ?, ?)",
                        (txid, index, value, script),
                    )

                db.execute("DELETE FROM blocks WHERE height=?", (height,))
                db.commit()
                return height, block_hash
            except Exception:
                db.rollback()
                raise
