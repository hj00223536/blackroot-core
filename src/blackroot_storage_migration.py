"""Read-only preflight inspection for legacy three-file node storage.

This module never migrates, repairs, checkpoints, or writes source databases.
It is a guardrail for a future separately reviewed migration utility.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote


_REQUIRED_TABLES = {
    "header": {"header_metadata", "headers"},
    "utxo": {
        "metadata", "utxos", "blocks", "block_transactions",
        "block_bodies", "block_undo_spent", "block_undo_created",
    },
    "journal": {"recovery_intent"},
}


def _sha256_file(path: Path) -> str:
    """Hash a potentially large snapshot without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=5.0)
    db.execute("PRAGMA query_only=ON")
    return db


def _schema_inventory(db: sqlite3.Connection) -> dict:
    """Return deterministic SQLite DDL, column, index, and FK metadata.

    This is inspection data for a future reviewed importer; it does not attempt
    to rewrite or normalize schema objects.
    """
    objects = [
        {"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
        for row in db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name, tbl_name"
        )
    ]
    tables = {}
    for item in objects:
        if item["type"] != "table":
            continue
        name = item["name"]
        quoted = '"' + name.replace('"', '""') + '"'
        tables[name] = {
            "create_sql": item["sql"],
            "columns": [
                {
                    "cid": row[0], "name": row[1], "type": row[2],
                    "not_null": bool(row[3]), "default": row[4],
                    "primary_key_position": row[5],
                }
                for row in db.execute(f"PRAGMA table_info({quoted})")
            ],
            "foreign_keys": [
                {
                    "id": row[0], "sequence": row[1],
                    "referenced_table": row[2], "from_column": row[3],
                    "to_column": row[4], "on_update": row[5],
                    "on_delete": row[6], "match": row[7],
                }
                for row in db.execute(f"PRAGMA foreign_key_list({quoted})")
            ],
        }
    return {"objects": objects, "tables": tables}

def _inspect_database(path: Path, kind: str) -> dict:
    try:
        db = _readonly_connection(path)
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot open {kind} database read-only: {path}") from exc
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"{kind} database integrity_check failed: {integrity!r}")
        fk_errors = db.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"{kind} database foreign_key_check failed: {fk_errors!r}")

        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = sorted(_REQUIRED_TABLES[kind] - tables)
        if missing:
            raise RuntimeError(f"{kind} database is missing required tables: {missing}")

        if kind == "header":
            metadata = dict(db.execute("SELECT key, value FROM header_metadata"))
            version = metadata.get("schema_version")
            if version != "1":
                raise RuntimeError(f"unsupported header schema version: {version!r}")
            counts = {
                "headers": db.execute("SELECT COUNT(*) FROM headers").fetchone()[0],
            }
        elif kind == "utxo":
            metadata = dict(db.execute("SELECT key, value FROM metadata"))
            version = metadata.get("schema_version")
            if version != "2":
                raise RuntimeError(f"unsupported UTXO schema version: {version!r}")
            counts = {
                table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in sorted(_REQUIRED_TABLES["utxo"])
            }
        else:
            rows = db.execute(
                "SELECT old_height, old_hash, new_height, new_hash "
                "FROM recovery_intent WHERE singleton=1"
            ).fetchall()
            if len(rows) > 1:
                raise RuntimeError("recovery journal contains multiple pending intents")
            if rows:
                raise RuntimeError(
                    "recovery journal has an unresolved intent; reconcile it before migration"
                )
            version = "unversioned"
            counts = {"pending_intents": 0}

        return {
            "kind": kind,
            "path": str(path),
            "schema_version": version,
            "table_counts": counts,
            "integrity_check": "ok",
            "foreign_key_check": "ok",
            "tables": sorted(tables),
            "schema_inventory": _schema_inventory(db),
        }
    finally:
        db.close()


