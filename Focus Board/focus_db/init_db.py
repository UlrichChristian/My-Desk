"""Schema creation, category seeding, and one-time canvas migration."""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from focus_db.connection import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'active',
    sort_order  INTEGER DEFAULT 0,
    created_on  TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id),
    color     TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    status       TEXT DEFAULT 'pipeline',
    important    INTEGER DEFAULT 0,
    urgent       INTEGER DEFAULT 0,
    placed       INTEGER DEFAULT 0,
    size         TEXT DEFAULT 'medium',
    category_id  INTEGER REFERENCES categories(id),
    project_id   INTEGER REFERENCES projects(id),
    parent_id    INTEGER REFERENCES tasks(id),
    sort_order   INTEGER DEFAULT 0,
    due_date     TEXT,
    enthusiasm   INTEGER,
    source       TEXT DEFAULT 'manual',
    external_id  TEXT,
    created_on   TEXT,
    updated_on   TEXT,
    completed_on TEXT
);

CREATE TABLE IF NOT EXISTS time_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          INTEGER NOT NULL REFERENCES tasks(id),
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    duration_seconds INTEGER
);
"""

_SEED_CATEGORIES = [
    ("Issues",            None, None, [
        ("Bug Fix",       None),
        ("System Issue",  None),
    ]),
    ("Strategic",         None, None, [
        ("Planning & Policy",   None),
        ("Financial Planning",  None),
        ("Growth",              None),
    ]),
    ("Monthly Recurring", None, None, [
        ("Payroll",    None),
        ("Reporting",  None),
        ("Admin",      None),
    ]),
]

# Canvas task data extracted from My operating canvas.html localStorage (v8)
_CANVAS_TASKS = [
    # Completed wins
    {"title": "Premium payment — booked in QBO + ATB file approved", "bucket": "done", "note": ""},
    {"title": "Tax adjustments — remittance advices (Canada Life, AGI, RBC, Manulife)", "bucket": "done", "note": ""},
    {"title": "Steve's Livestock — prep, meeting & follow-up", "bucket": "done", "note": ""},
    {"title": "GSC ERL — root-caused, forward fix, BD variance sent to carrier", "bucket": "done", "note": ""},
    {"title": "Payroll (EA + ED) — submitted", "bucket": "done", "note": ""},
    {"title": "Review iASM remittance advice", "bucket": "done", "note": ""},
    {"title": "Amend MBC remittance advice", "bucket": "done", "note": ""},
    {"title": "PBC remittance advice — pivot macro built & tested", "bucket": "done", "note": ""},
    {"title": "iASM Volume Breakdown macro — built & tested", "bucket": "done", "note": ""},
    {"title": "Send remittance advice notice email", "bucket": "done", "note": ""},
    {"title": "Send manual bill remittance advices", "bucket": "done", "note": ""},
    {"title": "Payroll App built (BambooHR report pull, Flask + CLI) — moved to C:\\, git-initialized", "bucket": "done", "note": ""},
    # Do Now (Q1: important + urgent)
    {"title": "ISL — email to HUB", "bucket": "do", "note": "carried"},
    {"title": "CMRRA — email", "bucket": "do", "note": "carried"},
    # Schedule (Q2: important + not urgent)
    {"title": "Accounting — trust account reconciliation", "bucket": "sched", "note": "start accounting"},
    {"title": "Accounting — bank recs", "bucket": "sched", "note": ""},
    {"title": "Accounting — booking vacations", "bucket": "sched", "note": ""},
    {"title": "Check 'Equ' 60-day bill in QBO — $25.44 overpaid", "bucket": "sched", "note": "reconcile"},
    {"title": "GSC ERL historical — awaiting GreenShield reply", "bucket": "sched", "note": "BD variance sent 06-24"},
    {"title": "Month-end cluster — confirm status (RBC recs, Book Payroll, Month end)", "bucket": "sched", "note": ""},
    {"title": "Lindsay ASO transition", "bucket": "sched", "note": "was due 06/18"},
    {"title": "Address Updates", "bucket": "sched", "note": "was due 06/12"},
    {"title": "AgSafe — July switch adviser in GB", "bucket": "sched", "note": "due 07/02"},
    {"title": "Reconciliation db update / status quo", "bucket": "sched", "note": ""},
    {"title": "Mirror PBC pivot macro in Process Street — to-do + audit step", "bucket": "sched", "note": "standing automation rule"},
    {"title": "Mirror iASM Volume Breakdown macro in Process Street — to-do + audit step", "bucket": "sched", "note": "standing rule"},
    {"title": "Mirror BambooHR pull (Payroll App) in Process Street — to-do + audit", "bucket": "sched", "note": "standing rule"},
    # Former projects, now Schedule tasks (important + not urgent)
    {"title": "Eye Recommend — carrier transition (heating up)", "bucket": "sched", "note": ""},
    {"title": "Humanacare — remit to", "bucket": "sched", "note": ""},
    {"title": "United Cycle", "bucket": "sched", "note": ""},
    {"title": "CMRRA", "bucket": "sched", "note": ""},
    # Delegate (Q3: not important + urgent)
    {"title": "Dev-team DB query → intern to import", "bucket": "del", "note": "delegated"},
]

_CANVAS_PROJECTS = [
    "Remittance Project — status quo meeting",
    "Travel Policy",
]

_BUCKET_MAP = {
    "do":    {"placed": 1, "status": "pipeline", "important": 1, "urgent": 1},
    "sched": {"placed": 1, "status": "pipeline", "important": 1, "urgent": 0},
    "del":   {"placed": 1, "status": "pipeline", "important": 0, "urgent": 1},
    "later": {"placed": 1, "status": "pipeline", "important": 0, "urgent": 0},
    "done":  {"placed": 1, "status": "done",     "important": 0, "urgent": 0},
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate_schema(conn)
    _seed_categories(conn)
    if conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
        _migrate_canvas(conn)
    conn.commit()
    conn.close()


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Idempotent additive column migrations — safe to call on every connection."""
    task_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "pending_since" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN pending_since TEXT")
    if "is_recurring" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN is_recurring INTEGER DEFAULT 0")
    if "accent_color" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN accent_color TEXT")
    if "procrastinate" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN procrastinate INTEGER DEFAULT 0")
    if "priority_index" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN priority_index INTEGER")

    cat_cols = {row["name"] for row in conn.execute("PRAGMA table_info(categories)")}
    if "frame_style" not in cat_cols:
        conn.execute(
            "ALTER TABLE categories ADD COLUMN frame_style TEXT DEFAULT 'subtle'"
        )

    proj_cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "sort_order" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN sort_order INTEGER DEFAULT 0")

    _backfill_category_colors(conn)
    conn.commit()


