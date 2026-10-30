"""Metadata store: SQLite by default, MySQL when DB_BACKEND=mysql."""
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from app.config import (
    DB_BACKEND,
    DB_PATH,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(512) NOT NULL,
    filename VARCHAR(512) NOT NULL,
    stored_path VARCHAR(1024) NOT NULL,
    file_type VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    page_count INT NOT NULL DEFAULT 0,
    chunk_count INT NOT NULL DEFAULT 0,
    error TEXT,
    owner_id INT NULL,
    collection_id INT NULL,
    created_at VARCHAR(64) NOT NULL,
    KEY idx_papers_owner (owner_id),
    KEY idx_papers_collection (collection_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
"""

MYSQL_CHUNKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id VARCHAR(64) PRIMARY KEY,
    paper_id INT NOT NULL,
    title VARCHAR(512) NOT NULL DEFAULT '',
    page INT NOT NULL DEFAULT 0,
    section VARCHAR(512) NOT NULL DEFAULT '',
    content LONGTEXT NOT NULL,
    chunk_index INT NOT NULL DEFAULT 0,
    is_reference TINYINT NOT NULL DEFAULT 0,
    KEY idx_chunks_paper (paper_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
"""


class DBConnection:
    """Tiny compatibility layer: sqlite-style ? params and cursors over PyMySQL."""

    def __init__(self, raw: Any, backend: str) -> None:
        self.raw = raw
        self.backend = backend

    def execute(self, sql: str, params: Any = ()):
        if self.backend == "mysql":
            sql = sql.replace("INSERT OR REPLACE", "REPLACE").replace("?", "%s")
            cursor = self.raw.cursor()
            cursor.execute(sql, params)
            return cursor
        return self.raw.execute(sql, params)

    def executemany(self, sql: str, params: Any):
        if self.backend == "mysql":
            sql = sql.replace("INSERT OR REPLACE", "REPLACE").replace("?", "%s")
            cursor = self.raw.cursor()
            cursor.executemany(sql, params)
            return cursor
        return self.raw.executemany(sql, params)

    def executescript(self, script: str) -> None:
        if self.backend == "sqlite":
            self.raw.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self.raw.commit()

    def close(self) -> None:
        self.raw.close()


def _mysql_connect() -> DBConnection:
    import pymysql
    from pymysql.cursors import DictCursor

    if not re.fullmatch(r"[A-Za-z0-9_]+", MYSQL_DATABASE):
        raise ValueError("MYSQL_DATABASE 只能包含字母、数字和下划线")

    kwargs = dict(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        raw = pymysql.connect(database=MYSQL_DATABASE, **kwargs)
    except pymysql.err.OperationalError as exc:
        if not exc.args or exc.args[0] != 1049:
            raise
        server = pymysql.connect(**kwargs)
        try:
            with server.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            server.commit()
        finally:
            server.close()
        raw = pymysql.connect(database=MYSQL_DATABASE, **kwargs)
    return DBConnection(raw, "mysql")


def connect() -> DBConnection:
    if DB_BACKEND == "mysql":
        return _mysql_connect()
    raw = sqlite3.connect(DB_PATH, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA busy_timeout=5000")
    return DBConnection(raw, "sqlite")


def init_db() -> None:
    with closing(connect()) as connection:
        if DB_BACKEND == "mysql":
            connection.executescript(MYSQL_SCHEMA)
            connection.executescript(MYSQL_CHUNKS_SCHEMA)
            _ensure_column(connection, "papers", "owner_id", "INT")
            _ensure_column(connection, "papers", "collection_id", "INT")
        else:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    page_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    paper_id INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    page INTEGER NOT NULL DEFAULT 0,
                    section TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL DEFAULT 0,
                    is_reference INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_paper ON chunks(paper_id);
                """
            )
            _ensure_column(connection, "papers", "owner_id", "INTEGER")
            _ensure_column(connection, "papers", "collection_id", "INTEGER")
        connection.commit()


def _ensure_column(
    connection: DBConnection, table: str, column: str, definition: str
) -> None:
    if connection.backend == "mysql":
        row = connection.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?",
            (MYSQL_DATABASE, table, column),
        ).fetchone()
        if row is None:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return
    columns = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_paper(
    *,
    title: str,
    filename: str,
    stored_path: str,
    file_type: str,
    owner_id: int,
    collection_id: int | None = None,
) -> int:
    with closing(connect()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO papers
                (title, filename, stored_path, file_type, status, owner_id, collection_id, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (title, filename, stored_path, file_type, owner_id, collection_id, now_iso()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def update_paper(paper_id: int, **fields: Any) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [paper_id]
    with closing(connect()) as connection:
        connection.execute(f"UPDATE papers SET {columns} WHERE id = ?", values)
        connection.commit()


def get_paper(paper_id: int) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return dict(row) if row else None


def list_papers(
    owner_id: int | None = None, collection_id: int | None = None
) -> list[dict[str, Any]]:
    conditions = []
    values: list[Any] = []
    if owner_id is not None:
        conditions.append("owner_id = ?")
        values.append(owner_id)
    if collection_id is not None:
        conditions.append("collection_id = ?")
        values.append(collection_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with closing(connect()) as connection:
        rows = connection.execute(
            f"SELECT * FROM papers {where} ORDER BY id DESC", values
        ).fetchall()
        return [dict(row) for row in rows]


def list_collections(user_id: int) -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM collections WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_collection(collection_id: int, user_id: int) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM collections WHERE id = ? AND user_id = ?",
            (collection_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def create_collection(user_id: int, name: str) -> int:
    with closing(connect()) as connection:
        cursor = connection.execute(
            "INSERT INTO collections (user_id, name, created_at) VALUES (?, ?, ?)",
            (user_id, name.strip(), now_iso()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def rename_collection(collection_id: int, user_id: int, name: str) -> bool:
    with closing(connect()) as connection:
        cursor = connection.execute(
            "UPDATE collections SET name = ? WHERE id = ? AND user_id = ?",
            (name.strip(), collection_id, user_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def delete_collection(collection_id: int, user_id: int) -> bool:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT id FROM collections WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        if len(rows) <= 1:
            raise ValueError("至少保留一个论文集合")
        fallback = next(
            (int(row["id"]) for row in rows if int(row["id"]) != collection_id), None
        )
        if fallback is None:
            return False
        connection.execute(
            "UPDATE papers SET collection_id = ? WHERE collection_id = ? AND owner_id = ?",
            (fallback, collection_id, user_id),
        )
        cursor = connection.execute(
            "DELETE FROM collections WHERE id = ? AND user_id = ?",
            (collection_id, user_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def move_paper(paper_id: int, user_id: int, collection_id: int) -> bool:
    with closing(connect()) as connection:
        cursor = connection.execute(
            "UPDATE papers SET collection_id = ? WHERE id = ? AND owner_id = ?",
            (collection_id, paper_id, user_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def delete_paper(paper_id: int) -> None:
    with closing(connect()) as connection:
        connection.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
        connection.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        connection.commit()


def delete_chunks(paper_id: int) -> None:
    with closing(connect()) as connection:
        connection.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
        connection.commit()


def insert_chunks(chunks: list[dict[str, Any]]) -> None:
    if not chunks:
        return
    with closing(connect()) as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO chunks
                (id, paper_id, title, page, section, content, chunk_index, is_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk["id"],
                    chunk["paper_id"],
                    chunk.get("title", ""),
                    chunk["page"],
                    chunk["section"],
                    chunk["content"],
                    chunk["chunk_index"],
                    int(chunk["is_reference"]),
                )
                for chunk in chunks
            ],
        )
        connection.commit()


def get_chunks(paper_ids: list[int], *, include_references: bool = False) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    placeholders = ",".join("?" for _ in paper_ids)
    sql = f"SELECT *, id AS chunk_id FROM chunks WHERE paper_id IN ({placeholders})"
    if not include_references:
        sql += " AND is_reference = 0"
    with closing(connect()) as connection:
        rows = connection.execute(sql, paper_ids).fetchall()
        return [dict(row) for row in rows]


def get_chunk(chunk_id: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT *, id AS chunk_id FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        return dict(row) if row else None


def get_neighbors(
    paper_id: int, chunk_index: int, *, window: int = 1
) -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT *, id AS chunk_id FROM chunks
            WHERE paper_id = ?
              AND is_reference = 0
              AND chunk_index BETWEEN ? AND ?
            ORDER BY chunk_index
            """,
            (paper_id, chunk_index - window, chunk_index + window),
        ).fetchall()
        return [dict(row) for row in rows]


def get_sections(paper_id: int) -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT
                section,
                MIN(page) AS first_page,
                MAX(page) AS last_page,
                COUNT(*) AS chunk_count,
                MIN(chunk_index) AS first_index
            FROM chunks
            WHERE paper_id = ? AND is_reference = 0
            GROUP BY section
            ORDER BY first_index
            """,
            (paper_id,),
        ).fetchall()
        return [dict(row) for row in rows]
