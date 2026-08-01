"""Task CRUD and queries. No Flask imports."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _active_filter() -> str:
    """SQL fragment excluding recurring templates and archived tasks."""
    return "AND t.is_recurring = 0 AND t.status != 'archived'"


def _task_select() -> str:
    return """SELECT t.*, c.name AS category_name, c.color AS category_color,
                     c.frame_style AS category_frame_style,
                     p.name AS project_name, parent.title AS parent_title
              FROM tasks t
              LEFT JOIN categories c ON c.id = t.category_id
              LEFT JOIN projects p ON p.id = t.project_id
              LEFT JOIN tasks parent ON parent.id = t.parent_id"""


def list_unplaced(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Pipeline list — unplaced tasks without a project or recurring flag."""
    return conn.execute(
        f"""{_task_select()}
           WHERE t.placed = 0 AND t.status = 'pipeline'
             AND t.project_id IS NULL
             {_active_filter()}
           ORDER BY t.sort_order, t.id""",
    ).fetchall()


def list_unplaced_by_project(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Backlog tasks filed under a project (placed=0, status=pipeline)."""
    return conn.execute(
        f"""{_task_select()}
           WHERE t.placed = 0 AND t.status = 'pipeline'
             AND t.project_id IS NOT NULL
             {_active_filter()}
           ORDER BY t.project_id, t.sort_order, t.id""",
    ).fetchall()


def list_by_quadrant(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """Return tasks in the matrix grouped by quadrant key."""
    rows = conn.execute(
        f"""{_task_select()}
           WHERE t.placed = 1 AND t.status = 'pipeline'
             {_active_filter()}
           ORDER BY t.sort_order, t.id""",
    ).fetchall()
    quadrants: dict[str, list] = {"do": [], "sched": [], "del": [], "later": []}
    for row in rows:
        if row["important"] and row["urgent"]:
            quadrants["do"].append(row)
        elif row["important"] and not row["urgent"]:
            quadrants["sched"].append(row)
        elif not row["important"] and row["urgent"]:
            quadrants["del"].append(row)
        else:
            quadrants["later"].append(row)
    return quadrants


def list_in_progress(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"""{_task_select()}
           WHERE t.status = 'in_progress'
             {_active_filter()}
           ORDER BY t.sort_order, t.id""",
    ).fetchall()


def search_tasks(
    conn: sqlite3.Connection, query: str, *, limit: int = 15
) -> list[sqlite3.Row]:
    """Find active tasks by title/description substring match (all query words must match)."""
    import re

    q = query.strip()
    if not q:
        return []
    words = [w for w in re.split(r"\s+", q) if w]
    clauses = [
        "COALESCE(t.is_recurring, 0) = 0",
        "t.status NOT IN ('archived', 'done')",
    ]
    params: list[str] = []
    for word in words:
        like = f"%{word}%"
        clauses.append(
            "(t.title LIKE ? COLLATE NOCASE"
            " OR COALESCE(t.description, '') LIKE ? COLLATE NOCASE)"
        )
        params.extend([like, like])
    rows = conn.execute(
        f"""{_task_select()}
           WHERE {" AND ".join(clauses)}
           ORDER BY t.sort_order, t.id""",
        params,
    ).fetchall()
    ql = q.lower()

    def _rank(row: sqlite3.Row) -> tuple[int, int]:
        title = (row["title"] or "").lower()
        if title == ql:
            return (0, row["id"])
        if ql in title:
            return (1, row["id"])
        if title.startswith(ql):
            return (2, row["id"])
        return (3, row["id"])

    return sorted(rows, key=_rank)[:limit]


def list_recently_completed(conn: sqlite3.Connection, n: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT t.*, c.name AS category_name
           FROM tasks t
           LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.status = 'done'
           ORDER BY t.completed_on DESC LIMIT ?""",
        (n,),
    ).fetchall()