def inspect_legacy_node_databases(
    header_path: str | Path,
    utxo_path: str | Path,
    recovery_journal_path: str | Path,
) -> dict:
    """Inspect legacy files without changing them; reject aliases and unsafe inputs."""
    supplied = {
        "header": Path(header_path).expanduser().resolve(strict=True),
        "utxo": Path(utxo_path).expanduser().resolve(strict=True),
        "journal": Path(recovery_journal_path).expanduser().resolve(strict=True),
    }
    for kind, path in supplied.items():
        if not path.is_file():
            raise ValueError(f"{kind} database path is not a regular file: {path}")

    items = list(supplied.items())
    for index, (name, path) in enumerate(items):
        for other_name, other_path in items[index + 1:]:
            if path == other_path or path.samefile(other_path):
                raise ValueError(
                    f"{name} and {other_name} source paths refer to the same file"
                )

    reports = {
        kind: _inspect_database(path, kind)
        for kind, path in supplied.items()
    }
    return {
        "status": "preflight_passed",
        "migration_performed": False,
        "source_files_modified": False,
        "databases": reports,
    }



def plan_coordinated_schema_merge(
    header_path: str | Path,
    utxo_path: str | Path,
    recovery_journal_path: str | Path,
) -> dict:
    """Build a deterministic, read-only DDL copy plan for a future importer.

    The plan preserves source CREATE statements and orders tables before their
    same-database FK dependants. It deliberately does not execute DDL or copy
    rows. Name collisions and unsupported schema objects fail closed.
    """
    report = inspect_legacy_node_databases(
        header_path, utxo_path, recovery_journal_path
    )
    inventories = report["databases"]
    object_owners: dict[str, str] = {}
    for kind in ("header", "utxo", "journal"):
        for item in inventories[kind]["schema_inventory"]["objects"]:
            name = item["name"]
            previous = object_owners.get(name)
            if previous is not None:
                raise RuntimeError(
                    f"schema object name collision: {name!r} exists in "
                    f"{previous} and {kind}"
                )
            object_owners[name] = kind
            if item["type"] not in {"table", "index", "trigger", "view"}:
                raise RuntimeError(
                    f"unsupported SQLite schema object type: {item['type']!r}"
                )
            if not item["sql"]:
                raise RuntimeError(
                    f"schema object {name!r} has no reproducible CREATE statement"
                )
            if item["type"] == "table" and item["sql"].lstrip().upper().startswith(
                "CREATE VIRTUAL TABLE"
            ):
                raise RuntimeError(
                    f"virtual table {name!r} is not supported by coordinated schema import"
                )
            if item["type"] == "view":
                raise RuntimeError("views are not yet supported by coordinated schema import")
            if item["type"] == "trigger":
                raise RuntimeError("triggers are not yet supported by coordinated schema import")

    table_owner: dict[str, str] = {}
    table_items: dict[str, dict] = {}
    for kind in ("header", "utxo", "journal"):
        inventory = inventories[kind]["schema_inventory"]
        for name, table in inventory["tables"].items():
            table_owner[name] = kind
            table_items[name] = table

    dependencies: dict[str, set[str]] = {name: set() for name in table_items}
    for name, table in table_items.items():
        for foreign_key in table["foreign_keys"]:
            parent = foreign_key["referenced_table"]
            if parent not in table_items:
                raise RuntimeError(
                    f"table {name!r} references missing table {parent!r}"
                )
            if table_owner[parent] != table_owner[name]:
                raise RuntimeError(
                    f"cross-store foreign key is not supported: {name!r} -> {parent!r}"
                )
            dependencies[name].add(parent)

    ordered_tables: list[str] = []
    remaining = {name: set(parents) for name, parents in dependencies.items()}
    while remaining:
        ready = sorted(name for name, parents in remaining.items() if not parents)
        if not ready:
            raise RuntimeError("cyclic foreign-key dependencies require a reviewed import strategy")
        for name in ready:
            ordered_tables.append(name)
            remaining.pop(name)
        for parents in remaining.values():
            parents.difference_update(ready)

    objects = []
    for name in ordered_tables:
        kind = table_owner[name]
        objects.append({
            "source": kind, "type": "table", "name": name,
            "create_sql": next(
                item["sql"] for item in inventories[kind]["schema_inventory"]["objects"]
                if item["type"] == "table" and item["name"] == name
            ),
        })
    for kind in ("header", "utxo", "journal"):
        for item in inventories[kind]["schema_inventory"]["objects"]:
            if item["type"] == "index":
                objects.append({
                    "source": kind, "type": "index", "name": item["name"],
                    "table": item["table"], "create_sql": item["sql"],
                })

    return {
        "status": "schema_merge_plan_ready",
        "migration_performed": False,
        "source_files_modified": False,
        "table_order": ordered_tables,
        "objects": objects,
        "row_copy_order": ordered_tables,
        "limitations": [
            "no DDL or rows were copied",
            "views and triggers are unsupported",
            "row-copy execution and destination validation remain unimplemented",
            "full transaction, script, and network-consensus validation remain separate gates",
        ],
    }


