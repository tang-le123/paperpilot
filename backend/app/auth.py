"""Local auth: PBKDF2 passwords + short-lived access token + refresh token."""
from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import DB_BACKEND
from app.db import _ensure_column, connect, now_iso

DEMO_USERNAME = os.getenv("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")
ACCESS_TTL_SECONDS = int(os.getenv("ACCESS_TTL_SECONDS", "7200"))
REFRESH_TTL_SECONDS = int(os.getenv("REFRESH_TTL_SECONDS", str(30 * 24 * 3600)))


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000
    ).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def ensure_auth_tables() -> None:
    with closing(connect()) as connection:
        if DB_BACKEND == "mysql":
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    username VARCHAR(64) NOT NULL UNIQUE,
                    salt VARCHAR(64) NOT NULL,
                    password_hash VARCHAR(128) NOT NULL,
                    token_hash VARCHAR(128) NOT NULL UNIQUE,
                    token_expires_at VARCHAR(64) NULL,
                    refresh_hash VARCHAR(128) NULL,
                    refresh_expires_at VARCHAR(64) NULL,
                    created_at VARCHAR(64) NOT NULL
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

                CREATE TABLE IF NOT EXISTS collections (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    name VARCHAR(80) NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    KEY idx_collections_user (user_id)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """
            )
        else:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_expires_at TEXT,
                    refresh_hash TEXT,
                    refresh_expires_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
        _ensure_column(connection, "users", "token_expires_at", "TEXT")
        _ensure_column(connection, "users", "refresh_hash", "TEXT")
        _ensure_column(connection, "users", "refresh_expires_at", "TEXT")
        connection.commit()


def _issue_tokens(connection: Any, user_id: int) -> tuple[str, str, int]:
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(40)
    connection.execute(
        """
        UPDATE users
        SET token_hash = ?, token_expires_at = ?, refresh_hash = ?, refresh_expires_at = ?
        WHERE id = ?
        """,
        (
            _hash_token(access),
            _future(ACCESS_TTL_SECONDS),
            _hash_token(refresh),
            _future(REFRESH_TTL_SECONDS),
            user_id,
        ),
    )
    connection.commit()
    return access, refresh, ACCESS_TTL_SECONDS


def _insert_user(username: str, password: str) -> tuple[int, str, str, int]:
    salt = secrets.token_hex(16)
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(40)
    with closing(connect()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO users
                (username, salt, password_hash, token_hash, token_expires_at,
                 refresh_hash, refresh_expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                salt,
                _hash_password(password, salt),
                _hash_token(access),
                _future(ACCESS_TTL_SECONDS),
                _hash_token(refresh),
                _future(REFRESH_TTL_SECONDS),
                now_iso(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid), access, refresh, ACCESS_TTL_SECONDS


def register(username: str, password: str) -> tuple[int, str, str, int]:
    username = username.strip()
    if len(username) < 2 or len(password) < 6:
        raise ValueError("用户名至少 2 个字符，密码至少 6 位。")
    try:
        user_id, access, refresh, expires = _insert_user(username, password)
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message:
            raise ValueError("用户名已存在。") from exc
        raise
    with closing(connect()) as connection:
        connection.execute(
            "INSERT INTO collections (user_id, name, created_at) VALUES (?, ?, ?)",
            (user_id, "默认集合", now_iso()),
        )
        connection.commit()
    return user_id, access, refresh, expires


def login(username: str, password: str) -> tuple[int, str, str, int] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row is None:
            return None
        expected = _hash_password(password, row["salt"])
        if not secrets.compare_digest(expected, row["password_hash"]):
            return None
        access, refresh, expires = _issue_tokens(connection, int(row["id"]))
        return int(row["id"]), access, refresh, expires


def refresh_access(refresh_token: str) -> tuple[int, str, str, int] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE refresh_hash = ?", (_hash_token(refresh_token),)
        ).fetchone()
        if row is None:
            return None
        expires_at = row["refresh_expires_at"]
        if not expires_at or expires_at <= now_iso():
            return None
        access, refresh, expires = _issue_tokens(connection, int(row["id"]))
        return int(row["id"]), access, refresh, expires


def user_from_token(token: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE token_hash = ?", (_hash_token(token),)
        ).fetchone()
        if row is None:
            return None
        expires_at = row["token_expires_at"]
        if not expires_at or expires_at <= now_iso():
            return None
        return dict(row)


def ensure_default_user() -> int:
    ensure_auth_tables()
    with closing(connect()) as connection:
        row = connection.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if row:
            user_id = int(row["id"])
        else:
            user_id, _, _, _ = _insert_user(DEMO_USERNAME, DEMO_PASSWORD)
            connection.execute(
                "INSERT INTO collections (user_id, name, created_at) VALUES (?, ?, ?)",
                (user_id, "默认集合", now_iso()),
            )
            connection.commit()

        connection.execute(
            "UPDATE papers SET owner_id = ? WHERE owner_id IS NULL", (user_id,)
        )
        connection.execute(
            """
            UPDATE papers
            SET collection_id = (
                SELECT id FROM collections WHERE user_id = ? ORDER BY id LIMIT 1
            )
            WHERE collection_id IS NULL
            """,
            (user_id,),
        )
        connection.commit()
        return user_id