def _backfill_category_colors(conn: sqlite3.Connection) -> None:
    """Assign palette colours to parent categories that have none."""
    from focus_services.colors import DEFAULT_COLOR, PARENT_CATEGORY_COLORS

    parents = conn.execute(
        "SELECT id, name, color FROM categories WHERE parent_id IS NULL"
    ).fetchall()
    for row in parents:
        if row["color"]:
            continue
        color = PARENT_CATEGORY_COLORS.get(row["name"], DEFAULT_COLOR)
        conn.execute(
            "UPDATE categories SET color = ? WHERE id = ?",
            (color, row["id"]),
        )
    conn.execute(
        "UPDATE categories SET frame_style = 'subtle' WHERE frame_style IS NULL"
    )


def _migrate_schema(conn: sqlite3.Connection) -> None:
    migrate_schema(conn)


def _seed_categories(conn: sqlite3.Connection) -> None:
    """Idempotent seed — categories has no UNIQUE constraint, so we check
    (name, parent_id) existence before inserting. Safe to run every startup."""
    def _ensure(name: str, parent_id, color):
        if parent_id is None:
            row = conn.execute(
                "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL", (name,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM categories WHERE name = ? AND parent_id = ?",
                (name, parent_id),
            ).fetchone()
        if row:
            return row[0]
        cur = conn.execute(
            "INSERT INTO categories (name, parent_id, color) VALUES (?, ?, ?)",
            (name, parent_id, color),
        )
        return cur.lastrowid

    for parent_name, _, color, children in _SEED_CATEGORIES:
        parent_id = _ensure(parent_name, None, color)
        for child_name, child_color in children:
            _ensure(child_name, parent_id, child_color)
    conn.commit()


def _migrate_canvas(conn: sqlite3.Connection) -> None:
    now = _iso_now()
    # Migrate projects
    for proj_name in _CANVAS_PROJECTS:
        conn.execute(
            "INSERT INTO projects (name, status, created_on) VALUES (?, 'active', ?)",
            (proj_name, now),
        )
    # Migrate tasks
    for i, t in enumerate(_CANVAS_TASKS):
        mapping = _BUCKET_MAP.get(t["bucket"], {"placed": 0, "status": "pipeline", "important": 0, "urgent": 0})
        description = t["note"] if t["note"] else None
        completed_on = now if mapping["status"] == "done" else None
        conn.execute(
            """INSERT INTO tasks
               (title, description, status, important, urgent, placed, sort_order,
                source, created_on, updated_on, completed_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'canvas_import', ?, ?, ?)""",
            (
                t["title"], description,
                mapping["status"], mapping["important"], mapping["urgent"],
                mapping["placed"], i,
                now, now, completed_on,
            ),
        )
    conn.commit()