def import_snapshot_set_to_coordinated_database(
    header_snapshot_path: str | Path,
    utxo_snapshot_path: str | Path,
    recovery_journal_snapshot_path: str | Path,
    destination_path: str | Path,
    *,
    batch_size: int = 512,
) -> dict:
    """Copy a validated three-snapshot set into a new, exclusive SQLite file.

    This creates a staging database only. It preserves table/index CREATE SQL
    and row values, never overwrites a destination, and never writes sources.
    It does not itself authorize production cutover.
    """
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    sources = {
        "header": Path(header_snapshot_path).expanduser().resolve(strict=True),
        "utxo": Path(utxo_snapshot_path).expanduser().resolve(strict=True),
        "journal": Path(recovery_journal_snapshot_path).expanduser().resolve(strict=True),
    }
    destination_arg = Path(destination_path).expanduser()
    parent = destination_arg.parent.resolve(strict=True)
    destination = parent / destination_arg.name
    if not parent.is_dir():
        raise ValueError("destination parent must be an existing directory")
    if destination.exists():
        raise FileExistsError(f"coordinated database destination already exists: {destination}")
    if destination.resolve(strict=False) in sources.values():
        raise ValueError("coordinated destination must differ from every source snapshot")

    # Validate the cross-store state before creating any output file.
    consistency = validate_snapshot_set_consistency(
        sources["header"], sources["utxo"], sources["journal"]
    )
    plan = plan_coordinated_schema_merge(
        sources["header"], sources["utxo"], sources["journal"]
    )
    if any(item["name"] == "blackroot_import_manifest" for item in plan["objects"]):
        raise RuntimeError("source schema uses reserved blackroot_import_manifest name")
    source_hashes = {kind: _sha256_file(path) for kind, path in sources.items()}

    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    target: sqlite3.Connection | None = None
    source_dbs: dict[str, sqlite3.Connection] = {}
    try:
        # Open incrementally so an exception opening a later source does
        # not orphan earlier read-only connections before assignment completes.
        for kind, source_path in sources.items():
            source_dbs[kind] = _readonly_connection(source_path)
        target = sqlite3.connect(str(destination), timeout=10.0)
        target.execute("PRAGMA foreign_keys=ON")
        target.execute("PRAGMA busy_timeout=10000")
        target.execute("PRAGMA synchronous=FULL")
        target.execute("BEGIN IMMEDIATE")

        for item in plan["objects"]:
            if item["type"] == "table":
                target.execute(item["create_sql"])
                source = source_dbs[item["source"]]
                table = item["name"]
                quoted = '"' + table.replace('"', '""') + '"'
                columns = [
                    row[1] for row in source.execute(f"PRAGMA table_info({quoted})")
                ]
                if not columns:
                    raise RuntimeError(f"source table {table!r} has no visible columns")
                quoted_columns = ", ".join(
                    '"' + column.replace('"', '""') + '"' for column in columns
                )
                placeholders = ", ".join("?" for _ in columns)
                insert_sql = (
                    f"INSERT INTO {quoted} ({quoted_columns}) "
                    f"VALUES ({placeholders})"
                )
                cursor = source.execute(f"SELECT {quoted_columns} FROM {quoted}")
                copied = 0
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    target.executemany(insert_sql, rows)
                    copied += len(rows)
                source_count = source.execute(
                    f"SELECT COUNT(*) FROM {quoted}"
                ).fetchone()[0]
                if copied != source_count:
                    raise RuntimeError(
                        f"row-copy count mismatch for {table!r}: {copied} != {source_count}"
                    )
            elif item["type"] == "index":
                target.execute(item["create_sql"])

        target.commit()
        integrity = target.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"staged database integrity_check failed: {integrity!r}")
        fk_errors = target.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"staged database foreign_key_check failed: {fk_errors!r}")

        row_counts = {
            table: target.execute(
                'SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"'
            ).fetchone()[0]
            for table in plan["table_order"]
        }
        for kind, source in source_dbs.items():
            source.close()
        source_dbs.clear()

        # Snapshots are expected to be immutable. Re-hash them after all reads
        # complete so a concurrent external modification cannot silently
        # produce a staging file assembled from mixed source states.
        source_hashes_after = {
            kind: _sha256_file(path) for kind, path in sources.items()
        }
        if source_hashes_after != source_hashes:
            raise RuntimeError("source snapshot changed during staged import")

        # Commit the acceptance marker only after all copy and source checks.
        target.execute("BEGIN IMMEDIATE")
        target.execute("""
            CREATE TABLE blackroot_import_manifest (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                format_version INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status = 'complete'),
                header_sha256 TEXT NOT NULL,
                utxo_sha256 TEXT NOT NULL,
                journal_sha256 TEXT NOT NULL,
                row_counts_json TEXT NOT NULL
            )
        """)
        target.execute(
            "INSERT INTO blackroot_import_manifest VALUES(1, 1, 'complete', ?, ?, ?, ?)",
            (
                source_hashes["header"], source_hashes["utxo"],
                source_hashes["journal"],
                json.dumps(row_counts, sort_keys=True, separators=(",", ":")),
            ),
        )
        target.commit()

        target.close()
        target = None
        return {
            "status": "coordinated_staging_database_created",
            "destination": str(destination),
            "destination_sha256": _sha256_file(destination),
            "source_sha256": source_hashes,
            "row_counts": row_counts,
            "table_order": plan["table_order"],
            "integrity_check": "ok",
            "foreign_key_check": "ok",
            "completion_manifest": "complete",
            "snapshot_consistency": consistency["status"],
            "migration_performed": True,
            "production_cutover_performed": False,
            "source_files_modified": False,
            "limitations": [
                "staging database has not been reopened through PersistentNodeState",
                "full transaction/script validation and independent consensus review remain required",
                "no production cutover or mainnet launch was performed",
            ],
        }
    except BaseException:
        for source in source_dbs.values():
            source.close()
        if target is not None:
            try:
                target.rollback()
            except sqlite3.Error:
                pass
            target.close()
        for candidate in (
            destination, Path(str(destination) + "-wal"),
            Path(str(destination) + "-shm"), Path(str(destination) + "-journal"),
        ):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        raise