def list_recurring_templates(conn: sqlite3.Connection) -> list[dict]:
    """Recurring template roots with nested subtasks."""
    roots = conn.execute(
        f"""{_task_select()}
           WHERE t.is_recurring = 1 AND t.parent_id IS NULL AND t.status != 'archived'
           ORDER BY t.sort_order, t.id""",
    ).fetchall()
    result = []
    for root in roots:
        subtasks = conn.execute(
            f"""{_task_select()}
               WHERE t.is_recurring = 1 AND t.parent_id = ? AND t.status != 'archived'
               ORDER BY t.sort_order, t.id""",
            (root["id"],),
        ).fetchall()
        result.append({"root": root, "subtasks": subtasks})
    return result


def list_top_level_tasks(
    conn: sqlite3.Connection, exclude_id: int | None = None
) -> list[sqlite3.Row]:
    """Active top-level tasks for the 'Subtask of' picker."""
    sql = f"""SELECT t.id, t.title FROM tasks t
           WHERE t.parent_id IS NULL AND t.status != 'done'
             {_active_filter()}"""
    params: list[int] = []
    if exclude_id:
        sql += " AND t.id != ?"
        params.append(exclude_id)
    sql += " ORDER BY t.title"
    return conn.execute(sql, params).fetchall()


def list_recurring_roots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Recurring template roots for the quick-add parent picker."""
    return conn.execute(
        """SELECT t.id, t.title FROM tasks t
           WHERE t.is_recurring = 1 AND t.parent_id IS NULL AND t.status != 'archived'
           ORDER BY t.title""",
    ).fetchall()


def find_recurring_root_by_title(conn: sqlite3.Connection, title: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM tasks
           WHERE is_recurring = 1 AND parent_id IS NULL AND title = ?
             AND status != 'archived'
           LIMIT 1""",
        (title,),
    ).fetchone()


def resolve_recurring_parent(
    conn: sqlite3.Connection, parent_id: int | None, *, is_recurring: bool
) -> tuple[int | None, str | None]:
    """Resolve parent for a recurring subtask. Returns (parent_id, redirect_note)."""
    if not is_recurring or parent_id is None:
        return parent_id, None

    parent = get_task(conn, parent_id)
    if not parent:
        return parent_id, None

    if parent["is_recurring"] and not parent["parent_id"]:
        return parent_id, None

    if parent["is_recurring"] and parent["parent_id"]:
        return parent["parent_id"], None

    match = find_recurring_root_by_title(conn, parent["title"])
    if match:
        return match["id"], f"Attached to recurring template «{match['title']}»."

    raise ValueError(
        "Recurring subtasks must attach to a Recurring template. "
        f"No recurring template found for «{parent['title']}»."
    )


def placement_from_recurring_root(
    conn: sqlite3.Connection,
    root_id: int,
    *,
    important: int,
    urgent: int,
    placed: int,
) -> tuple[int, int, int]:
    """Default important/urgent/placed from a recurring template root."""
    root = get_task(conn, root_id)
    if not root or not root["is_recurring"]:
        return important, urgent, placed
    if not important and not urgent:
        important = root["important"]
        urgent = root["urgent"]
    if important or urgent:
        placed = 1
    elif not placed:
        placed = root["placed"]
    return important, urgent, placed


def list_parent_task_options(
    conn: sqlite3.Connection,
    *,
    exclude_task_id: int | None = None,
    for_recurring: bool = False,
    current_parent_id: int | None = None,
) -> list[sqlite3.Row]:
    """Eligible parent tasks for the edit-form picker."""
    if for_recurring:
        sql = """SELECT t.id, t.title FROM tasks t
                 WHERE t.is_recurring = 1 AND t.parent_id IS NULL
                   AND t.status != 'archived'"""
        params: list[int] = []
    else:
        sql = f"""SELECT t.id, t.title FROM tasks t
                  WHERE t.parent_id IS NULL AND t.status NOT IN ('done', 'archived')
                    {_active_filter()}"""
        params = []
    if exclude_task_id:
        sql += " AND t.id != ?"
        params.append(exclude_task_id)
    sql += " ORDER BY t.title"
    options = conn.execute(sql, params).fetchall()
    if current_parent_id and not any(r["id"] == current_parent_id for r in options):
        parent = get_task(conn, current_parent_id)
        if parent:
            options = [parent, *options]
    return options


def get_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def get_task_detail(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"{_task_select()} WHERE t.id = ?",
        (task_id,),
    ).fetchone()


