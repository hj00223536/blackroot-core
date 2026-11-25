"""Read-only preflight inspection for legacy three-file node storage.

This module never migrates, repairs, checkpoints, or writes source databases.
It is a guardrail for a future separately reviewed migration utility.
"""
from __future__ import annotations

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
