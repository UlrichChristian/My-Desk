"""Project CRUD. No Flask imports."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_projects(conn: sqlite3.Connection, *, include_archived: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM projects"
    if not include_archived:
        sql += " WHERE status = 'active'"
    sql += " ORDER BY sort_order, name"
    return conn.execute(sql).fetchall()


def get_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def add_project(conn: sqlite3.Connection, *, name: str, description: str | None = None) -> sqlite3.Row:
    now = _iso_now()
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM projects"
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO projects (name, description, status, sort_order, created_on) "
        "VALUES (?, ?, 'active', ?, ?)",
        (name, description, next_order, now),
    )
    conn.commit()
    return get_project(conn, cur.lastrowid)


def reorder_projects(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    """Assign sort_order by the position of each project id in ordered_ids."""
    now = _iso_now()
    for index, pid in enumerate(ordered_ids):
        conn.execute(
            "UPDATE projects SET sort_order = ? WHERE id = ?", (index, pid)
        )
    conn.commit()


def archive_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("UPDATE projects SET status='archived' WHERE id=?", (project_id,))
    conn.commit()


def project_task_count(conn: sqlite3.Connection, project_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE project_id=? AND status != 'done'",
        (project_id,),
    ).fetchone()[0]
