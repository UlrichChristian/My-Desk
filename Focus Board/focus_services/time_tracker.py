"""Time tracking — start/stop timer, query active entry. No Flask imports."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_active_entry(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT te.*, t.title AS task_title
           FROM time_entries te
           JOIN tasks t ON t.id = te.task_id
           WHERE te.ended_at IS NULL
           ORDER BY te.id DESC LIMIT 1""",
    ).fetchone()


def start_timer(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    """Start timer on task_id. Auto-stops any currently running timer first."""
    _stop_active(conn)
    now = _iso_now()
    cur = conn.execute(
        "INSERT INTO time_entries (task_id, started_at) VALUES (?, ?)",
        (task_id, now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM time_entries WHERE id=?", (cur.lastrowid,)).fetchone()


def stop_timer(conn: sqlite3.Connection) -> sqlite3.Row | None:
    entry = get_active_entry(conn)
    if entry is None:
        return None
    return _stop_entry(conn, entry["id"], entry["started_at"])


def _stop_active(conn: sqlite3.Connection) -> None:
    entry = get_active_entry(conn)
    if entry:
        _stop_entry(conn, entry["id"], entry["started_at"])


def _stop_entry(conn: sqlite3.Connection, entry_id: int, started_at: str) -> sqlite3.Row:
    now = _iso_now()
    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    ended_dt = datetime.now(timezone.utc)
    duration = int((ended_dt - started_dt).total_seconds())
    conn.execute(
        "UPDATE time_entries SET ended_at=?, duration_seconds=? WHERE id=?",
        (now, duration, entry_id),
    )
    conn.commit()
    return conn.execute("SELECT * FROM time_entries WHERE id=?", (entry_id,)).fetchone()


def total_time_on_task(conn: sqlite3.Connection, task_id: int) -> int:
    """Return total seconds logged on a task (completed entries only)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(duration_seconds), 0) FROM time_entries WHERE task_id=? AND ended_at IS NOT NULL",
        (task_id,),
    ).fetchone()
    return row[0]


def list_entries_for_task(
    conn: sqlite3.Connection, task_id: int, limit: int = 10
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT id, started_at, ended_at, duration_seconds
           FROM time_entries
           WHERE task_id = ? AND ended_at IS NOT NULL
           ORDER BY started_at DESC, id DESC LIMIT ?""",
        (task_id, limit),
    ).fetchall()


def get_entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM time_entries WHERE id = ?", (entry_id,)
    ).fetchone()


def _parse_iso(value: str) -> datetime:
    """Parse an ISO timestamp (accepts trailing 'Z') into an aware UTC datetime."""
    if not value:
        raise ValueError("Missing timestamp.")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _canonical(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_manual_entry(
    conn: sqlite3.Connection, task_id: int, started_at: str, ended_at: str
) -> sqlite3.Row:
    """Insert a completed time entry with explicit start/end (UTC ISO strings).

    Used for retroactive logging when the live timer was not running. Duration is
    derived from the timestamps, matching how live entries are stored.
    """
    start_dt = _parse_iso(started_at)
    end_dt = _parse_iso(ended_at)
    if end_dt <= start_dt:
        raise ValueError("End time must be after start time.")
    duration = int((end_dt - start_dt).total_seconds())
    cur = conn.execute(
        "INSERT INTO time_entries (task_id, started_at, ended_at, duration_seconds) VALUES (?, ?, ?, ?)",
        (task_id, _canonical(start_dt), _canonical(end_dt), duration),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM time_entries WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def update_entry(
    conn: sqlite3.Connection, entry_id: int, started_at: str, ended_at: str
) -> sqlite3.Row | None:
    """Edit an existing entry's start/end (UTC ISO strings); duration recomputed."""
    start_dt = _parse_iso(started_at)
    end_dt = _parse_iso(ended_at)
    if end_dt <= start_dt:
        raise ValueError("End time must be after start time.")
    duration = int((end_dt - start_dt).total_seconds())
    conn.execute(
        "UPDATE time_entries SET started_at=?, ended_at=?, duration_seconds=? WHERE id=?",
        (_canonical(start_dt), _canonical(end_dt), duration, entry_id),
    )
    conn.commit()
    return get_entry(conn, entry_id)


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> bool:
    cur = conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
    conn.commit()
    return cur.rowcount > 0


def elapsed_seconds(started_at: str) -> int:
    """Seconds since a timer started (for live display)."""
    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return int((datetime.now(timezone.utc) - started_dt).total_seconds())