def inspect_staged_import_artifact(database_path: str | Path) -> dict:
    """Classify a staging artifact without changing or deleting it.

    A complete manifest means only that the importer reached its completion
    marker. It does not establish consensus validity or production readiness.
    """
    path = Path(database_path).expanduser()
    if not path.exists():
        return {"status": "missing", "database": str(path)}
    if not path.is_file():
        return {"status": "not_regular_file", "database": str(path)}

    try:
        db = _readonly_connection(path.resolve(strict=True))
    except (sqlite3.DatabaseError, OSError, ValueError):
        return {"status": "not_readable_sqlite", "database": str(path)}

    try:
        try:
            integrity = db.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                return {
                    "status": "sqlite_integrity_failed",
                    "database": str(path),
                    "integrity_result": None if integrity is None else integrity[0],
                }
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='blackroot_import_manifest'"
            ).fetchone()
            if not exists:
                return {
                    "status": "incomplete_import_no_manifest",
                    "database": str(path),
                    "integrity_result": "ok",
                }
            rows = db.execute(
                "SELECT format_version, status, header_sha256, utxo_sha256, "
                "journal_sha256, row_counts_json "
                "FROM blackroot_import_manifest WHERE singleton=1"
            ).fetchall()
            if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] != "complete":
                return {
                    "status": "invalid_or_incomplete_manifest",
                    "database": str(path),
                    "integrity_result": "ok",
                }
            for digest in rows[0][2:5]:
                if (
                    not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                ):
                    return {
                        "status": "invalid_or_incomplete_manifest",
                        "database": str(path),
                        "integrity_result": "ok",
                    }
            try:
                counts = json.loads(rows[0][5])
            except (TypeError, json.JSONDecodeError):
                return {
                    "status": "invalid_or_incomplete_manifest",
                    "database": str(path),
                    "integrity_result": "ok",
                }
            if not isinstance(counts, dict) or any(
                not isinstance(name, str) or not isinstance(count, int)
                or isinstance(count, bool) or count < 0
                for name, count in counts.items()
            ):
                return {
                    "status": "invalid_or_incomplete_manifest",
                    "database": str(path),
                    "integrity_result": "ok",
                }
            return {
                "status": "complete_import_manifest_present",
                "database": str(path),
                "integrity_result": "ok",
                "recorded_tables": len(counts),
                "production_validated": False,
            }
        except sqlite3.DatabaseError:
            return {"status": "sqlite_inspection_failed", "database": str(path)}
    finally:
        db.close()


