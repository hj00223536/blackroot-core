"""SQLite-backed experimental UTXO and block persistence.

Block connection/reorganization calls the block validator, including its
fail-closed supported legacy P2PKH authorization check and coinbase-maturity
checks using persisted UTXO provenance. The standalone ``apply`` helper is
accounting-only. Header/network consensus is only partially delegated to the
experimental HeaderChain wrapper; this is not a production node database.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .blackroot_transactions import OutPoint, Transaction, TxOutput, validate_transaction
from .blackroot_blocks import Block, validate_block_transactions
from .blackroot_chain import HeaderChain
from .blackroot_maturity import UTXOProvenance
from .blackroot_sqlite import SQLiteTransactionConnection
from .blackroot_monetary import TOTAL_SUPPLY_CAP, block_subsidy


def _validate_active_transaction_order(active_transactions: dict[bytes, tuple[int, int, Transaction]]) -> None:
    """Reject active-chain inputs that point to same-or-later transactions."""
    for spending_height, spending_position, spending_tx in active_transactions.values():
        if spending_position == 0:
            continue
        for txin in spending_tx.inputs:
            source = active_transactions.get(txin.previous_output.txid)
            if source is None:
                continue
            source_height, source_position, source_tx = source
            if source_height > spending_height or (
                source_height == spending_height and source_position >= spending_position
            ):
                raise RuntimeError(
                    "active block input references a transaction that is not earlier in chain order"
                )
            if txin.previous_output.index >= len(source_tx.outputs):
                raise RuntimeError("active block spends a nonexistent earlier output")


class UTXOStore:
    SCHEMA_VERSION = 5

    def __init__(
        self,
        path: str | Path,
        *,
        connection: SQLiteTransactionConnection | None = None,
    ):
        self.path = str(path)
        self._external_connection = connection
        if connection is not None and not isinstance(connection, SQLiteTransactionConnection):
            raise TypeError("connection must be a SQLiteTransactionConnection")
        if connection is not None and not connection.in_transaction:
            raise RuntimeError("coordinator-owned UTXO initialization requires an active outer transaction")
        self._initialize()

    def _connect(self):
        if self._external_connection is not None:
            return self._external_connection
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection_scope(self) -> Iterator[sqlite3.Connection | SQLiteTransactionConnection]:
        """Borrow the coordinator connection or own and close a local one."""
        db = self._connect()
        try:
            yield db
        finally:
            if self._external_connection is None:
                db.close()

    def _require_standalone_transaction(self, operation: str) -> None:
        if self._external_connection is not None:
            raise RuntimeError(
                f"{operation} still owns an internal transaction and is not yet "
                "available with a coordinator-owned connection"
            )

    @contextmanager
    def _write_scope(self) -> Iterator[sqlite3.Connection | SQLiteTransactionConnection]:
        """Use an outer transaction when injected; otherwise own one locally."""
        if self._external_connection is not None:
            if not self._external_connection.in_transaction:
                raise RuntimeError("coordinator-owned UTXO writes require an active outer transaction")
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

    def _initialize(self) -> None:
        with self._connection_scope() as db:
            if self._external_connection is None:
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
                    created_height INTEGER NOT NULL DEFAULT 0 CHECK(created_height >= 0),
                    is_coinbase INTEGER NOT NULL DEFAULT 0 CHECK(is_coinbase IN (0, 1)),
                    created_mtp INTEGER CHECK(created_mtp IS NULL OR created_mtp >= 0),
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
                if row[0] == "4":
                    blocks_exist = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blocks'").fetchone()
                    live = db.execute("SELECT COUNT(*) FROM utxos").fetchone()[0]
                    block_count = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] if blocks_exist else 0
                    if live or block_count:
                        raise RuntimeError("schema-v4 migration requires a verified reindex from genesis to reconstruct cumulative issuance")
                    if blocks_exist:
                        db.execute("ALTER TABLE blocks ADD COLUMN subsidy_issued INTEGER NOT NULL DEFAULT 0 CHECK(subsidy_issued >= 0)")
                    db.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (str(self.SCHEMA_VERSION),))
                elif row[0] == "1":
                    blocks_exist = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blocks'").fetchone()
                    live = db.execute("SELECT COUNT(*) FROM utxos").fetchone()[0]
                    block_count = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] if blocks_exist else 0
                    if live or block_count:
                        raise RuntimeError("unsafe schema-v1 migration: non-empty state requires verified reindex from genesis")
                    raise RuntimeError("schema-v1 migration requires an explicit empty-database rebuild")
                elif row[0] == "2":
                    raise RuntimeError("schema-v2 migration requires a verified reindex from genesis to reconstruct UTXO creation MTP")
                elif row[0] == "3":
                    raise RuntimeError("schema-v3 migration requires a verified reindex from genesis to distinguish unknown creation MTP")
                else:
                    raise RuntimeError("unsupported UTXO database schema version")
            # Accounting only: this counter is not a genesis-initialization
            # marker and must never authorize or imply founder issuance.
            bootstrap_row = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()
            if bootstrap_row is None:
                if row is not None and row[0] != "4":
                    raise RuntimeError("schema-v5 database is missing bootstrap issuance metadata")
                db.execute(
                    "INSERT INTO metadata(key, value) VALUES('bootstrap_issued_sats', '0')"
                )
            else:
                try:
                    bootstrap_value = int(bootstrap_row[0])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("bootstrap issuance metadata is malformed") from exc
                if bootstrap_value < 0 or bootstrap_value > TOTAL_SUPPLY_CAP:
                    raise RuntimeError("bootstrap issuance metadata exceeds total supply cap")
            db.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    height INTEGER PRIMARY KEY CHECK(height >= 0),
                    block_hash BLOB NOT NULL UNIQUE CHECK(length(block_hash) = 32),
                    prev_hash BLOB NOT NULL CHECK(length(prev_hash) = 32),
                    header BLOB NOT NULL,
                    tx_count INTEGER NOT NULL CHECK(tx_count > 0),
                    total_fees INTEGER NOT NULL CHECK(total_fees >= 0),
                    subsidy_issued INTEGER NOT NULL CHECK(subsidy_issued >= 0)
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
                CREATE TABLE IF NOT EXISTS block_bodies (
                    block_hash BLOB PRIMARY KEY CHECK(length(block_hash) = 32),
                    raw_block BLOB NOT NULL,
                    serialized_size INTEGER NOT NULL CHECK(serialized_size > 0)
                ) WITHOUT ROWID
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS block_undo_spent (
                    height INTEGER NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
                    txid BLOB NOT NULL CHECK(length(txid) = 32),
                    output_index INTEGER NOT NULL CHECK(output_index >= 0 AND output_index <= 4294967295),
                    value INTEGER NOT NULL CHECK(value >= 0),
                    script_pubkey BLOB NOT NULL,
                    created_height INTEGER NOT NULL CHECK(created_height >= 0),
                    is_coinbase INTEGER NOT NULL CHECK(is_coinbase IN (0, 1)),
                    created_mtp INTEGER CHECK(created_mtp IS NULL OR created_mtp >= 0),
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

            # Closing an owned sqlite3 connection does not commit its transaction.
            # The coordinator-owned connection remains under the outer transaction.
            if self._external_connection is None:
                db.commit()

    def store_block_body(self, block: Block) -> bytes:
        """Persist a candidate block body by header hash for later branch recovery.

        The body must have a matching merkle commitment. Header consensus and
        transaction authorization are checked when the body is connected.
        """
        if not isinstance(block, Block):
            raise TypeError("block must be a Block")
        from .blackroot_transactions import merkle_root
        if merkle_root(tx.txid for tx in block.transactions) != block.header.merkle_root:
            raise ValueError("block body merkle root does not match header")
        raw = block.serialize()
        block_hash = block.header.hash
        # Serialize the read/check/insert sequence against concurrent writers.
        # Deferred transactions otherwise allow multiple processes to observe
        # a missing row before either attempts the INSERT.
        with self._write_scope() as db:
            row = db.execute(
                "SELECT raw_block, serialized_size FROM block_bodies WHERE block_hash=?", (block_hash,)
            ).fetchone()
            if row is not None:
                archived_raw = bytes(row[0])
                if len(archived_raw) != row[1]:
                    raise RuntimeError("archived block body size metadata is corrupt")
                if archived_raw != raw:
                    raise RuntimeError("conflicting archived body for identical block header")
                return block_hash
            db.execute(
                "INSERT INTO block_bodies(block_hash, raw_block, serialized_size) VALUES(?, ?, ?)",
                (block_hash, raw, len(raw)),
            )
        return block_hash

    def discard_block_bodies(self, block_hashes: tuple[bytes, ...]) -> int:
        """Remove archived candidate bodies after branch validation fails."""
        if not isinstance(block_hashes, tuple):
            raise TypeError("block_hashes must be a tuple")
        if any(not isinstance(item, bytes) or len(item) != 32 for item in block_hashes):
            raise ValueError("every block hash must be exactly 32 bytes")
        if not block_hashes:
            return 0
        with self._write_scope() as db:
            before = db.total_changes
            db.executemany(
                "DELETE FROM block_bodies WHERE block_hash=?",
                ((item,) for item in dict.fromkeys(block_hashes)),
            )
            return db.total_changes - before

    def load_block_body(self, block_hash: bytes) -> Block | None:
        """Load and integrity-check a previously archived serialized block body."""
        if not isinstance(block_hash, bytes) or len(block_hash) != 32:
            raise ValueError("block_hash must be exactly 32 bytes")
        with self._connection_scope() as db:
            row = db.execute(
                "SELECT raw_block, serialized_size FROM block_bodies WHERE block_hash=?",
                (block_hash,),
            ).fetchone()
        if row is None:
            return None
        raw = bytes(row[0])
        if len(raw) != row[1]:
            raise RuntimeError("archived block body size metadata is corrupt")
        block = Block.deserialize(raw)
        if block.header.hash != block_hash:
            raise RuntimeError("archived block body header hash does not match archive key")
        from .blackroot_transactions import merkle_root
        if merkle_root(tx.txid for tx in block.transactions) != block.header.merkle_root:
            raise RuntimeError("archived block body merkle root is corrupt")
        return block

    def add_genesis_output(self, outpoint: OutPoint, output: TxOutput) -> None:
        """Insert a trusted bootstrap output; caller must authenticate its origin."""
        if not isinstance(outpoint, OutPoint) or not isinstance(output, TxOutput):
            raise TypeError("expected OutPoint and TxOutput")
        with self._write_scope() as db:
            if db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]:
                raise RuntimeError("bootstrap outputs cannot be added after chain activation")
            bootstrap_row = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()
            if bootstrap_row is None:
                raise RuntimeError("bootstrap issuance metadata is missing")
            try:
                raw_bootstrap_issued = bootstrap_row[0]
                bootstrap_issued = int(raw_bootstrap_issued)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("bootstrap issuance metadata is malformed") from exc
            if (
                not isinstance(raw_bootstrap_issued, str)
                or raw_bootstrap_issued != str(bootstrap_issued)
            ):
                raise RuntimeError("bootstrap issuance metadata is malformed")
            if bootstrap_issued < 0 or bootstrap_issued > TOTAL_SUPPLY_CAP:
                raise RuntimeError("bootstrap issuance metadata exceeds total supply cap")
            if bootstrap_issued + output.value > TOTAL_SUPPLY_CAP:
                raise ValueError("cumulative bootstrap issuance exceeds total supply cap")
            db.execute(
                "INSERT INTO utxos(txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) VALUES(?, ?, ?, ?, 0, 0, NULL)",
                (outpoint.txid, outpoint.index, output.value, output.script_pubkey),
            )
            db.execute(
                "UPDATE metadata SET value=? WHERE key='bootstrap_issued_sats'",
                (str(bootstrap_issued + output.value),),
            )

    def get(self, outpoint: OutPoint) -> TxOutput | None:
        with self._connection_scope() as db:
            row = db.execute(
                "SELECT value, script_pubkey FROM utxos WHERE txid=? AND output_index=?",
                (outpoint.txid, outpoint.index),
            ).fetchone()
        return None if row is None else TxOutput(row[0], bytes(row[1]))

    def count(self) -> int:
        with self._connection_scope() as db:
            return db.execute("SELECT COUNT(*) FROM utxos").fetchone()[0]

    def apply(self, tx: Transaction) -> int:
        """Atomically spend inputs and create outputs; returns fee in atomic units."""
        if not isinstance(tx, Transaction):
            raise TypeError("tx must be a Transaction")
        with self._write_scope() as db:
            if db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]:
                raise RuntimeError("accounting-only apply is disabled after chain activation")
            current: dict[OutPoint, TxOutput] = {}
            for txin in tx.inputs:
                outpoint = txin.previous_output
                row = db.execute(
                    "SELECT value, script_pubkey FROM utxos WHERE txid=? AND output_index=?",
                    (outpoint.txid, outpoint.index),
                ).fetchone()
                if row is not None:
                    current[outpoint] = TxOutput(row[0], bytes(row[1]))
            _, output_total = validate_transaction(tx, current)
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
            return fee

    def verify_integrity(self) -> None:
        """Fail closed on SQLite, relational, transaction-record, or body corruption."""
        with self._connection_scope() as db:
            integrity = db.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise RuntimeError(f"UTXO SQLite integrity check failed: {integrity!r}")
            issued = db.execute("SELECT COALESCE(SUM(subsidy_issued), 0) FROM blocks").fetchone()[0]
            bootstrap_row = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()
            if bootstrap_row is None:
                raise RuntimeError("persisted bootstrap issuance metadata is malformed")
            try:
                raw_bootstrap_issued = bootstrap_row[0]
                bootstrap_issued = int(raw_bootstrap_issued)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("persisted bootstrap issuance metadata is malformed") from exc
            if bootstrap_issued >= 0 and (
                not isinstance(raw_bootstrap_issued, str)
                or raw_bootstrap_issued != str(bootstrap_issued)
            ):
                raise RuntimeError("persisted bootstrap issuance metadata is malformed")
            if bootstrap_issued < 0 or issued < 0 or bootstrap_issued + issued > TOTAL_SUPPLY_CAP:
                raise RuntimeError("persisted cumulative issuance exceeds total supply cap")
            active_block_count = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
            if active_block_count == 0:
                live_bootstrap_value = db.execute(
                    "SELECT COALESCE(SUM(value), 0) FROM utxos"
                ).fetchone()[0]
                if live_bootstrap_value < 0 or live_bootstrap_value > bootstrap_issued:
                    raise RuntimeError(
                        "persisted pre-activation UTXO value exceeds recorded issuance accounting"
                    )
            issuance_rows = db.execute(
                "SELECT height, subsidy_issued FROM blocks ORDER BY height"
            ).fetchall()
            for height, recorded_issuance in issuance_rows:
                expected_issuance = block_subsidy(height)
                if expected_issuance != recorded_issuance:
                    raise RuntimeError("stored per-block subsidy budget does not match consensus schedule")
            blocks = db.execute(
                "SELECT height, block_hash, prev_hash, header, tx_count FROM blocks ORDER BY height"
            ).fetchall()
            # Index every active-chain transaction so live outputs can be
            # checked against their canonical serialized source. Bootstrap
            # outputs are intentionally absent from this index: they predate
            # block history and require a separate authenticated manifest.
            active_transactions: dict[bytes, tuple[int, int, Transaction]] = {}
            spent_history: set[OutPoint] = set()
            expected_parent = bytes(32)
            for expected_height, (height, block_hash, prev_hash, stored_header, tx_count) in enumerate(blocks):
                block_hash = bytes(block_hash)
                prev_hash = bytes(prev_hash)
                if height != expected_height:
                    raise RuntimeError("UTXO active block heights are not contiguous")
                if prev_hash != expected_parent:
                    raise RuntimeError("UTXO active block parent linkage is corrupt")
                if len(bytes(stored_header)) != 80:
                    raise RuntimeError("persisted active block header must be exactly 80 bytes")
                tx_rows = db.execute(
                    "SELECT position, txid, raw_transaction FROM block_transactions "
                    "WHERE height=? ORDER BY position",
                    (height,),
                ).fetchall()
                if len(tx_rows) != tx_count:
                    raise RuntimeError("UTXO active block transaction count is inconsistent")
                from .blackroot_transactions import compact_size
                try:
                    reconstructed = Block.deserialize(
                        bytes(stored_header) + compact_size(len(tx_rows))
                        + b"".join(bytes(row[2]) for row in tx_rows)
                    )
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("persisted active block header/body reconstruction failed") from exc
                if (
                    reconstructed.header.hash != block_hash
                    or reconstructed.header.prev_hash != prev_hash
                ):
                    raise RuntimeError("persisted active block header does not match its chain record")
                from .blackroot_transactions import merkle_root
                if merkle_root(tx.txid for tx in reconstructed.transactions) != reconstructed.header.merkle_root:
                    raise RuntimeError("persisted active block transactions do not match the header merkle root")
                from .blackroot_blocks import is_coinbase
                if (
                    not is_coinbase(reconstructed.transactions[0])
                    or any(is_coinbase(tx) for tx in reconstructed.transactions[1:])
                ):
                    raise RuntimeError("persisted active block coinbase position is invalid")
                for expected_position, (position, txid, raw_transaction) in enumerate(tx_rows):
                    if position != expected_position:
                        raise RuntimeError("UTXO transaction positions are not contiguous")
                    try:
                        tx = Transaction.deserialize(bytes(raw_transaction))
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError("stored active transaction is malformed") from exc
                    if tx.txid != bytes(txid):
                        raise RuntimeError("stored active transaction ID does not match its bytes")
                    if tx.txid in active_transactions:
                        raise RuntimeError("duplicate transaction ID in active transaction history")
                    active_transactions[tx.txid] = (height, position, tx)
                expected_created: set[tuple[bytes, int]] = set()
                for _position, txid, _raw in tx_rows:
                    tx = active_transactions[bytes(txid)][2]
                    expected_created.update(
                        (tx.txid, output_index)
                        for output_index, _output in enumerate(tx.outputs)
                    )
                recorded_created = {
                    (bytes(txid), output_index)
                    for txid, output_index in db.execute(
                        "SELECT txid, output_index FROM block_undo_created WHERE height=?",
                        (height,),
                    ).fetchall()
                }
                if recorded_created != expected_created:
                    raise RuntimeError("persisted block undo-created records do not match active transaction outputs")

                block_inputs: set[OutPoint] = set()
                expected_spent: set[OutPoint] = set()
                for position, txid, _raw in tx_rows:
                    if position == 0:
                        continue
                    tx = active_transactions[bytes(txid)][2]
                    for txin in tx.inputs:
                        previous = txin.previous_output
                        if previous in block_inputs:
                            raise RuntimeError("active block transaction history contains a duplicate spend")
                        block_inputs.add(previous)
                        if previous in spent_history:
                            raise RuntimeError("active transaction history spends an output more than once")
                        source = active_transactions.get(previous.txid)
                        if source is not None:
                            source_height, source_position, source_tx = source
                            if source_height > height or (
                                source_height == height and source_position >= position
                            ):
                                raise RuntimeError("active block input references a transaction that is not earlier in chain order")
                            if previous.index >= len(source_tx.outputs):
                                raise RuntimeError("active block spends a nonexistent earlier output")
                            if source_height < height:
                                expected_spent.add(previous)

                spent_rows = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, "
                    "is_coinbase, created_mtp FROM block_undo_spent WHERE height=?",
                    (height,),
                ).fetchall()
                recorded_spent: set[OutPoint] = set()
                for spent_txid, spent_index, spent_value, spent_script, spent_height, spent_coinbase, spent_mtp in spent_rows:
                    spent_outpoint = OutPoint(bytes(spent_txid), spent_index)
                    if spent_outpoint in recorded_spent or spent_outpoint not in block_inputs:
                        raise RuntimeError("persisted block undo-spent record does not match a block input")
                    recorded_spent.add(spent_outpoint)
                    source = active_transactions.get(spent_outpoint.txid)
                    if source is not None:
                        source_height, _source_position, source_tx = source
                        if source_height >= height or spent_outpoint.index >= len(source_tx.outputs):
                            raise RuntimeError("persisted block undo-spent record references a non-parent output")
                        source_output = source_tx.outputs[spent_outpoint.index]
                        if (
                            spent_value != source_output.value
                            or bytes(spent_script) != source_output.script_pubkey
                            or spent_height != source_height
                            or spent_coinbase != int(_source_position == 0)
                        ):
                            raise RuntimeError("persisted block undo-spent data does not match its source output")
                if not expected_spent.issubset(recorded_spent):
                    raise RuntimeError("persisted block undo-spent records are missing historical inputs")
                spent_history.update(block_inputs)
                expected_parent = block_hash

            # Resolve dependencies again after every active transaction is indexed;
            # otherwise a corrupted earlier block could point into a later block.
            _validate_active_transaction_order(active_transactions)

            archived_bodies = db.execute(
                "SELECT block_hash, raw_block, serialized_size FROM block_bodies"
            ).fetchall()
            from .blackroot_transactions import merkle_root
            for archived_hash, raw_block, serialized_size in archived_bodies:
                archived_hash = bytes(archived_hash)
                raw = bytes(raw_block)
                if len(raw) != serialized_size:
                    raise RuntimeError("archived block body size metadata is corrupt")
                try:
                    archived_block = Block.deserialize(raw)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("archived block body is malformed") from exc
                if archived_block.header.hash != archived_hash:
                    raise RuntimeError("archived block body header hash does not match archive key")
                if merkle_root(tx.txid for tx in archived_block.transactions) != archived_block.header.merkle_root:
                    raise RuntimeError("archived block body merkle root is corrupt")

            # SQLite CHECK constraints are not a substitute for validating
            # persisted UTXO rows: they can be bypassed by a damaged or
            # externally modified database. Validate the consensus-facing
            # fields again during every explicit integrity audit.
            utxo_rows = db.execute(
                "SELECT txid, output_index, value, script_pubkey, created_height, "
                "is_coinbase, created_mtp FROM utxos"
            ).fetchall()
            active_tip = db.execute(
                "SELECT MAX(height) FROM blocks"
            ).fetchone()[0]
            for txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp in utxo_rows:
                if not isinstance(txid, (bytes, bytearray)) or len(txid) != 32:
                    raise RuntimeError("persisted UTXO transaction ID is malformed")
                if not isinstance(output_index, int) or output_index < 0 or output_index > 0xFFFFFFFF:
                    raise RuntimeError("persisted UTXO output index is malformed")
                if not isinstance(value, int) or value < 0 or value > TOTAL_SUPPLY_CAP:
                    raise RuntimeError("persisted UTXO value is malformed")
                if not isinstance(script_pubkey, (bytes, bytearray)):
                    raise RuntimeError("persisted UTXO script is malformed")
                if not isinstance(created_height, int) or created_height < 0:
                    raise RuntimeError("persisted UTXO creation height is malformed")
                if active_tip is not None and created_height > active_tip:
                    raise RuntimeError("persisted UTXO creation height exceeds active tip")
                if not isinstance(is_coinbase, int) or is_coinbase not in (0, 1):
                    raise RuntimeError("persisted UTXO coinbase flag is malformed")
                if created_mtp is not None and (not isinstance(created_mtp, int) or created_mtp < 0):
                    raise RuntimeError("persisted UTXO creation median-time-past is malformed")

                source = active_transactions.get(bytes(txid))
                if source is not None:
                    source_height, source_position, source_tx = source
                    if output_index >= len(source_tx.outputs):
                        raise RuntimeError("persisted UTXO output index is absent from its active transaction")
                    source_output = source_tx.outputs[output_index]
                    if value != source_output.value or bytes(script_pubkey) != source_output.script_pubkey:
                        raise RuntimeError("persisted UTXO output does not match its active transaction")
                    if created_height != source_height or is_coinbase != int(source_position == 0):
                        raise RuntimeError("persisted UTXO provenance does not match its active transaction")

            foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise RuntimeError(
                    f"UTXO SQLite foreign-key check failed: {foreign_key_errors!r}"
                )

    def issued_subsidy(self) -> int:
        """Return cumulative newly issued subsidy on the active persisted chain."""
        with self._connection_scope() as db:
            row = db.execute("SELECT COALESCE(SUM(subsidy_issued), 0) FROM blocks").fetchone()
        return row[0]

    def issued_total(self) -> int:
        """Return all persisted issuance, including trusted pre-chain bootstrap outputs."""
        with self._connection_scope() as db:
            bootstrap = int(db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0])
            subsidy = db.execute(
                "SELECT COALESCE(SUM(subsidy_issued), 0) FROM blocks"
            ).fetchone()[0]
        return bootstrap + subsidy

    def tip(self) -> tuple[int, bytes] | None:
        """Return the stored tip height and hash, or None."""
        with self._connection_scope() as db:
            row = db.execute(
                "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
            ).fetchone()
        return None if row is None else (row[0], bytes(row[1]))


    def block_header(self, height: int) -> bytes | None:
        """Return the exact serialized header persisted at a connected height."""
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise ValueError("height must be a non-negative integer")
        with self._connection_scope() as db:
            row = db.execute(
                "SELECT header FROM blocks WHERE height=?", (height,)
            ).fetchone()
        return None if row is None else bytes(row[0])


    def active_block_headers(self) -> tuple[tuple[int, bytes, bytes, bytes], ...]:
        """Return active-chain header records ordered by height.

        Each entry is (height, block_hash, previous_hash, serialized_header).
        The caller can compare this complete sequence with the validated header DAG.
        """
        with self._connection_scope() as db:
            rows = db.execute(
                "SELECT height, block_hash, prev_hash, header FROM blocks ORDER BY height"
            ).fetchall()
        return tuple(
            (height, bytes(block_hash), bytes(prev_hash), bytes(header))
            for height, block_hash, prev_hash, header in rows
        )


    @staticmethod
    def _advance_provenance(block, parent_provenance, height, created_mtp):
        updated = dict(parent_provenance)
        for tx in block.transactions[1:]:
            for txin in tx.inputs:
                updated.pop(txin.previous_output, None)
            for index, _output in enumerate(tx.outputs):
                updated[OutPoint(tx.txid, index)] = UTXOProvenance(height, False, created_mtp)
        coinbase = block.transactions[0]
        for index, _output in enumerate(coinbase.outputs):
            updated[OutPoint(coinbase.txid, index)] = UTXOProvenance(height, True, created_mtp)
        return updated

    def connect_validated_block(
        self, block: Block, height: int, header_chain: HeaderChain
    ) -> int:
        """Connect one block only when its exact header is on the validated best chain.

        HeaderChain supplies header linkage, proof-of-work, timestamp, and
        difficulty checks. This method additionally binds the body to the
        selected header-chain position before using the persistent UTXO path.
        The caller must still ensure the HeaderChain itself was initialized
        from the intended, independently agreed genesis parameters.
        """
        if not isinstance(header_chain, HeaderChain):
            raise TypeError("header_chain must be a HeaderChain")
        if not isinstance(block, Block):
            raise TypeError("block must be a Block")
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise ValueError("height must be a non-negative integer")
        if height > header_chain.height:
            raise ValueError("block height is above validated header-chain tip")
        selected_header = header_chain.get(height)
        if selected_header.serialize() != block.header.serialize():
            raise ValueError("block header is not the selected validated best-chain header")
        active = self.tip()
        if active is None:
            if height != 0:
                raise ValueError("first validated block must be genesis at height zero")
        elif height != active[0] + 1 or block.header.prev_hash != active[1]:
            raise ValueError("validated block must directly extend persistent active tip")
        parent_mtp = None if height == 0 else header_chain.median_time_past(block.header.prev_hash)
        return self.connect_block(block, height, median_time_past=parent_mtp)

    def connect_block(
        self, block: Block, height: int, *, median_time_past: int | None = None
    ) -> int:
        """Atomically validate and persist a block and its resulting UTXO set.

        This path checks supported block-body rules, legacy P2PKH
        authorization, and coinbase maturity from the stored provenance.
        A supplied median_time_past must be the authenticated MTP of the
        parent header; this low-level method does not authenticate it. It does
        not validate header PoW, difficulty, timestamps, or peer consensus;
        use connect_validated_block with a correctly initialized HeaderChain
        for the prototype header checks.
        """
        if not isinstance(block, Block):
            raise TypeError("block must be a Block")
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise ValueError("height must be a non-negative integer")
        if median_time_past is not None and (
            not isinstance(median_time_past, int)
            or isinstance(median_time_past, bool)
            or median_time_past < 0
        ):
            raise ValueError("median_time_past must be a non-negative integer or None")
        with self._write_scope() as db:
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
            provenance: dict[OutPoint, UTXOProvenance] = {}
            rows = db.execute(
                "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos"
            ).fetchall()
            for txid, index, value, script, created_height, is_coinbase_flag, created_mtp in rows:
                outpoint = OutPoint(bytes(txid), index)
                parent[outpoint] = TxOutput(value, bytes(script))
                provenance[outpoint] = UTXOProvenance(created_height, bool(is_coinbase_flag), created_mtp)

            updated, fees = validate_block_transactions(
                block, parent, height, provenance, median_time_past
            )
            subsidy_issued = block_subsidy(height)
            already_issued = db.execute("SELECT COALESCE(SUM(subsidy_issued), 0) FROM blocks").fetchone()[0]
            bootstrap_issued = int(db.execute("SELECT value FROM metadata WHERE key='bootstrap_issued_sats'").fetchone()[0])
            if bootstrap_issued + already_issued + subsidy_issued > TOTAL_SUPPLY_CAP:
                raise ValueError("cumulative subsidy issuance exceeds total supply cap")
            created_mtp = median_time_past
            updated_provenance = self._advance_provenance(block, provenance, height, created_mtp)
            if set(updated) != set(updated_provenance):
                raise RuntimeError("UTXO/provenance state diverged")

            db.execute(
                "INSERT INTO blocks(height, block_hash, prev_hash, header, tx_count, total_fees, subsidy_issued) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (height, block.header.hash, block.header.prev_hash,
                 block.header.serialize(), len(block.transactions), fees, subsidy_issued),
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
                            "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                            (height, previous.txid, previous.index,
                             spent_output.value, spent_output.script_pubkey,
                             provenance[previous].created_height, int(provenance[previous].is_coinbase),
                              provenance[previous].created_median_time_past),
                        )
            for tx in block.transactions:
                for index, _output in enumerate(tx.outputs):
                    db.execute(
                        "INSERT INTO block_undo_created(height, txid, output_index) VALUES(?, ?, ?)",
                        (height, tx.txid, index),
                    )

            for position, tx in enumerate(block.transactions):
                db.execute(
                    "INSERT INTO block_transactions(height, position, txid, raw_transaction) "
                    "VALUES(?, ?, ?, ?)",
                    (height, position, tx.txid, tx.serialize()),
                )

            db.execute("DELETE FROM utxos")
            db.executemany(
                "INSERT INTO utxos(txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) VALUES(?, ?, ?, ?, ?, ?, ?)",
                [(op.txid, op.index, output.value, output.script_pubkey,
                  updated_provenance[op].created_height,
                  int(updated_provenance[op].is_coinbase),
                  updated_provenance[op].created_median_time_past)
                 for op, output in updated.items()],
            )
        return fees

    def reorganize_to_best(
        self,
        header_chain: HeaderChain,
        replacement_blocks: dict[bytes, Block] | None = None,
    ) -> tuple[int, bytes]:
        """Apply the HeaderChain-selected best branch to this UTXO store, including its deterministic equal-work tie-break.

        The active database tip must already exist in the supplied header DAG.
        Every connecting body must be supplied by its exact header hash and its
        serialized header must match. HeaderChain validates the implemented
        header-level rules; this method validates each replacement body's
        transactions and scripts against authenticated UTXO/provenance state,
        then commits the UTXO switch atomically. Incomplete protocol rules,
        external interoperability, and production consensus review remain
        unresolved; this method does not make this prototype production-ready.
        """
        if not isinstance(header_chain, HeaderChain):
            raise TypeError("header_chain must be a HeaderChain")
        if replacement_blocks is not None and not isinstance(replacement_blocks, dict):
            raise TypeError("replacement_blocks must be a dict or None")
        replacement_blocks = {} if replacement_blocks is None else dict(replacement_blocks)
        active = self.tip()
        if active is None:
            raise ValueError("cannot reorganize an empty UTXO chain")
        active_height, active_hash = active
        active_node = header_chain.node(active_hash)
        if active_node is None or active_node.height != active_height:
            raise ValueError("active database tip is absent or inconsistent in header chain")

        best_hash = header_chain.best_hash
        best_node = header_chain.node(best_hash)
        if best_node is None:
            raise ValueError("header chain has no best tip")
        if best_hash == active_hash or best_node.chainwork < active_node.chainwork:
            return active

        # HeaderChain uses a deterministic hash tie-break when cumulative work
        # is equal. Keep the persistent UTXO tip aligned with that selected
        # branch; refusing equal-work switches here would leave header and UTXO
        # best-chain views inconsistent.
        disconnect_headers, connect_headers = header_chain.reorganization(active_hash)
        if not connect_headers:
            return active

        connect_blocks = []
        for header in connect_headers:
            block = replacement_blocks.get(header.hash)
            if block is None:
                block = self.load_block_body(header.hash)
            if not isinstance(block, Block):
                raise ValueError("missing replacement block body for best-chain header")
            if block.header.serialize() != header.serialize():
                raise ValueError("replacement block header does not match header-chain entry")
            connect_blocks.append(block)

        median_times = tuple(
            None if header.prev_hash == bytes(32)
            else header_chain.median_time_past(header.prev_hash)
            for header in connect_headers
        )
        return self.reorganize(
            tuple(header.hash for header in disconnect_headers),
            tuple(connect_blocks),
            median_time_past_values=median_times,
        )

    def reorganize(
        self,
        disconnect_hashes: tuple[bytes, ...],
        connect_blocks: tuple[Block, ...],
        *,
        median_time_past_values: tuple[int | None, ...] | None = None,
    ) -> tuple[int, bytes] | None:
        """Atomically disconnect an active suffix and connect a replacement.

        disconnect_hashes must be ordered tip-first; connect_blocks must be
        ordered fork-first. Each connecting block's transactions and scripts
        are checked against the authenticated UTXO/provenance snapshot, and any
        failure rolls the entire database reorganization back. This lower-level
        method does not independently establish header ancestry, proof of work,
        difficulty, or greater chainwork; callers must establish those before
        invoking it. Use reorganize_to_best() to select a branch from HeaderChain.
        Remaining protocol rules and production consensus review are incomplete.
        """
        if not isinstance(disconnect_hashes, tuple) or not isinstance(connect_blocks, tuple):
            raise TypeError("disconnect_hashes and connect_blocks must be tuples")
        if not disconnect_hashes and not connect_blocks:
            raise ValueError("reorganization must change at least one block")
        if any(not isinstance(item, bytes) or len(item) != 32 for item in disconnect_hashes):
            raise ValueError("every disconnect hash must be exactly 32 bytes")
        if any(not isinstance(block, Block) for block in connect_blocks):
            raise TypeError("every replacement entry must be a Block")
        if median_time_past_values is not None and (
            not isinstance(median_time_past_values, tuple)
            or len(median_time_past_values) != len(connect_blocks)
        ):
            raise ValueError("median-time-past values must match replacement block count")
        if median_time_past_values is not None and any(
            value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            )
            for value in median_time_past_values
        ):
            raise ValueError("each median-time-past value must be a non-negative integer or None")

        with self._write_scope() as db:
            for expected_hash in disconnect_hashes:
                tip = db.execute(
                    "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
                ).fetchone()
                if tip is None:
                    raise ValueError("disconnect list extends below empty chain")
                height, block_hash = tip[0], bytes(tip[1])
                if block_hash != expected_hash:
                    raise ValueError("disconnect hashes must match active tips in tip-first order")

                # Validate the persisted body and positional index before
                # trusting undo records during a reorganization disconnect.
                block_record = db.execute(
                    "SELECT tx_count, prev_hash, header FROM blocks WHERE height=?",
                    (height,),
                ).fetchone()
                if block_record is None:
                    raise RuntimeError("reorganization active block metadata is missing")
                expected_tx_count, stored_prev_hash, stored_header = (
                    block_record[0], bytes(block_record[1]), bytes(block_record[2])
                )
                positioned_rows = db.execute(
                    "SELECT position, txid, raw_transaction FROM block_transactions "
                    "WHERE height=? ORDER BY position",
                    (height,),
                ).fetchall()
                if len(positioned_rows) != expected_tx_count or not positioned_rows:
                    raise RuntimeError(
                        "reorganization transaction count does not match active block metadata"
                    )
                if any(row[0] != position for position, row in enumerate(positioned_rows)):
                    raise RuntimeError("reorganization transaction positions are not contiguous")
                if len(stored_header) != 80:
                    raise RuntimeError("reorganization stored block header must be exactly 80 bytes")
                from .blackroot_transactions import compact_size, merkle_root
                try:
                    reconstructed = Block.deserialize(
                        stored_header + compact_size(len(positioned_rows))
                        + b"".join(bytes(row[2]) for row in positioned_rows)
                    )
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "reorganization active block reconstruction failed"
                    ) from exc
                if (
                    reconstructed.header.hash != block_hash
                    or reconstructed.header.prev_hash != stored_prev_hash
                    or merkle_root(tx.txid for tx in reconstructed.transactions)
                    != reconstructed.header.merkle_root
                    or any(
                        tx.txid != bytes(row[1])
                        for tx, row in zip(reconstructed.transactions, positioned_rows)
                    )
                ):
                    raise RuntimeError(
                        "reorganization active block header/body commitment is inconsistent"
                    )

                transaction_rows = db.execute(
                    "SELECT txid, raw_transaction FROM block_transactions "
                    "WHERE height=? ORDER BY position",
                    (height,),
                ).fetchall()
                expected_created = set()
                for stored_txid, raw_transaction in transaction_rows:
                    transaction = Transaction.deserialize(bytes(raw_transaction))
                    if transaction.txid != bytes(stored_txid):
                        raise RuntimeError("stored transaction ID does not match reorganization body")
                    expected_created.update(
                        (transaction.txid, index)
                        for index, _output in enumerate(transaction.outputs)
                    )
                created = db.execute(
                    "SELECT txid, output_index FROM block_undo_created WHERE height=?",
                    (height,),
                ).fetchall()
                recorded_created = {(bytes(txid), index) for txid, index in created}
                if recorded_created != expected_created:
                    raise RuntimeError(
                        "reorganization undo-created records do not match stored block transactions"
                    )
                for txid, index in created:
                    db.execute(
                        "DELETE FROM utxos WHERE txid=? AND output_index=?",
                        (txid, index),
                    )
                prior_outputs = {}
                prior_spent = set()
                prior_rows = db.execute(
                    "SELECT bt.txid, bt.raw_transaction, bt.height, bt.position "
                    "FROM block_transactions bt WHERE bt.height<? ORDER BY bt.height, bt.position",
                    (height,),
                ).fetchall()
                for prior_txid, raw_transaction, prior_height, prior_position in prior_rows:
                    prior_tx = Transaction.deserialize(bytes(raw_transaction))
                    if prior_tx.txid != bytes(prior_txid):
                        raise RuntimeError("stored prior transaction ID does not match reorganization history")
                    if prior_position > 0:
                        for txin in prior_tx.inputs:
                            prior_outpoint = (
                                txin.previous_output.txid, txin.previous_output.index
                            )
                            if prior_outpoint in prior_spent:
                                raise RuntimeError(
                                    "stored prior transaction history contains a duplicate spend"
                                )
                            prior_spent.add(prior_outpoint)
                    for output_index, output in enumerate(prior_tx.outputs):
                        prior_outputs[(prior_tx.txid, output_index)] = (
                            output.value, output.script_pubkey, prior_height,
                            int(prior_position == 0),
                        )

                block_inputs = set()
                for txid, raw_transaction in transaction_rows[1:]:
                    transaction = Transaction.deserialize(bytes(raw_transaction))
                    for txin in transaction.inputs:
                        outpoint = (txin.previous_output.txid, txin.previous_output.index)
                        if outpoint in block_inputs or outpoint in prior_spent:
                            raise RuntimeError("reorganization block history contains a duplicate or prior spend")
                        block_inputs.add(outpoint)

                # Recompute creation MTP for outputs whose source transaction is
                # present in the persisted active-chain history. MTP belongs to
                # the source block's parent, not the block that later spends it.
                prior_header_rows = db.execute(
                    "SELECT height, header FROM blocks WHERE height<? ORDER BY height",
                    (height,),
                ).fetchall()
                prior_timestamps = {}
                for prior_header_height, prior_header in prior_header_rows:
                    prior_header = bytes(prior_header)
                    if len(prior_header) != 80:
                        raise RuntimeError("reorganization prior block header must be exactly 80 bytes")
                    prior_timestamps[prior_header_height] = int.from_bytes(
                        prior_header[68:72], "little"
                    )
                if prior_header_rows and (
                    len(prior_header_rows) != prior_header_rows[-1][0] + 1
                    or any(row[0] != index for index, row in enumerate(prior_header_rows))
                ):
                    raise RuntimeError("reorganization prior block header history is not contiguous")

                def expected_creation_mtp(source_height):
                    if source_height == 0:
                        return None
                    parent_height = source_height - 1
                    first_height = max(0, parent_height - 10)
                    required_heights = range(first_height, parent_height + 1)
                    if any(item not in prior_timestamps for item in required_heights):
                        raise RuntimeError("reorganization cannot reconstruct historical creation MTP")
                    timestamps = sorted(prior_timestamps[item] for item in required_heights)
                    return timestamps[len(timestamps) // 2]

                spent = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM block_undo_spent WHERE height=?",
                    (height,),
                ).fetchall()
                recorded_spent = set()
                for txid, index, value, script, created_height, is_coinbase_flag, created_mtp in spent:
                    outpoint = (bytes(txid), index)
                    if outpoint in recorded_spent or outpoint not in block_inputs:
                        raise RuntimeError("reorganization undo-spent records do not match block inputs")
                    recorded_spent.add(outpoint)
                    known_output = prior_outputs.get(outpoint)
                    if known_output is not None:
                        expected_value, expected_script, expected_height, expected_coinbase = known_output
                        expected_mtp = expected_creation_mtp(expected_height)
                        if (
                            value != expected_value or bytes(script) != expected_script
                            or created_height != expected_height
                            or is_coinbase_flag != expected_coinbase
                            or created_mtp != expected_mtp
                        ):
                            raise RuntimeError("reorganization undo-spent data does not match prior transaction output")
                expected_known_spent = (
                    set(prior_outputs).difference(prior_spent).intersection(block_inputs)
                )
                if not expected_known_spent.issubset(recorded_spent):
                    raise RuntimeError("reorganization undo-spent records are missing known historical inputs")

                for txid, index, value, script, created_height, is_coinbase_flag, created_mtp in spent:
                    db.execute(
                        "INSERT INTO utxos(txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (txid, index, value, script, created_height, is_coinbase_flag, created_mtp),
                    )
                db.execute("DELETE FROM blocks WHERE height=?", (height,))

            for block_index, block in enumerate(connect_blocks):
                median_time_past = (
                    None if median_time_past_values is None
                    else median_time_past_values[block_index]
                )
                tip = db.execute(
                    "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
                ).fetchone()
                if tip is None:
                    height = 0
                    if block.header.prev_hash != bytes(32):
                        raise ValueError("replacement genesis must have a zero parent")
                else:
                    height = tip[0] + 1
                    if block.header.prev_hash != bytes(tip[1]):
                        raise ValueError("replacement block does not extend replacement tip")

                parent: dict[OutPoint, TxOutput] = {}
                provenance: dict[OutPoint, UTXOProvenance] = {}
                for txid, index, value, script, created_height, is_coinbase_flag, created_mtp in db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos"
                ).fetchall():
                    outpoint = OutPoint(bytes(txid), index)
                    parent[outpoint] = TxOutput(value, bytes(script))
                    provenance[outpoint] = UTXOProvenance(created_height, bool(is_coinbase_flag), created_mtp)
                updated, fees = validate_block_transactions(
                    block, parent, height, provenance, median_time_past
                )
                subsidy_issued = block_subsidy(height)
                already_issued = db.execute("SELECT COALESCE(SUM(subsidy_issued), 0) FROM blocks").fetchone()[0]
                bootstrap_issued = int(db.execute("SELECT value FROM metadata WHERE key='bootstrap_issued_sats'").fetchone()[0])
                if bootstrap_issued + already_issued + subsidy_issued > TOTAL_SUPPLY_CAP:
                    raise ValueError("cumulative subsidy issuance exceeds total supply cap")
                created_mtp = median_time_past
                updated_provenance = self._advance_provenance(block, provenance, height, created_mtp)
                if set(updated) != set(updated_provenance):
                    raise RuntimeError("UTXO/provenance state diverged")

                db.execute(
                    "INSERT INTO blocks(height, block_hash, prev_hash, header, tx_count, total_fees, subsidy_issued) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (height, block.header.hash, block.header.prev_hash,
                     block.header.serialize(), len(block.transactions), fees, subsidy_issued),
                )
                for tx in block.transactions[1:]:
                    for txin in tx.inputs:
                        previous = txin.previous_output
                        spent_output = parent.get(previous)
                        if spent_output is not None:
                            db.execute(
                                "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                                (height, previous.txid, previous.index,
                                 spent_output.value, spent_output.script_pubkey,
                                 provenance[previous].created_height, int(provenance[previous].is_coinbase),
                                  provenance[previous].created_median_time_past),
                            )
                for tx in block.transactions:
                    for index, _output in enumerate(tx.outputs):
                        db.execute(
                            "INSERT INTO block_undo_created(height, txid, output_index) VALUES(?, ?, ?)",
                            (height, tx.txid, index),
                        )
                for position, tx in enumerate(block.transactions):
                    db.execute(
                        "INSERT INTO block_transactions(height, position, txid, raw_transaction) "
                        "VALUES(?, ?, ?, ?)",
                        (height, position, tx.txid, tx.serialize()),
                    )
                db.execute("DELETE FROM utxos")
                db.executemany(
                    "INSERT INTO utxos(txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    [(op.txid, op.index, output.value, output.script_pubkey,
                      updated_provenance[op].created_height,
                      int(updated_provenance[op].is_coinbase),
                      updated_provenance[op].created_median_time_past)
                     for op, output in updated.items()],
                )

            tip = db.execute(
                "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
            ).fetchone()
            return None if tip is None else (tip[0], bytes(tip[1]))


    def disconnect_tip(self, expected_tip_hash: bytes) -> tuple[int, bytes]:
        """Disconnect exactly the current tip using its recorded UTXO undo data.

        This is a storage primitive, not a complete chain reorganization engine.
        The caller must independently establish that the replacement branch has
        valid consensus, scripts, proof of work, timestamps, and greater chainwork.
        """
        if not isinstance(expected_tip_hash, bytes) or len(expected_tip_hash) != 32:
            raise ValueError("expected_tip_hash must be exactly 32 bytes")

        with self._write_scope() as db:
            tip = db.execute(
                "SELECT height, block_hash, tx_count, prev_hash, header FROM blocks ORDER BY height DESC LIMIT 1"
            ).fetchone()
            if tip is None:
                raise ValueError("cannot disconnect an empty chain")
            height, block_hash, expected_tx_count = tip[0], bytes(tip[1]), tip[2]
            stored_prev_hash, stored_header = bytes(tip[3]), bytes(tip[4])
            if block_hash != expected_tip_hash:
                raise ValueError("expected tip hash does not match stored tip")

            # Validate all inverse records before mutating the live UTXO set.
            # A corrupt undo journal must never be able to mint arbitrary outputs
            # or restore an unrelated outpoint during a tip disconnect.
            transaction_rows = db.execute(
                "SELECT position, txid, raw_transaction FROM block_transactions "
                "WHERE height=? ORDER BY position",
                (height,),
            ).fetchall()
            if len(transaction_rows) != expected_tx_count:
                raise RuntimeError("disconnect undo preflight transaction count does not match active block metadata")
            if not transaction_rows:
                raise RuntimeError("disconnect undo preflight cannot find active block transactions")
            expected_created = set()
            block_inputs = set()
            active_transactions: dict[bytes, tuple[int, int, Transaction]] = {}
            for expected_position, (position, stored_txid, raw_transaction) in enumerate(transaction_rows):
                if position != expected_position:
                    raise RuntimeError("disconnect undo preflight found non-contiguous transaction positions")
                try:
                    transaction = Transaction.deserialize(bytes(raw_transaction))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("disconnect undo preflight found malformed transaction data") from exc
                if transaction.txid != bytes(stored_txid):
                    raise RuntimeError("disconnect undo preflight transaction ID mismatch")
                active_transactions[transaction.txid] = (height, position, transaction)
                expected_created.update(
                    (transaction.txid, index)
                    for index, _output in enumerate(transaction.outputs)
                )
                if position > 0:
                    for txin in transaction.inputs:
                        outpoint = (txin.previous_output.txid, txin.previous_output.index)
                        if outpoint in block_inputs:
                            raise RuntimeError("disconnect undo preflight found duplicate block inputs")
                        block_inputs.add(outpoint)

            # A serialized block header is exactly 80 bytes. Reject malformed
            # persisted data explicitly before Block.deserialize can unpack it.
            if len(stored_header) != 80:
                raise RuntimeError("disconnect undo preflight stored block header must be exactly 80 bytes")

            # Reconstruct the complete persisted block before touching live UTXOs.
            # This binds the stored header/hash/parent to the ordered transaction
            # records and verifies the header's Merkle commitment.
            from .blackroot_transactions import compact_size, merkle_root
            try:
                reconstructed = Block.deserialize(
                    stored_header + compact_size(len(transaction_rows))
                    + b"".join(bytes(row[2]) for row in transaction_rows)
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError("disconnect undo preflight could not reconstruct active block") from exc
            if (
                reconstructed.header.hash != block_hash
                or reconstructed.header.prev_hash != stored_prev_hash
            ):
                raise RuntimeError("disconnect undo preflight block header does not match chain record")
            if merkle_root(tx.txid for tx in reconstructed.transactions) != reconstructed.header.merkle_root:
                raise RuntimeError("disconnect undo preflight block merkle root does not match transactions")

            created = db.execute(
                "SELECT txid, output_index FROM block_undo_created WHERE height=?",
                (height,),
            ).fetchall()
            recorded_created = {(bytes(txid), index) for txid, index in created}
            if recorded_created != expected_created:
                raise RuntimeError("disconnect undo-created records do not match active block outputs")

            prior_outputs = {}
            prior_spent = set()
            prior_rows = db.execute(
                "SELECT bt.txid, bt.raw_transaction, bt.height, bt.position "
                "FROM block_transactions bt WHERE bt.height<? ORDER BY bt.height, bt.position",
                (height,),
            ).fetchall()
            for prior_txid, raw_transaction, prior_height, prior_position in prior_rows:
                try:
                    prior_tx = Transaction.deserialize(bytes(raw_transaction))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("disconnect undo preflight found malformed prior transaction") from exc
                if prior_tx.txid != bytes(prior_txid):
                    raise RuntimeError("disconnect undo preflight prior transaction ID mismatch")
                active_transactions[prior_tx.txid] = (prior_height, prior_position, prior_tx)
                if prior_position > 0:
                    for txin in prior_tx.inputs:
                        outpoint = (txin.previous_output.txid, txin.previous_output.index)
                        if outpoint in prior_spent:
                            raise RuntimeError("disconnect undo preflight found duplicate prior spend")
                        prior_spent.add(outpoint)
                for output_index, output in enumerate(prior_tx.outputs):
                    prior_outputs[(prior_tx.txid, output_index)] = (
                        output.value, output.script_pubkey, prior_height, int(prior_position == 0)
                    )

            # Check dependencies across the entire active prefix plus this tip.
            # A persisted earlier transaction must not be allowed to reference an
            # output created by this (or any later) block before disconnect mutates UTXOs.
            try:
                _validate_active_transaction_order(active_transactions)
            except RuntimeError as exc:
                raise RuntimeError("disconnect undo preflight found invalid active transaction order") from exc

            spent = db.execute(
                "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                "FROM block_undo_spent WHERE height=?",
                (height,),
            ).fetchall()
            recorded_spent = set()
            for txid, index, value, script, created_height, is_coinbase_flag, created_mtp in spent:
                outpoint = (bytes(txid), index)
                if outpoint in recorded_spent or outpoint not in block_inputs:
                    raise RuntimeError("disconnect undo-spent records do not match active block inputs")
                recorded_spent.add(outpoint)
                known_output = prior_outputs.get(outpoint)
                if known_output is not None:
                    expected_value, expected_script, expected_height, expected_coinbase = known_output
                    if (
                        value != expected_value or bytes(script) != expected_script
                        or created_height != expected_height
                        or is_coinbase_flag != expected_coinbase
                    ):
                        raise RuntimeError("disconnect undo-spent data does not match prior transaction output")

            expected_known_spent = set(prior_outputs).difference(prior_spent).intersection(block_inputs)
            if not expected_known_spent.issubset(recorded_spent):
                raise RuntimeError("disconnect undo-spent records are missing known historical inputs")

            for txid, index in created:
                db.execute(
                    "DELETE FROM utxos WHERE txid=? AND output_index=?",
                    (txid, index),
                )

            for txid, index, value, script, created_height, is_coinbase_flag, created_mtp in spent:
                db.execute(
                    "INSERT INTO utxos(txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (txid, index, value, script, created_height, is_coinbase_flag, created_mtp),
                )

            db.execute("DELETE FROM blocks WHERE height=?", (height,))
            return height, block_hash

