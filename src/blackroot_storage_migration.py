"""Read-only preflight inspection for legacy three-file node storage.

This module never migrates, repairs, checkpoints, or writes source databases.
It is a guardrail for a future separately reviewed migration utility.
"""
from __future__ import annotations

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


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=5.0)
    db.execute("PRAGMA query_only=ON")
    return db


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
        return {
            "status": "snapshot_created",
            "source": str(source),
            "snapshot": str(destination),
            "source_modified": False,
            "integrity_check": "ok",
            "foreign_key_check": "ok",
            "table_count": table_count,
            "page_count": page_count,
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

        snapshot_report = inspect_legacy_node_databases(
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