def get_subtasks(conn: sqlite3.Connection, parent_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tasks WHERE parent_id = ? ORDER BY sort_order, id",
        (parent_id,),
    ).fetchall()


def subtask_progress(conn: sqlite3.Connection, parent_id: int) -> tuple[int, int]:
    """Return (done_count, total_count) for subtasks of parent_id."""
    rows = get_subtasks(conn, parent_id)
    total = len(rows)
    done = sum(1 for r in rows if r["status"] == "done")
    return done, total


def subtasks_remaining(conn: sqlite3.Connection, parent_id: int) -> int:
    """Count of subtasks not yet done."""
    return conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE parent_id = ? AND status != 'done'",
        (parent_id,),
    ).fetchone()[0]


def project_task_counts(conn: sqlite3.Connection, project_id: int) -> tuple[int, int]:
    """Return (done_count, total_count) for all tasks linked to a project."""
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done,
             COUNT(*) AS total
           FROM tasks WHERE project_id = ?""",
        (project_id,),
    ).fetchone()
    return (row["done"] or 0, row["total"] or 0)


def projects_aggregate_counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return (done, total) across all project-linked tasks."""
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done,
             COUNT(*) AS total
           FROM tasks WHERE project_id IS NOT NULL""",
    ).fetchone()
    return (row["done"] or 0, row["total"] or 0)


def get_or_create_category(
    conn: sqlite3.Connection,
    name: str,
    parent_id: int | None,
    *,
    color: str | None = None,
    frame_style: str = "subtle",
) -> int:
    """Idempotent: return existing or insert new category (parent or sub)."""
    from focus_services.colors import DEFAULT_COLOR

    name = name.strip()
    if not name:
        raise ValueError("Category name required")
    if parent_id is None:
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL",
            (name,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id = ?",
            (name, parent_id),
        ).fetchone()
    if row:
        return row["id"]
    if color is None:
        color = DEFAULT_COLOR if parent_id is None else None
    cur = conn.execute(
        "INSERT INTO categories (name, parent_id, color, frame_style) VALUES (?, ?, ?, ?)",
        (name, parent_id, color, frame_style if parent_id is None else "subtle"),
    )
    conn.commit()
    return cur.lastrowid


def update_category(
    conn: sqlite3.Connection,
    category_id: int,
    *,
    color: str | None = None,
    frame_style: str | None = None,
) -> None:
    updates = {}
    if color is not None:
        updates["color"] = color
    if frame_style is not None:
        updates["frame_style"] = frame_style
    if not updates:
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE categories SET {cols} WHERE id=?",
        (*updates.values(), category_id),
    )
    conn.commit()


def get_category(conn: sqlite3.Connection, category_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM categories WHERE id = ?", (category_id,)
    ).fetchone()


def list_archived_tasks(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        f"""{_task_select()}
           WHERE t.status = 'archived' AND COALESCE(t.is_recurring, 0) = 0
           ORDER BY t.updated_on DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def add_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str | None = None,
    important: int = 0,
    urgent: int = 0,
    placed: int = 0,
    size: str = "medium",
    category_id: int | None = None,
    project_id: int | None = None,
    parent_id: int | None = None,
    due_date: str | None = None,
    source: str = "manual",
    external_id: str | None = None,
    is_recurring: int = 0,
    pending_since: str | None = None,
) -> sqlite3.Row:
    now = _iso_now()
    if pending_since is None and placed and not urgent:
        pending_since = now
    cur = conn.execute(
        """INSERT INTO tasks
           (title, description, status, important, urgent, placed, size,
            category_id, project_id, parent_id, due_date, source, external_id,
            is_recurring, pending_since, created_on, updated_on)
           VALUES (?, ?, 'pipeline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, important, urgent, placed, size,
         category_id, project_id, parent_id, due_date, source, external_id,
         is_recurring, pending_since, now, now),
    )
    conn.commit()
    return get_task(conn, cur.lastrowid)


def place_task(
    conn: sqlite3.Connection, task_id: int, important: int, urgent: int
) -> None:
    now = _iso_now()
    if urgent:
        pending_since = None
    else:
        pending_since = (
            conn.execute(
                "SELECT COALESCE(pending_since, ?) FROM tasks WHERE id = ?",
                (now, task_id),
            ).fetchone()[0]
        )
    conn.execute(
        """UPDATE tasks
           SET placed=1, important=?, urgent=?, status='pipeline',
               pending_since=?, updated_on=?
           WHERE id=?""",
        (important, urgent, pending_since, now, task_id),
    )
    conn.commit()


def move_to_in_progress(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute(
        "UPDATE tasks SET status='in_progress', placed=1, updated_on=? WHERE id=?",
        (_iso_now(), task_id),
    )
    conn.commit()


def complete_task(conn: sqlite3.Connection, task_id: int, enthusiasm: int | None = None) -> None:
    now = _iso_now()
    conn.execute(
        """UPDATE tasks SET status='done', enthusiasm=?, completed_on=?, updated_on=?,
           priority_index=NULL WHERE id=?""",
        (enthusiasm, now, now, task_id),
    )
    conn.commit()


def move_to_pipeline(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute(
        "UPDATE tasks SET status='pipeline', updated_on=? WHERE id=?",
        (_iso_now(), task_id),
    )
    conn.commit()


def archive_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute(
        "UPDATE tasks SET status='archived', updated_on=?, priority_index=NULL WHERE id=?",
        (_iso_now(), task_id),
    )
    conn.commit()


def unarchive_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute(
        "UPDATE tasks SET status='pipeline', updated_on=? WHERE id=?",
        (_iso_now(), task_id),
    )
    conn.commit()


def reopen_task(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    to_status: str = "pipeline",
) -> None:
    """Move a completed task back to the active board."""
    row = get_task(conn, task_id)
    if not row:
        raise ValueError("Task not found")
    if row["status"] != "done":
        raise ValueError("Only completed tasks can be reopened")
    if row["is_recurring"]:
        raise ValueError("Cannot reopen recurring template")
    if to_status not in ("pipeline", "in_progress"):
        raise ValueError("to_status must be 'pipeline' or 'in_progress'")
    now = _iso_now()
    placed = 1 if to_status == "in_progress" else row["placed"]
    conn.execute(
        """UPDATE tasks SET status=?, completed_on=NULL, placed=?, updated_on=?
           WHERE id=?""",
        (to_status, placed, now, task_id),
    )
    conn.commit()


def update_sort_order(conn: sqlite3.Connection, task_id: int, sort_order: int) -> None:
    conn.execute(
        "UPDATE tasks SET sort_order=?, updated_on=? WHERE id=?",
        (sort_order, _iso_now(), task_id),
    )
    conn.commit()


def reorder_tasks(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    """Renumber sort_order by each task id's position in ordered_ids.

    Renumbering the whole list (not just the moved item) is what makes a drag
    actually persist — otherwise duplicate sort_orders fall back to id order.
    """
    now = _iso_now()
    for index, tid in enumerate(ordered_ids):
        conn.execute(
            "UPDATE tasks SET sort_order=?, updated_on=? WHERE id=?",
            (index, now, tid),
        )
    conn.commit()


def update_task(conn: sqlite3.Connection, task_id: int, **fields) -> None:
    allowed = {
        "title", "description", "size", "category_id", "project_id",
        "parent_id", "due_date", "important", "urgent", "is_recurring",
        "accent_color", "procrastinate", "priority_index",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_on"] = _iso_now()
    cols = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE tasks SET {cols} WHERE id=?",
        (*updates.values(), task_id),
    )
    conn.commit()


def instantiate_recurring(conn: sqlite3.Connection, template_root_id: int) -> int:
    """Deep-copy a recurring template tree into fresh active tasks. Returns new root id."""
    root = get_task(conn, template_root_id)
    if not root or not root["is_recurring"]:
        raise ValueError("Not a recurring template")

    subtasks = get_subtasks(conn, template_root_id)
    now = _iso_now()

    def _clone_row(src: sqlite3.Row, *, parent_id: int | None, is_root: bool) -> int:
        pending = now if src["placed"] and not src["urgent"] else None
        cur = conn.execute(
            """INSERT INTO tasks
               (title, description, status, important, urgent, placed, size,
                category_id, project_id, parent_id, due_date, source,
                is_recurring, pending_since, created_on, updated_on)
               VALUES (?, ?, 'pipeline', ?, ?, ?, ?, ?, ?, ?, ?, 'recurring',
                       0, ?, ?, ?)""",
            (
                src["title"], src["description"],
                src["important"], src["urgent"], src["placed"], src["size"],
                src["category_id"], src["project_id"], parent_id, src["due_date"],
                pending, now, now,
            ),
        )
        return cur.lastrowid

    new_root_id = _clone_row(root, parent_id=None, is_root=True)
    for sub in subtasks:
        _clone_row(sub, parent_id=new_root_id, is_root=False)

    conn.commit()
    return new_root_id


def _require_recurring(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    row = get_task(conn, task_id)
    if not row:
        raise ValueError(f"Task {task_id} not found.")
    if not row["is_recurring"]:
        raise ValueError(f"Task {task_id} is not a recurring template.")
    if row["status"] == "archived":
        raise ValueError("Cannot modify archived recurring template.")
    return row


def get_recurring_template(conn: sqlite3.Connection, template_root_id: int) -> dict:
    """Return a recurring template root and its direct subtasks."""
    root = _require_recurring(conn, template_root_id)
    if root["parent_id"]:
        raise ValueError("template_id must be a root recurring template (not a subtask).")
    subtasks = [
        r
        for r in get_subtasks(conn, template_root_id)
        if r["is_recurring"] and r["status"] != "archived"
    ]
    return {"root": root, "subtasks": subtasks}


def create_recurring_template(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str | None = None,
    important: int = 0,
    urgent: int = 0,
    size: str = "medium",
    category_id: int | None = None,
    project_id: int | None = None,
    due_date: str | None = None,
    source: str = "mcp",
) -> sqlite3.Row:
    """Create a new recurring template root (Recurring section on board)."""
    placed = 1 if (important or urgent) else 0
    if project_id and not important and not urgent:
        placed = 0
    return add_task(
        conn,
        title=title,
        description=description,
        important=important,
        urgent=urgent,
        placed=placed,
        size=size,
        category_id=category_id,
        project_id=project_id,
        due_date=due_date,
        is_recurring=1,
        source=source,
    )


def add_recurring_subtask(
    conn: sqlite3.Connection,
    *,
    template_root_id: int,
    title: str,
    description: str | None = None,
    size: str = "medium",
    important: int | None = None,
    urgent: int | None = None,
    due_date: str | None = None,
) -> sqlite3.Row:
    """Add a subtask to a recurring template root (cloned on start_recurring)."""
    root = _require_recurring(conn, template_root_id)
    if root["parent_id"]:
        raise ValueError("template_root_id must be a root recurring template.")
    imp = 0 if important is None else int(important)
    urg = 0 if urgent is None else int(urgent)
    imp, urg, placed = placement_from_recurring_root(
        conn, template_root_id, important=imp, urgent=urg, placed=0
    )
    return add_task(
        conn,
        title=title,
        description=description,
        important=imp,
        urgent=urg,
        placed=placed,
        size=size,
        category_id=root["category_id"],
        project_id=root["project_id"],
        parent_id=template_root_id,
        due_date=due_date,
        is_recurring=1,
        source="mcp",
    )


def update_recurring_task(conn: sqlite3.Connection, task_id: int, **fields) -> None:
    """Patch a recurring template node (root or subtask)."""
    row = _require_recurring(conn, task_id)
    updates = dict(fields)
    if "important" in updates or "urgent" in updates:
        imp = updates.get("important", row["important"])
        urg = updates.get("urgent", row["urgent"])
        if "placed" not in updates:
            updates["placed"] = 1 if (imp or urg) else 0
    update_task(conn, task_id, **updates)


def list_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM categories ORDER BY parent_id NULLS FIRST, name"
    ).fetchall()


def list_parent_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM categories WHERE parent_id IS NULL ORDER BY name"
    ).fetchall()


def toggle_procrastinate(conn: sqlite3.Connection, task_id: int) -> int:
    """Flip procrastinate flag; return new value."""
    row = conn.execute(
        "SELECT procrastinate FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        raise ValueError("Task not found")
    new_val = 0 if row["procrastinate"] else 1
    conn.execute(
        "UPDATE tasks SET procrastinate=?, updated_on=? WHERE id=?",
        (new_val, _iso_now(), task_id),
    )
    conn.commit()
    return new_val


def _priority_eligible_sql(prefix: str = "") -> str:
    """SQL fragment for root active tasks eligible for MCP priority queue."""
    p = f"{prefix}." if prefix else ""
    return f"""{p}parent_id IS NULL
              AND COALESCE({p}is_recurring, 0) = 0
              AND {p}status IN ('pipeline', 'in_progress')"""


def list_priority_queue(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Active root tasks with a priority index, ordered 1 first."""
    return conn.execute(
        f"""{_task_select()}
           WHERE t.priority_index IS NOT NULL AND {_priority_eligible_sql("t")}
           ORDER BY t.priority_index ASC, t.id ASC""",
    ).fetchall()


def set_task_priority(
    conn: sqlite3.Connection, task_id: int, priority_index: int | None
) -> None:
    """Assign or clear MCP priority index on a root active task."""
    row = get_task(conn, task_id)
    if not row:
        raise ValueError("Task not found")
    if row["parent_id"]:
        raise ValueError("Priority queue is for root tasks only, not subtasks.")
    if row["is_recurring"]:
        raise ValueError("Recurring templates cannot be prioritized.")
    if row["status"] in ("done", "archived"):
        raise ValueError("Done or archived tasks cannot be prioritized.")
    if priority_index is not None and priority_index < 1:
        raise ValueError("priority_index must be >= 1, or null to clear.")
    conn.execute(
        "UPDATE tasks SET priority_index=?, updated_on=? WHERE id=?",
        (priority_index, _iso_now(), task_id),
    )
    conn.commit()


def set_priority_queue(conn: sqlite3.Connection, ordered_task_ids: list[int]) -> None:
    """Replace the MCP focus queue: clear existing priorities, assign 1..n in order."""
    if not ordered_task_ids:
        conn.execute(
            f"""UPDATE tasks SET priority_index=NULL, updated_on=?
                WHERE priority_index IS NOT NULL AND {_priority_eligible_sql()}""",
            (_iso_now(),),
        )
        conn.commit()
        return
    seen: set[int] = set()
    for tid in ordered_task_ids:
        if tid in seen:
            raise ValueError(f"Duplicate task id {tid} in priority queue.")
        seen.add(tid)
        row = get_task(conn, tid)
        if not row:
            raise ValueError(f"Task {tid} not found.")
        if row["parent_id"]:
            raise ValueError(f"Task {tid} is a subtask — queue root tasks only.")
        if row["is_recurring"]:
            raise ValueError(f"Task {tid} is a recurring template.")
        if row["status"] in ("done", "archived"):
            raise ValueError(f"Task {tid} is done or archived.")
    now = _iso_now()
    conn.execute(
        f"""UPDATE tasks SET priority_index=NULL, updated_on=?
            WHERE priority_index IS NOT NULL AND {_priority_eligible_sql()}""",
        (now,),
    )
    for index, tid in enumerate(ordered_task_ids, start=1):
        conn.execute(
            "UPDATE tasks SET priority_index=?, updated_on=? WHERE id=?",
            (index, now, tid),
        )
    conn.commit()


def reindex_task_priorities(conn: sqlite3.Connection) -> list[dict]:
    """Compact priority_index values to 1..n without gaps (MCP maintenance)."""
    rows = conn.execute(
        f"""SELECT id FROM tasks
            WHERE priority_index IS NOT NULL AND {_priority_eligible_sql()}
            ORDER BY priority_index ASC, id ASC""",
    ).fetchall()
    now = _iso_now()
    result: list[dict] = []
    for index, row in enumerate(rows, start=1):
        conn.execute(
            "UPDATE tasks SET priority_index=?, updated_on=? WHERE id=?",
            (index, now, row["id"]),
        )
        result.append({"id": row["id"], "priority_index": index})
    conn.commit()
    return result


def count_in_progress_by_size(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT size, COUNT(*) AS cnt FROM tasks WHERE status='in_progress' GROUP BY size"
    ).fetchall()
    return {r["size"]: r["cnt"] for r in rows}
