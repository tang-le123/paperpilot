r"""One-off migration: copy all PaperPilot SQLite rows into MySQL.

Usage (PowerShell):
    cd E:\paperpilot\backend
    $env:DB_BACKEND='mysql'
    E:\paperpilot\.venv\Scripts\python.exe scripts\migrate_sqlite_to_mysql.py
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.auth import ensure_auth_tables
from app.config import DB_PATH
from app.db import connect, init_db


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"SQLite DB not found: {DB_PATH}")

    init_db()
    ensure_auth_tables()
    source = sqlite3.connect(DB_PATH)
    source.row_factory = sqlite3.Row

    with closing(source) as sqlite_db, closing(connect()) as mysql:
        for table in ("users", "collections", "papers", "chunks"):
            try:
                rows = sqlite_db.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                print(f"skip missing table: {table}")
                continue
            if not rows:
                print(f"{table}: 0 rows")
                continue
            columns = rows[0].keys()
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(f"`{column}`" for column in columns)
            sql = f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})"
            mysql.executemany(sql, [tuple(row) for row in rows])
            mysql.commit()
            print(f"{table}: {len(rows)} rows")


if __name__ == "__main__":
    main()
