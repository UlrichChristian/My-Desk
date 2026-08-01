"""One-time DB correction: move four canvas projects to Schedule tasks.

Run once: python -m focus_db.fix_projects
Safe to re-run — checks for existing tasks before inserting.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from focus_db.connection import DB_PATH

_REMOVED_PROJECTS = [
    "Eye Recommend — carrier transition (heating up)",
    "Humanacare — remit to",
    "United Cycle",
    "CMRRA",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fix_projects() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = _iso_now()

    for name in _REMOVED_PROJECTS:
        proj = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if not proj:
            continue

        existing = conn.execute(
            "SELECT id FROM tasks WHERE title = ? AND source = 'canvas_import'",
            (name,),
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO tasks
                   (title, status, important, urgent, placed, source, created_on, updated_on)
                   VALUES (?, 'pipeline', 1, 0, 1, 'canvas_import', ?, ?)""",
                (name, now, now),
            )

        linked = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_id = ?", (proj["id"],)
        ).fetchone()[0]
        if linked:
            print(f"SKIP delete {name!r}: {linked} linked task(s)")
            continue

        conn.execute("DELETE FROM projects WHERE id = ?", (proj["id"],))
        print(f"Removed project {name!r}, added Schedule task if needed")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    fix_projects()
