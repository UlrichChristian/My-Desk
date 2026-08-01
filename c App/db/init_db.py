import sqlite3
from datetime import datetime, timezone

from db.connection import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT,
    password_hash TEXT,
    is_active     INTEGER DEFAULT 1,
    created_on    TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    permission_id INTEGER NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (user_id, permission_id)
);
"""

_SEED_PERMISSIONS = [
    ("payroll",      "Access the Payroll App"),
    ("focus", "Access the Focus Board"),
    ("financial",    "Access the Financial Management area"),
    ("knowledge",    "Access the Knowledge journal / logs"),
    ("admin",        "Manage users and permissions"),
]

_FIRST_USER = ("culrich", "Christian Ulrich")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript(_SCHEMA)

    for name, desc in _SEED_PERMISSIONS:
        conn.execute(
            "INSERT OR IGNORE INTO permissions (name, description) VALUES (?, ?)",
            (name, desc),
        )

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, is_active, created_on)"
            " VALUES (?, ?, NULL, 1, ?)",
            (_FIRST_USER[0], _FIRST_USER[1], now),
        )
        conn.commit()
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = ?", (_FIRST_USER[0],)
        ).fetchone()[0]
        for name, _ in _SEED_PERMISSIONS:
            perm_id = conn.execute(
                "SELECT id FROM permissions WHERE name = ?", (name,)
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO user_permissions (user_id, permission_id) VALUES (?, ?)",
                (user_id, perm_id),
            )

    conn.commit()
    conn.close()