def validate_coordinated_staging_database(
    database_path: str | Path,
    *,
    pow_limit: int,
    genesis,
    require_import_manifest: bool = False,
    verify_manifest_counts: bool = False,
) -> dict:
    """Reopen a staged DB through the real coordinated node stores.

    The caller must supply the expected network parameters from a trusted
    configuration. This function never creates or changes network parameters
    to make a database pass.
    """
    from .blackroot_node_state import PersistentNodeState
    from .blackroot_chain import BlockHeader

    if not isinstance(genesis, BlockHeader):
        raise TypeError("genesis must be a BlockHeader")
    path = Path(database_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("staging database path is not a regular file")

    if verify_manifest_counts and not require_import_manifest:
        raise ValueError("verify_manifest_counts requires require_import_manifest=True")

    if require_import_manifest:
        manifest_db = _readonly_connection(path)
        try:
            exists = manifest_db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='blackroot_import_manifest'"
            ).fetchone()
            if not exists:
                raise RuntimeError("staging database has no completed import manifest")
            rows = manifest_db.execute(
                "SELECT format_version, status, header_sha256, utxo_sha256, "
                "journal_sha256, row_counts_json "
                "FROM blackroot_import_manifest WHERE singleton=1"
            ).fetchall()
            if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] != "complete":
                raise RuntimeError("staging database import manifest is incomplete or invalid")
            for digest in rows[0][2:5]:
                if not isinstance(digest, str) or len(digest) != 64:
                    raise RuntimeError("staging database import manifest has invalid source hashes")
                try:
                    int(digest, 16)
                except ValueError as exc:
                    raise RuntimeError("staging database import manifest has invalid source hashes") from exc
            try:
                counts = json.loads(rows[0][5])
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("staging database import manifest has invalid row counts") from exc
            if not isinstance(counts, dict) or any(
                not isinstance(name, str) or not isinstance(count, int)
                or isinstance(count, bool) or count < 0
                for name, count in counts.items()
            ):
                raise RuntimeError("staging database import manifest has invalid row counts")

            actual_tables = {
                row[0] for row in manifest_db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' "
                    "AND name != 'blackroot_import_manifest'"
                )
            }
            if set(counts) != actual_tables:
                raise RuntimeError(
                    "staging database import manifest table inventory does not match"
                )
            if verify_manifest_counts:
                actual_counts = {}
                for table in sorted(actual_tables):
                    quoted = '"' + table.replace('"', '""') + '"'
                    actual_counts[table] = manifest_db.execute(
                        f"SELECT COUNT(*) FROM {quoted}"
                    ).fetchone()[0]
                if counts != actual_counts:
                    raise RuntimeError(
                        "staging database import manifest row counts do not match"
                    )
        finally:
            manifest_db.close()

    state = PersistentNodeState.open_coordinated(path, pow_limit, genesis)
    try:
        if not state.coordinated:
            raise RuntimeError("staging database did not open in coordinated mode")
        state.utxos.verify_integrity()
        state._verify_persistent_tip()
        pending = state.recovery_journal.pending()
        if pending:
            raise RuntimeError("staging database has an unresolved recovery intent")
        tip = state.utxos.tip()
        best = state.headers.chain.node(state.headers.chain.best_hash)
        if best is None:
            raise RuntimeError("staging header DAG has no best-chain node")
        return {
            "status": "coordinated_node_reopen_passed",
            "database": str(path),
            "coordinated": True,
            "header_height": best.height,
            "header_best_hash": best.header.hash.hex(),
            "utxo_tip": None if tip is None else (tip[0], tip[1].hex()),
            "recovery_intents_pending": 0,
            "migration_performed": False,
            "production_cutover_performed": False,
        }
    finally:
        state.close()


