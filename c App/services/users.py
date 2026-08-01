"""User accounts — CRUD and authentication. No Flask imports; stays testable."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone

_PBKDF2_ROUNDS = 240_000


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, rounds_s, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds_s)
    )
    return hmac.compare_digest(dk.hex(), hash_hex)


def list_users(conn: sqlite3.Connection, *, include_inactive: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM users"
    if not include_inactive:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY display_name, username"
    return conn.execute(sql).fetchall()


def get_user(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()


def authenticate(
    conn: sqlite3.Connection, *, username: str, password: str | None
) -> sqlite3.Row | None:
    """Return user row if credentials are valid, else None.

    A user with no password_hash may sign in by selecting their name with no password.
    """
    user = get_user(conn, username)
    if user is None or not user["is_active"]:
        return None
    if user["password_hash"]:
        if not password or not verify_password(password, user["password_hash"]):
            return None
    return user


def get_user_permissions(conn: sqlite3.Connection, username: str) -> set[str]:
    rows = conn.execute(
        """SELECT p.name FROM permissions p
           JOIN user_permissions up ON up.permission_id = p.id
           JOIN users u ON u.id = up.user_id
           WHERE u.username = ? COLLATE NOCASE""",
        (username,),
    ).fetchall()
    return {r["name"] for r in rows}