def create_consistent_sqlite_snapshot(
    source_path: str | Path,
    snapshot_path: str | Path,
) -> dict:
    """Create a consistent SQLite backup without writing to the source.

    The destination is created exclusively and is never overwritten. SQLite's
    backup API captures a consistent database image, including committed WAL
    content visible to the read-only source connection.
    """
    source = Path(source_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"source database is not a regular file: {source}")

    requested = Path(snapshot_path).expanduser()
    parent = requested.parent.resolve(strict=True)
    destination = parent / requested.name
    if destination.exists():
        raise FileExistsError(f"snapshot destination already exists: {destination}")
    if destination == source or destination.resolve(strict=False) == source:
        raise ValueError("snapshot destination must differ from source database")

    source_db = None
    snapshot_db = None
    created = False
    try:
        # O_EXCL closes the check-then-create race and reserves only a new path.
        descriptor = os.open(
            destination,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        created = True

        source_uri = f"file:{quote(str(source), safe='/')}?mode=ro"
        source_db = sqlite3.connect(source_uri, uri=True, timeout=10.0)
        source_db.execute("PRAGMA query_only=ON")
        snapshot_db = sqlite3.connect(str(destination), timeout=10.0)
        source_db.backup(snapshot_db, pages=256, sleep=0.05)

        integrity = snapshot_db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"snapshot integrity_check failed: {integrity!r}")
        foreign_key_errors = snapshot_db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"snapshot foreign_key_check failed: {foreign_key_errors!r}"
            )
        table_count = snapshot_db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        page_count = snapshot_db.execute("PRAGMA page_count").fetchone()[0]
        snapshot_db.close()
        snapshot_db = None
        snapshot_sha256 = _sha256_file(destination)
        return {
            "status": "snapshot_created",
            "source": str(source),
            "snapshot": str(destination),
            "source_modified": False,
            "integrity_check": "ok",
            "foreign_key_check": "ok",
            "table_count": table_count,
            "page_count": page_count,
            "snapshot_sha256": snapshot_sha256,
        }
    except BaseException:
        if snapshot_db is not None:
            snapshot_db.close()
            snapshot_db = None
        if created:
            for candidate in (
                destination,
                Path(str(destination) + "-wal"),
                Path(str(destination) + "-shm"),
                Path(str(destination) + "-journal"),
            ):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
        raise
    finally:
        if snapshot_db is not None:
            snapshot_db.close()
        if source_db is not None:
            source_db.close()


def snapshot_legacy_node_databases(
    header_path: str | Path,
    utxo_path: str | Path,
    recovery_journal_path: str | Path,
    snapshot_directory: str | Path,
) -> dict:
    """Preflight and snapshot all legacy stores as separate SQLite databases.

    This is still not a migration: the three snapshots remain separate files.
    The destination directory must already exist and none of the three output
    names may exist. If any step fails, only snapshots created by this call
    are removed.
    """
    source_report = inspect_legacy_node_databases(
        header_path, utxo_path, recovery_journal_path
    )
    directory = Path(snapshot_directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(f"snapshot destination is not a directory: {directory}")

    sources = {
        "header": Path(header_path).expanduser().resolve(strict=True),
        "utxo": Path(utxo_path).expanduser().resolve(strict=True),
        "journal": Path(recovery_journal_path).expanduser().resolve(strict=True),
    }
    destinations = {
        kind: directory / f"blackroot-{kind}-snapshot.sqlite"
        for kind in ("header", "utxo", "journal")
    }

    for kind, destination in destinations.items():
        if destination.exists():
            raise FileExistsError(
                f"{kind} snapshot already exists: {destination}"
            )
        if destination.resolve(strict=False) in sources.values():
            raise ValueError(f"{kind} snapshot aliases a source database")

    created = []
    try:
        reports = {}
        for kind in ("header", "utxo", "journal"):
            reports[kind] = create_consistent_sqlite_snapshot(
                sources[kind], destinations[kind]
            )
            created.append(destinations[kind])

        snapshot_report = validate_snapshot_set_consistency(
            destinations["header"],
            destinations["utxo"],
            destinations["journal"],
        )
        return {
            "status": "snapshots_validated",
            "migration_performed": False,
            "source_files_modified": False,
            "source_preflight": source_report,
            "snapshots": reports,
            "snapshot_preflight": snapshot_report,
        }
    except BaseException:
        for path in created:
            for candidate in (
                path,
                Path(str(path) + "-wal"),
                Path(str(path) + "-shm"),
                Path(str(path) + "-journal"),
            ):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
        raise


def validate_snapshot_set_consistency(
    header_snapshot_path: str | Path,
    utxo_snapshot_path: str | Path,
    recovery_journal_snapshot_path: str | Path,
) -> dict:
    """Cross-check active UTXO block headers against the replay source snapshot.

    This performs structural cross-file checks only. Full consensus replay is
    still performed when opening the staged database with the node stores.
    """
    reports = inspect_legacy_node_databases(
        header_snapshot_path, utxo_snapshot_path, recovery_journal_snapshot_path
    )
    header_path = Path(header_snapshot_path).expanduser().resolve(strict=True)
    utxo_path = Path(utxo_snapshot_path).expanduser().resolve(strict=True)
    from .blackroot_chain import BlockHeader, HeaderChain

    header_db = _readonly_connection(header_path)
    utxo_db = _readonly_connection(utxo_path)
    try:
        header_columns = {
            row[1] for row in header_db.execute("PRAGMA table_info(headers)")
        }
        required_header_columns = {
            "block_hash", "height", "version", "prev_hash", "merkle_root",
            "timestamp", "bits", "nonce",
        }
        if not required_header_columns.issubset(header_columns):
            raise RuntimeError("header snapshot lacks columns required for cross-store validation")

        header_metadata = dict(
            header_db.execute("SELECT key, value FROM header_metadata")
        )
        genesis_hex = header_metadata.get("genesis_hash")
        pow_limit_text = header_metadata.get("pow_limit")
        if not isinstance(genesis_hex, str) or len(genesis_hex) != 64:
            raise RuntimeError("header snapshot has a malformed genesis hash")
        try:
            genesis_hash = bytes.fromhex(genesis_hex)
            pow_limit = int(pow_limit_text)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("header snapshot has malformed network metadata") from exc
        if len(genesis_hash) != 32 or pow_limit <= 0 or str(pow_limit) != pow_limit_text:
            raise RuntimeError("header snapshot has non-canonical network metadata")

        header_rows = header_db.execute(
            "SELECT block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork "
            "FROM headers ORDER BY height, block_hash"
        ).fetchall()
        headers_by_hash = {}
        genesis_header = None
        for row in header_rows:
            block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork = row
            header = BlockHeader(
                version, bytes(prev_hash), bytes(merkle_root), timestamp, bits, nonce
            )
            if header.hash != bytes(block_hash):
                raise RuntimeError("header snapshot contains a header hash mismatch")
            headers_by_hash[bytes(block_hash)] = (height, header.serialize())
            if bytes(block_hash) == genesis_hash:
                genesis_header = header
        if genesis_header is None:
            raise RuntimeError("header snapshot is missing its declared genesis header")
        if genesis_header.prev_hash != bytes(32):
            raise RuntimeError("declared header genesis has a non-zero parent")

        # Replay every stored branch using the same header-DAG consensus checks
        # as PersistentHeaderStore, and compare stored height/work metadata.
        replayed = HeaderChain(pow_limit, genesis_header)
        genesis_work = replayed.node(genesis_hash).chainwork
        genesis_rows = 0
        for row in header_rows:
            block_hash, height, version, prev_hash, merkle_root, timestamp, bits, nonce, chainwork = row
            header = BlockHeader(
                version, bytes(prev_hash), bytes(merkle_root), timestamp, bits, nonce
            )
            block_hash = bytes(block_hash)
            if height == 0:
                genesis_rows += 1
                if block_hash != genesis_hash or str(genesis_work) != str(chainwork):
                    raise RuntimeError("header genesis metadata mismatch during replay")
                continue
            try:
                replayed.add_to_branch(header)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"header snapshot replay rejected {block_hash.hex()}: {exc}"
                ) from exc
            node = replayed.node(block_hash)
            if node is None or node.height != height or str(node.chainwork) != str(chainwork):
                raise RuntimeError("header snapshot height or chainwork mismatch during replay")
        if genesis_rows != 1:
            raise RuntimeError("header snapshot must contain exactly one genesis header")

        genesis_record = headers_by_hash.get(genesis_hash)
        if genesis_record is None or genesis_record[0] != 0:
            raise RuntimeError("header snapshot is missing its declared genesis header")
        genesis_header = BlockHeader(
            *(
                header_db.execute(
                    "SELECT version, prev_hash, merkle_root, timestamp, bits, nonce "
                    "FROM headers WHERE block_hash=?",
                    (genesis_hash,),
                ).fetchone()
            )
        )
        if genesis_header.prev_hash != bytes(32):
            raise RuntimeError("declared header genesis has a non-zero parent")

        block_columns = {
            row[1] for row in utxo_db.execute("PRAGMA table_info(blocks)")
        }
        required_block_columns = {
            "height", "block_hash", "prev_hash", "header",
        }
        if not required_block_columns.issubset(block_columns):
            raise RuntimeError("UTXO snapshot lacks columns required for cross-store validation")

        active_rows = utxo_db.execute(
            "SELECT height, block_hash, prev_hash, header FROM blocks ORDER BY height"
        ).fetchall()
        expected_parent = bytes(32)
        for expected_height, (height, block_hash, prev_hash, raw_header) in enumerate(active_rows):
            block_hash = bytes(block_hash)
            prev_hash = bytes(prev_hash)
            if height != expected_height:
                raise RuntimeError("UTXO active block heights are not contiguous")
            if prev_hash != expected_parent:
                raise RuntimeError("UTXO active block parent linkage is inconsistent")
            header_record = headers_by_hash.get(block_hash)
            if header_record is None:
                raise RuntimeError("active UTXO block is missing from the header snapshot")
            header_height, serialized_header = header_record
            if header_height != height or serialized_header != bytes(raw_header):
                raise RuntimeError("active UTXO block header disagrees with header snapshot")
            if height == 0 and block_hash != bytes.fromhex(
                dict(header_db.execute("SELECT key, value FROM header_metadata"))
                ["genesis_hash"]
            ):
                raise RuntimeError("UTXO genesis does not match header snapshot genesis")
            expected_parent = block_hash

        tip = None if not active_rows else (active_rows[-1][0], bytes(active_rows[-1][1]).hex())
        return {
            "status": "snapshot_set_consistent",
            "migration_performed": False,
            "active_utxo_blocks_checked": len(active_rows),
            "active_utxo_tip": tip,
            "preflight": reports,
        }
    finally:
        header_db.close()
        utxo_db.close()
