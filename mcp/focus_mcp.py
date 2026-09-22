"""Focus Board MCP tools and helpers — imported by mcp/server.py."""

from __future__ import annotations

import difflib
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from focus_services import colors as color_svc
from focus_services import projects as proj_svc
from focus_services import tasks as task_svc
from focus_services import time_tracker as timer_svc

_QUADRANT_FLAGS = {
    "do": (1, 1),
    "sched": (1, 0),
    "del": (0, 1),
    "later": (0, 0),
}

_TASK_TYPES = ("adhoc", "recurring", "project")

_STYLE_NOTE = "focus-task-style.md"
_CONFIRM_MSG = (
    "Show preview to the user; re-call with confirmed=True after explicit approval."
)

# Duplicate detection — how similar two titles must be to be flagged (0..1).
_DUP_THRESHOLD = 0.72


def _norm_title(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for duplicate matching."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _find_duplicate_candidates(
    conn: sqlite3.Connection, title: str, *, limit: int = 5
) -> list[dict]:
    """Return existing non-archived tasks whose title looks like `title`.

    Each candidate: id, title, status, similarity (0..1), exact (normalized match),
    active (status is pipeline/in_progress). Sorted exact-first then most similar.
    """
    target = _norm_title(title)
    if not target:
        return []
    rows = conn.execute(
        "SELECT id, title, status FROM tasks WHERE status != 'archived'"
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        cand = _norm_title(r["title"])
        if not cand:
            continue
        exact = cand == target
        ratio = difflib.SequenceMatcher(None, target, cand).ratio()
        if exact or ratio >= _DUP_THRESHOLD:
            out.append({
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "similarity": round(ratio, 2),
                "exact": exact,
                "active": r["status"] in ("active", "in_progress", "pipeline"),
            })
    out.sort(key=lambda d: (d["exact"], d["similarity"]), reverse=True)
    return out[:limit]


def _blocking_duplicates(candidates: list[dict]) -> list[dict]:
    """Exact matches of still-active tasks — the ones we refuse to duplicate."""
    return [c for c in candidates if c["exact"] and c["active"]]


def _band_for_row(row: sqlite3.Row | dict) -> str:
    """v2 lifecycle band: today | active | completed | archived."""
    status = row["status"]
    if status == "in_progress":
        return "today"
    if status == "done":
        return "completed"
    if status == "archived":
        return "archived"
    return "active"


def _slim_task(row: sqlite3.Row | dict) -> dict:
    """Task payload for list/get responses — action-oriented fields only."""
    keys = row.keys()
    category = row["category_name"] if "category_name" in keys else None
    project = row["project_name"] if "project_name" in keys else None
    parent_title = row["parent_title"] if "parent_title" in keys else None
    priority_index = row["priority_index"] if "priority_index" in keys else None
    waiting_on = row["waiting_on"] if "waiting_on" in keys else None
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "band": _band_for_row(row),
        "type": task_svc.resolve_task_type(row),
        "urgent": bool(row["urgent"]),
        "important": bool(row["important"]),
        "due_date": row["due_date"],
        "waiting_on": waiting_on,
        "description": row["description"],
        "parent_id": row["parent_id"],
        "parent_title": parent_title,
        "project": project,
        "category": category,
        "size": row["size"],
        "priority_index": priority_index,
    }


def _slim_mutate(row: sqlite3.Row | dict) -> dict:
    """Minimal write confirmation for task mutations."""
    return {
        "ok": True,
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "band": _band_for_row(row),
        "type": task_svc.resolve_task_type(row),
    }


def _place_task_preview(
    task_id: int, *, task_type: str | None, important: bool | None, urgent: bool | None
) -> dict:
    return {
        "ok": False,
        "needs_confirmation": True,
        "task_id": task_id,
        "band": "active",
        "task_type": task_type,
        "important": important,
        "urgent": urgent,
        "message": _CONFIRM_MSG,
    }


def _quadrant_label(important: int, urgent: int) -> str:
    """Legacy helper — kept only for recurring-template previews that still mention it."""
    return next(
        (k for k, v in _QUADRANT_FLAGS.items() if v == (important, urgent)),
        "later",
    )


def _needs_confirm(confirmed: bool, preview: dict, action: str) -> dict | None:
    if confirmed:
        return None
    return {
        "ok": False,
        "needs_confirmation": True,
        "action": action,
        "preview": preview,
        "message": _CONFIRM_MSG,
    }


_CLOCK_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p")


def _parse_local_dt(date: str, clock: str, tz: str) -> datetime:
    """Combine 'YYYY-MM-DD' + a local wall-clock time into a tz-aware datetime.

    Accepts 24h ('09:00') or 12h ('9:00 AM') clock strings. `tz` is an IANA name
    (e.g. 'America/Edmonton'); DST is handled by zoneinfo.
    """
    try:
        day = datetime.strptime(date.strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Could not parse date '{date}'. Use 'YYYY-MM-DD'.")
    parsed = None
    for fmt in _CLOCK_FORMATS:
        try:
            parsed = datetime.strptime(clock.strip().upper(), fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"Could not parse time '{clock}'. Use 'HH:MM' or 'H:MM AM/PM'.")
    try:
        zone = ZoneInfo(tz)
    except Exception:
        raise ValueError(f"Unknown timezone '{tz}'.")
    return day.replace(
        hour=parsed.hour, minute=parsed.minute, second=parsed.second, tzinfo=zone
    )


def _resolve_category_or_error(
    conn: sqlite3.Connection, name: str | None
) -> int | None:
    if not name:
        return None
    name = name.strip()
    if ">" in name:
        parent_part, child_part = [p.strip() for p in name.split(">", 1)]
        parent = conn.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id IS NULL",
            (parent_part,),
        ).fetchone()
        if not parent:
            raise ValueError(
                f"Category parent '{parent_part}' not found. Use list_categories or add_category."
            )
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id = ?",
            (child_part, parent["id"]),
        ).fetchone()
        if not row:
            raise ValueError(
                f"Subcategory '{child_part}' under '{parent_part}' not found. "
                "Use list_categories or add_category."
            )
        return row["id"]
    row = conn.execute(
        "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id IS NULL",
        (name,),
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE LIMIT 1", (name,)
        ).fetchone()
    if not row:
        raise ValueError(
            f"Category '{name}' not found. Use list_categories, add_category, "
            "or add_task(..., create_category=True)."
        )
    return row["id"]


def _resolve_or_create_category(
    conn: sqlite3.Connection,
    name: str | None,
    *,
    color: str | None = None,
    frame_style: str = "subtle",
) -> int | None:
    """Resolve category by name, or create parent/sub via get_or_create_category."""
    if not name:
        return None
    name = name.strip()
    if ">" in name:
        parent_part, child_part = [p.strip() for p in name.split(">", 1)]
        parent = conn.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id IS NULL",
            (parent_part,),
        ).fetchone()
        if parent:
            parent_id = parent["id"]
        else:
            parent_id = task_svc.get_or_create_category(
                conn,
                parent_part,
                None,
                color=color or color_svc.DEFAULT_COLOR,
                frame_style=frame_style,
            )
        return task_svc.get_or_create_category(conn, child_part, parent_id)
    existing = conn.execute(
        "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id IS NULL",
        (name,),
    ).fetchone()
    if existing:
        return existing["id"]
    return task_svc.get_or_create_category(
        conn,
        name,
        None,
        color=color or color_svc.DEFAULT_COLOR,
        frame_style=frame_style,
    )


def _resolve_project_or_error(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name:
        return None
    row = conn.execute(
        "SELECT id FROM projects WHERE name = ? COLLATE NOCASE AND status = 'active'",
        (name.strip(),),
    ).fetchone()
    if not row:
        raise ValueError(f"Project '{name}' not found. Use list_projects.")
    return row["id"]


def _resolve_parent_or_error(
    conn: sqlite3.Connection,
    *,
    parent_id: int | None = None,
    parent_title: str | None = None,
) -> int:
    if parent_id:
        row = task_svc.get_task(conn, parent_id)
        if not row:
            raise ValueError(f"Parent task id {parent_id} not found.")
        return parent_id
    if parent_title:
        row = conn.execute(
            """SELECT id FROM tasks WHERE title = ? COLLATE NOCASE
               AND parent_id IS NULL AND status NOT IN ('done', 'archived')
               AND COALESCE(is_recurring, 0) = 0 LIMIT 1""",
            (parent_title.strip(),),
        ).fetchone()
        if not row:
            raise ValueError(f"Parent task '{parent_title}' not found.")
        return row["id"]
    raise ValueError("parent_id or parent_title required.")


def _resolve_recurring_root_or_error(
    conn: sqlite3.Connection,
    *,
    template_id: int | None = None,
    template_title: str | None = None,
) -> int:
    if template_id:
        row = task_svc.get_task(conn, template_id)
        if not row or not row["is_recurring"] or row["parent_id"]:
            raise ValueError(
                f"Recurring template root {template_id} not found. Use list_recurring_templates."
            )
        return template_id
    if template_title:
        row = conn.execute(
            """SELECT id FROM tasks WHERE title = ? COLLATE NOCASE
               AND is_recurring = 1 AND parent_id IS NULL AND status != 'archived'
               LIMIT 1""",
            (template_title.strip(),),
        ).fetchone()
        if not row:
            raise ValueError(
                f"Recurring template '{template_title}' not found. Use list_recurring_templates."
            )
        return row["id"]
    raise ValueError("template_id or template_title required.")


def _recurring_node_dict(row: sqlite3.Row) -> dict:
    d = _slim_task(row)
    d["is_root"] = row["parent_id"] is None
    return d


def _task_dict_from_detail(conn: sqlite3.Connection, task_id: int) -> dict:
    row = task_svc.get_task_detail(conn, task_id)
    if not row:
        raise ValueError(f"Task {task_id} not found.")
    return _slim_task(row)


def _wording_flags(title: str, description: str | None) -> list[str]:
    flags: list[str] = []
    t = title or ""
    if len(t) > 100:
        flags.append("title_over_100_chars")
    if t.isupper() and len(t) > 3:
        flags.append("title_all_caps")
    lower = t.lower()
    for prefix in ("todo", "tbd", "fix", "misc", "stuff"):
        if lower.startswith(prefix):
            flags.append(f"vague_prefix_{prefix}")
    if not description or not description.strip():
        flags.append("missing_description")
    return flags


def _load_style_guide(notes_dir: str) -> dict:
    path = os.path.join(notes_dir, _STYLE_NOTE)
    if not os.path.exists(path):
        return {"empty": True, "path": path, "content": "", "hint": "Create focus-task-style.md"}
    with open(path, encoding="utf-8", errors="replace") as f:
        return {"empty": False, "path": path, "content": f.read()}


def register_focus_tools(mcp, *, focus_db_path: str, notes_dir: str, open_db) -> None:
    """Register all focus MCP tools on the given FastMCP instance."""

    @mcp.tool()
    def get_task_style_guide() -> dict:
        """Read the task wording style guide from the Knowledge App (read-only)."""
        return _load_style_guide(notes_dir)

    @mcp.tool()
    def suggest_task_wording(task_id: int) -> dict:
        """Review task title/description against the style guide — read-only, never mutates.

        Returns current text, style guide, and heuristic flags. Propose improvements
        to the user in chat; use update_task with confirmed=True only after approval.
        """
        with open_db(focus_db_path) as conn:
            row = task_svc.get_task_detail(conn, task_id)
            if not row:
                raise ValueError(f"Task {task_id} not found.")
            guide = _load_style_guide(notes_dir)
            return {
                "task_id": task_id,
                "current_title": row["title"],
                "current_description": row["description"],
                "style_guide": guide.get("content", ""),
                "style_guide_empty": guide.get("empty", True),
                "heuristic_flags": _wording_flags(row["title"], row["description"]),
            }

    @mcp.tool()
    def get_task(task_id: int) -> dict:
        """Get full task detail including description, category, project, accent, subtask counts."""
        with open_db(focus_db_path) as conn:
            return _task_dict_from_detail(conn, task_id)

    @mcp.tool()
    def list_tasks(status: str | None = None, placed: bool | None = None) -> list[dict]:
        """List tasks. Ask user for filters if unclear. Use list_categories / list_projects for names.

        status='pipeline' is accepted as an alias for 'active'. placed is ignored.
        """
        clauses = ["COALESCE(t.is_recurring, 0) = 0", "t.status != 'archived'"]
        params: list[Any] = []
        if status:
            if status == "pipeline":
                status = "active"
            clauses.append("t.status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses)
        with open_db(focus_db_path) as conn:
            rows = conn.execute(
                f"""SELECT t.*, c.name AS category_name, c.color AS category_color,
                           c.frame_style AS category_frame_style,
                           p.name AS project_name, parent.title AS parent_title
                    FROM tasks t
                    LEFT JOIN categories c ON c.id = t.category_id
                    LEFT JOIN projects p ON p.id = t.project_id
                    LEFT JOIN tasks parent ON parent.id = t.parent_id
                    {where}
                    ORDER BY t.sort_order, t.id""",
                params,
            ).fetchall()
            return [_slim_task(r) for r in rows]

    @mcp.tool()
    def list_active_board() -> dict:
        """Active work snapshot for the v2 board bands.

        Returns today (in_progress) and active (not-started tasks grouped by type:
        adhoc / recurring / project). pipeline is always [] (legacy key).
        Excludes recurring templates, done, and archived.
        """
        with open_db(focus_db_path) as conn:
            today = [_slim_task(r) for r in task_svc.list_in_progress(conn)]
            by_type = task_svc.list_active_by_type(conn)
            active = {
                key: [_slim_task(r) for r in rows]
                for key, rows in by_type.items()
            }
            return {
                "today": today,
                "in_progress": today,  # alias for older callers
                "active": active,
                "pipeline": [],
            }

    @mcp.tool()
    def search_tasks(query: str, limit: int = 15) -> list[dict]:
        """Find active tasks by partial title/description match (read-only).

        All words in query must appear somewhere in title or description (case-insensitive).
        Results ranked: exact title match, then substring, then prefix, then other hits.
        Use when list_tasks filter is unclear or the task name may not match exactly.
        """
        with open_db(focus_db_path) as conn:
            rows = task_svc.search_tasks(conn, query, limit=limit)
            return [_slim_task(r) for r in rows]

    @mcp.tool()
    def list_priority_queue() -> list[dict]:
        """Read-only: root active tasks in MCP focus order (priority_index 1 = do first).

        Use this during check-ins to keep Christian on track. Tasks without a
        priority_index are not in the queue.
        """
        with open_db(focus_db_path) as conn:
            rows = task_svc.list_priority_queue(conn)
            return [_slim_task(r) for r in rows]

    @mcp.tool()
    def set_task_priority(
        task_id: int,
        priority_index: int | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Assign MCP focus rank on a root task (1 = highest). Pass priority_index=null to clear.

        Does not shift other tasks — call reindex_task_priorities to compact gaps, or use
        set_priority_queue to replace the whole ordered list.
        """
        preview = {"task_id": task_id, "priority_index": priority_index}
        blocked = _needs_confirm(confirmed, preview, "set_task_priority")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task_svc.set_task_priority(conn, task_id, priority_index)
            row = task_svc.get_task(conn, task_id)
            return _slim_mutate(row)

    @mcp.tool()
    def set_priority_queue(task_ids: list[int], confirmed: bool = False) -> dict:
        """Replace the MCP focus queue with an ordered list (ids[0] → priority 1, etc.).

        Clears previous queue entries, then assigns 1..n. Empty list clears the queue.
        Preferred tool when agreeing on 'what to work on next' in conversation.
        """
        preview = {"task_ids": task_ids, "count": len(task_ids)}
        blocked = _needs_confirm(confirmed, preview, "set_priority_queue")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task_svc.set_priority_queue(conn, task_ids)
            rows = task_svc.list_priority_queue(conn)
            return {
                "ok": True,
                "queue": [
                    {
                        "priority_index": r["priority_index"],
                        "id": r["id"],
                        "title": r["title"],
                        "status": r["status"],
                    }
                    for r in rows
                ],
            }

    @mcp.tool()
    def reindex_task_priorities(confirmed: bool = False) -> dict:
        """Compact priority_index values to 1..n without gaps (MCP maintenance).

        Call occasionally when indices get sparse or large after many edits.
        """
        with open_db(focus_db_path) as conn:
            before = [
                {"id": r["id"], "priority_index": r["priority_index"]}
                for r in task_svc.list_priority_queue(conn)
            ]
        preview = {"before": before, "action": "compact to 1..n"}
        blocked = _needs_confirm(confirmed, preview, "reindex_task_priorities")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            after = task_svc.reindex_task_priorities(conn)
            return {"ok": True, "before": before, "after": after}

    @mcp.tool()
    def add_task(
        title: str,
        confirmed: bool = False,
        description: str | None = None,
        important: bool | None = None,
        urgent: bool | None = None,
        size: str = "medium",
        category: str | None = None,
        create_category: bool = False,
        category_color: str | None = None,
        category_frame_style: str = "subtle",
        project: str | None = None,
        due_date: str | None = None,
        accent_color: str | None = None,
        priority_index: int | None = None,
        source: str = "mcp",
        allow_duplicate: bool = False,
    ) -> dict:
        """Add a task. Ask user for all fields before calling. confirmed=False returns preview only.

        Use category='Parent > Sub' for subcategories. When create_category=True, missing
        categories are created (same as web quick-add). Otherwise use add_category first.

        Duplicate guard: the preview lists any existing look-alike tasks under
        `possible_duplicates` — review them before confirming, and skip/update instead of
        re-adding. An exact match of a still-active task is refused on confirm unless
        allow_duplicate=True.
        """
        imp = 1 if important else 0
        urg = 1 if urgent else 0
        with open_db(focus_db_path) as conn:
            duplicates = _find_duplicate_candidates(conn, title)
        preview = {
            "title": title,
            "description": description,
            "important": bool(imp),
            "urgent": bool(urg),
            "quadrant": _quadrant_label(imp, urg),
            "size": size,
            "category": category,
            "create_category": create_category,
            "category_color": category_color,
            "category_frame_style": category_frame_style,
            "project": project,
            "due_date": due_date,
            "accent_color": accent_color,
            "priority_index": priority_index,
            "possible_duplicates": duplicates,
        }
        blocked = _needs_confirm(confirmed, preview, "add_task")
        if blocked:
            return blocked
        if not allow_duplicate and _blocking_duplicates(duplicates):
            return {
                "ok": False,
                "skipped": True,
                "reason": "possible_duplicate",
                "duplicates": duplicates,
                "message": (
                    "A matching active task already exists. Update that task, or "
                    "re-call with allow_duplicate=True to add anyway."
                ),
            }
        with open_db(focus_db_path) as conn:
            if create_category and category:
                category_id = _resolve_or_create_category(
                    conn,
                    category,
                    color=category_color,
                    frame_style=category_frame_style,
                )
            else:
                category_id = _resolve_category_or_error(conn, category)
            project_id = _resolve_project_or_error(conn, project)
            row = task_svc.add_task(
                conn,
                title=title,
                description=description,
                important=imp,
                urgent=urg,
                size=size,
                category_id=category_id,
                project_id=project_id,
                due_date=due_date,
                source=source,
            )
            if accent_color:
                task_svc.update_task(conn, row["id"], accent_color=accent_color)
            if priority_index is not None:
                task_svc.set_task_priority(conn, row["id"], priority_index)
            row = task_svc.get_task(conn, row["id"])
            result = _slim_mutate(row)
            if duplicates:
                result["possible_duplicates"] = duplicates
            return result

    @mcp.tool()
    def add_subtask(
        title: str,
        confirmed: bool = False,
        parent_id: int | None = None,
        parent_title: str | None = None,
        description: str | None = None,
        size: str = "medium",
        due_date: str | None = None,
    ) -> dict:
        """Add a subtask under a parent. Inherits parent placement. Requires confirmed=True to write."""
        preview = {
            "title": title,
            "parent_id": parent_id,
            "parent_title": parent_title,
            "description": description,
            "size": size,
        }
        blocked = _needs_confirm(confirmed, preview, "add_subtask")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            pid = _resolve_parent_or_error(conn, parent_id=parent_id, parent_title=parent_title)
            parent = task_svc.get_task(conn, pid)
            if parent["is_recurring"]:
                raise ValueError(
                    "Use add_recurring_subtask for recurring templates, not add_subtask."
                )
            row = task_svc.add_task(
                conn,
                title=title,
                description=description,
                important=parent["important"],
                urgent=parent["urgent"],
                size=size,
                category_id=parent["category_id"],
                project_id=parent["project_id"],
                parent_id=pid,
                due_date=due_date,
                source="mcp",
            )
            return _slim_mutate(task_svc.get_task(conn, row["id"]))

    @mcp.tool()
    def add_project(
        name: str,
        confirmed: bool = False,
        description: str | None = None,
    ) -> dict:
        """Add a project. confirmed=False returns preview only."""
        preview = {"name": name, "description": description}
        blocked = _needs_confirm(confirmed, preview, "add_project")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM projects WHERE name = ? COLLATE NOCASE", (name.strip(),)
            ).fetchone()
            if existing:
                raise ValueError(f"Project '{name}' already exists (id={existing['id']}).")
            row = proj_svc.add_project(conn, name=name.strip(), description=description)
            return {"ok": True, "id": row["id"], "name": row["name"]}

    @mcp.tool()
    def add_category(
        name: str,
        confirmed: bool = False,
        parent: str | None = None,
        color: str | None = None,
        frame_style: str = "subtle",
    ) -> dict:
        """Add a parent category or subcategory. confirmed=False returns preview only.

        Args:
            name: Category name (required).
            parent: Optional parent category name for a subcategory. Supports 'Parent > Sub'
                syntax in parent only when resolving an existing parent by full path.
            color: Swatch hex for new parent categories (defaults to palette default).
            frame_style: Gradient frame intensity — subtle, medium, or bold (parents only).

        Idempotent: returns existing id if the same name already exists under the same parent.
        """
        preview = {
            "name": name,
            "parent": parent,
            "color": color,
            "frame_style": frame_style,
        }
        blocked = _needs_confirm(confirmed, preview, "add_category")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            parent_id = None
            if parent:
                parent_id = _resolve_category_or_error(conn, parent)
                parent_row = task_svc.get_category(conn, parent_id)
                if parent_row and parent_row["parent_id"]:
                    raise ValueError("Parent must be a top-level category.")
            before = None
            if parent_id is None:
                before = conn.execute(
                    "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id IS NULL",
                    (name.strip(),),
                ).fetchone()
            else:
                before = conn.execute(
                    "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND parent_id = ?",
                    (name.strip(), parent_id),
                ).fetchone()
            cat_id = task_svc.get_or_create_category(
                conn,
                name,
                parent_id,
                color=(color or color_svc.DEFAULT_COLOR) if parent_id is None else None,
                frame_style=frame_style if parent_id is None else "subtle",
            )
            return {
                "ok": True,
                "id": cat_id,
                "name": name.strip(),
                "parent_id": parent_id,
                "created": before is None,
            }

    @mcp.tool()
    def update_task(
        task_id: int,
        confirmed: bool = False,
        title: str | None = None,
        description: str | None = None,
        size: str | None = None,
        category: str | None = None,
        create_category: bool = False,
        category_color: str | None = None,
        category_frame_style: str = "subtle",
        project: str | None = None,
        due_date: str | None = None,
        accent_color: str | None = None,
        procrastinate: bool | None = None,
        important: bool | None = None,
        urgent: bool | None = None,
        waiting_on: str | None = None,
        type_override: str | None = None,
        parent_id: int | None = None,
        parent_title: str | None = None,
    ) -> dict:
        """Patch a task. description is high priority for email-sweep context. confirmed=True required to write.

        type_override ∈ adhoc|recurring|project|'' (empty string clears to derived).
        waiting_on is a free-text label shown as a wait chip on Active tiles.
        """
        if type_override is not None and type_override not in ("", *_TASK_TYPES):
            raise ValueError(f"type_override must be one of {_TASK_TYPES} or ''.")
        fields = {
            k: v
            for k, v in {
                "title": title,
                "description": description,
                "size": size,
                "category": category,
                "create_category": create_category if category is not None else None,
                "project": project,
                "due_date": due_date,
                "accent_color": accent_color,
                "procrastinate": procrastinate,
                "important": important,
                "urgent": urgent,
                "waiting_on": waiting_on,
                "type_override": type_override,
                "parent_id": parent_id,
                "parent_title": parent_title,
            }.items()
            if v is not None
        }
        if not fields:
            raise ValueError("At least one field to update is required.")
        preview = {"task_id": task_id, **fields}
        blocked = _needs_confirm(confirmed, preview, "update_task")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task = task_svc.get_task(conn, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found.")
            if task["status"] == "archived":
                raise ValueError("Cannot update archived task — unarchive first.")
            if task["is_recurring"]:
                raise ValueError(
                    "Use update_recurring_task for recurring templates, not update_task."
                )
            updates: dict[str, Any] = {}
            if title is not None:
                updates["title"] = title
            if description is not None:
                updates["description"] = description
            if size is not None:
                updates["size"] = size
            if due_date is not None:
                updates["due_date"] = due_date
            if accent_color is not None:
                updates["accent_color"] = accent_color or None
            if procrastinate is not None:
                updates["procrastinate"] = 1 if procrastinate else 0
            if important is not None:
                updates["important"] = 1 if important else 0
            if urgent is not None:
                updates["urgent"] = 1 if urgent else 0
            if waiting_on is not None:
                updates["waiting_on"] = waiting_on.strip() or None
            if type_override is not None:
                updates["type_override"] = type_override or None
            if category is not None:
                if category == "":
                    updates["category_id"] = None
                elif create_category:
                    updates["category_id"] = _resolve_or_create_category(
                        conn,
                        category,
                        color=category_color,
                        frame_style=category_frame_style,
                    )
                else:
                    updates["category_id"] = _resolve_category_or_error(conn, category)
            if project is not None:
                updates["project_id"] = _resolve_project_or_error(conn, project) if project else None
            if parent_id is not None or parent_title is not None:
                updates["parent_id"] = _resolve_parent_or_error(
                    conn, parent_id=parent_id, parent_title=parent_title
                )
            task_svc.update_task(conn, task_id, **updates)
            return _slim_mutate(task_svc.get_task(conn, task_id))

    @mcp.tool()
    def place_task(
        task_id: int,
        important: bool | None = None,
        urgent: bool | None = None,
        task_type: str | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Ensure a task is on Active (status=active). confirmed=True required.

        New tasks already land on Active — this is a no-op wrapper for older
        callers. Pass important/urgent only to set those flags. Optional
        task_type ∈ adhoc|recurring|project sets a type_override when it
        differs from the natural type.
        """
        if task_type is not None and task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}.")
        if not confirmed:
            return _place_task_preview(
                task_id, task_type=task_type, important=important, urgent=urgent
            )
        with open_db(focus_db_path) as conn:
            task = task_svc.get_task(conn, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found.")
            if task["is_recurring"]:
                raise ValueError("Cannot place a recurring template — start it first.")
            flag_updates = {}
            if important is not None:
                flag_updates["important"] = 1 if important else 0
            if urgent is not None:
                flag_updates["urgent"] = 1 if urgent else 0
            if flag_updates:
                task_svc.update_task(conn, task_id, **flag_updates)
            task_svc.set_task_band(conn, task_id, band="active", target_type=task_type)
            return _slim_mutate(task_svc.get_task(conn, task_id))

    @mcp.tool()
    def promote_to_active(
        task_id: int,
        task_type: str | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Ensure a task is on Active. Alias for place_task without flags.

        Optional task_type ∈ adhoc|recurring|project. confirmed=True required.
        """
        return place_task(
            task_id, task_type=task_type, confirmed=confirmed
        )

    @mcp.tool()
    def complete_task(
        task_id: int,
        confirmed: bool = False,
        enthusiasm: int | None = None,
    ) -> dict:
        """Mark a task done. Stops active timer on that task. confirmed=True required."""
        preview = {"task_id": task_id, "enthusiasm": enthusiasm}
        blocked = _needs_confirm(confirmed, preview, "complete_task")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            active = timer_svc.get_active_entry(conn)
            if active and active["task_id"] == task_id:
                timer_svc.stop_timer(conn)
            task_svc.complete_task(conn, task_id, enthusiasm)
            row = task_svc.get_task(conn, task_id)
            return _slim_mutate(row)

    @mcp.tool()
    def reopen_task(
        task_id: int,
        confirmed: bool = False,
        to_status: str = "active",
    ) -> dict:
        """Move a completed task back to the board (Active or Today).

        to_status='active' (or legacy 'pipeline') restores to Active.
        to_status='in_progress' restores to Today. confirmed=True required.
        """
        if to_status == "pipeline":
            to_status = "active"
        if to_status not in ("active", "in_progress"):
            raise ValueError("to_status must be 'active' or 'in_progress'")
        preview = {"task_id": task_id, "to_status": to_status}
        blocked = _needs_confirm(confirmed, preview, "reopen_task")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task_svc.reopen_task(conn, task_id, to_status=to_status)
            return _slim_mutate(task_svc.get_task(conn, task_id))

    @mcp.tool()
    def archive_task(task_id: int, confirmed: bool = False) -> dict:
        """Archive a task (hide from board). Stops timer if active. confirmed=True required."""
        preview = {"task_id": task_id, "status": "archived"}
        blocked = _needs_confirm(confirmed, preview, "archive_task")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task = task_svc.get_task(conn, task_id)
            if task and task["is_recurring"]:
                raise ValueError("Cannot archive recurring template.")
            active = timer_svc.get_active_entry(conn)
            if active and active["task_id"] == task_id:
                timer_svc.stop_timer(conn)
            task_svc.archive_task(conn, task_id)
            return _slim_mutate(task_svc.get_task(conn, task_id))

    @mcp.tool()
    def unarchive_task(task_id: int, confirmed: bool = False) -> dict:
        """Restore archived task to Active. confirmed=True required."""
        preview = {"task_id": task_id, "status": "active", "band": "active"}
        blocked = _needs_confirm(confirmed, preview, "unarchive_task")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task_svc.unarchive_task(conn, task_id)
            return _slim_mutate(task_svc.get_task(conn, task_id))

    @mcp.tool()
    def list_archived_tasks(limit: int = 20) -> list[dict]:
        """List archived tasks (read-only)."""
        with open_db(focus_db_path) as conn:
            rows = task_svc.list_archived_tasks(conn, limit)
            return [_slim_task(r) for r in rows]

    @mcp.tool()
    def move_to_pipeline(task_id: int, confirmed: bool = False) -> dict:
        """Send a task off Today back to Active (status=active).

        Stops the timer if this task is timing. confirmed=True required.
        """
        preview = {"task_id": task_id, "band": "active"}
        blocked = _needs_confirm(confirmed, preview, "move_to_pipeline")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            active = timer_svc.get_active_entry(conn)
            if active and active["task_id"] == task_id:
                timer_svc.stop_timer(conn)
            task_svc.set_task_band(conn, task_id, band="active")
            return _slim_mutate(task_svc.get_task(conn, task_id))

    def _apply_move_to_in_progress(task_id: int) -> dict:
        with open_db(focus_db_path) as conn:
            task = task_svc.get_task(conn, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found.")
            if task["is_recurring"]:
                raise ValueError("Cannot move recurring template to in-progress.")
            if task["status"] == "archived":
                raise ValueError("Cannot move archived task — unarchive first.")
            if task["status"] == "done":
                raise ValueError("Task is already done.")
            if task["status"] == "in_progress":
                return _slim_mutate(task)
            task_svc.move_to_in_progress(conn, task_id)
            return _slim_mutate(task_svc.get_task(conn, task_id))

    @mcp.tool()
    def move_to_in_progress(task_id: int, confirmed: bool = False) -> dict:
        """Move a task to Today (in_progress). confirmed=True required.

        Use from Active before start_timer.
        """
        preview = {"task_id": task_id, "band": "today", "status": "in_progress"}
        blocked = _needs_confirm(confirmed, preview, "move_to_in_progress")
        if blocked:
            return blocked
        return _apply_move_to_in_progress(task_id)

    @mcp.tool()
    def start_work(task_id: int, confirmed: bool = False) -> dict:
        """Alias for move_to_in_progress — moves task to Today."""
        preview = {"task_id": task_id, "band": "today", "status": "in_progress"}
        blocked = _needs_confirm(confirmed, preview, "start_work")
        if blocked:
            return blocked
        return _apply_move_to_in_progress(task_id)

    @mcp.tool()
    def start_timer(task_id: int, confirm_switch: bool = False, confirmed: bool = False) -> dict:
        """Start timer on an in_progress task. Use move_to_in_progress first. confirm_switch if another timer runs."""
        preview = {"task_id": task_id, "confirm_switch": confirm_switch}
        blocked = _needs_confirm(confirmed, preview, "start_timer")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task = task_svc.get_task(conn, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found.")
            if task["is_recurring"]:
                raise ValueError("Cannot time a recurring template.")
            if task["status"] == "archived":
                raise ValueError("Cannot time archived task.")
            if task["status"] != "in_progress":
                raise ValueError("Task must be in_progress. Use move_to_in_progress(task_id) first.")
            active = timer_svc.get_active_entry(conn)
            if active and active["task_id"] != task_id and not confirm_switch:
                return {
                    "ok": False,
                    "needs_confirm": True,
                    "message": "Timer already running on another task. Re-call with confirm_switch=True.",
                    "current_task_id": active["task_id"],
                    "current_task_title": active["task_title"],
                }
            timer_svc.start_timer(conn, task_id)
            entry = timer_svc.get_active_entry(conn)
            return {
                "ok": True,
                "task_id": task_id,
                "started_at": entry["started_at"],
                "elapsed_seconds": 0,
            }

    @mcp.tool()
    def stop_timer(confirmed: bool = False) -> dict:
        """Stop the active timer. confirmed=True required."""
        with open_db(focus_db_path) as conn:
            entry = timer_svc.get_active_entry(conn)
            if not entry:
                return {"ok": True}
            preview = {
                "task_id": entry["task_id"],
                "task_title": entry["task_title"],
                "elapsed_seconds": timer_svc.elapsed_seconds(entry["started_at"]),
            }
        blocked = _needs_confirm(confirmed, preview, "stop_timer")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            stopped = timer_svc.stop_timer(conn)
            if not stopped:
                return {"ok": True}
            return {
                "ok": True,
                "task_id": stopped["task_id"],
                "duration_seconds": stopped["duration_seconds"],
            }

    @mcp.tool()
    def get_active_timer() -> dict:
        """Return the currently running timer, if any (read-only)."""
        with open_db(focus_db_path) as conn:
            entry = timer_svc.get_active_entry(conn)
            if entry is None:
                return {"active": False}
            return {
                "active": True,
                "task_id": entry["task_id"],
                "task_title": entry["task_title"],
                "started_at": entry["started_at"],
                "elapsed_seconds": timer_svc.elapsed_seconds(entry["started_at"]),
            }

    @mcp.tool()
    def list_subtasks(
        parent_id: int | None = None,
        parent_title: str | None = None,
    ) -> dict:
        """List subtasks of a parent with done/total progress."""
        with open_db(focus_db_path) as conn:
            pid = _resolve_parent_or_error(conn, parent_id=parent_id, parent_title=parent_title)
            subs = task_svc.get_subtasks(conn, pid)
            done, total = task_svc.subtask_progress(conn, pid)
            return {
                "parent_id": pid,
                "done": done,
                "total": total,
                "subtasks": [
                    {
                        "id": s["id"],
                        "title": s["title"],
                        "status": s["status"],
                        "size": s["size"],
                    }
                    for s in subs
                ],
            }

    @mcp.tool()
    def get_task_time(task_id: int, limit: int = 10) -> dict:
        """Total logged seconds and recent time entries for a task (read-only)."""
        with open_db(focus_db_path) as conn:
            if not task_svc.get_task(conn, task_id):
                raise ValueError(f"Task {task_id} not found.")
            entries = timer_svc.list_entries_for_task(conn, task_id, limit)
            return {
                "task_id": task_id,
                "total_seconds": timer_svc.total_time_on_task(conn, task_id),
                "recent_entries": [
                    {
                        "started_at": e["started_at"],
                        "ended_at": e["ended_at"],
                        "duration_seconds": e["duration_seconds"],
                    }
                    for e in entries
                ],
            }

    @mcp.tool()
    def list_recurring_templates() -> list[dict]:
        """List recurring template trees (read-only)."""
        with open_db(focus_db_path) as conn:
            templates = task_svc.list_recurring_templates(conn)
            result = []
            for tmpl in templates:
                root = tmpl["root"]
                result.append({
                    "root_id": root["id"],
                    "root_title": root["title"],
                    "quadrant": _quadrant_label(root["important"], root["urgent"]),
                    "subtasks": [
                        {
                            "id": s["id"],
                            "title": s["title"],
                            "quadrant": _quadrant_label(s["important"], s["urgent"]),
                        }
                        for s in tmpl["subtasks"]
                    ],
                })
            return result

    @mcp.tool()
    def get_recurring_template(
        template_id: int | None = None,
        template_title: str | None = None,
    ) -> dict:
        """Read a recurring template root and its subtasks (read-only)."""
        with open_db(focus_db_path) as conn:
            root_id = _resolve_recurring_root_or_error(
                conn, template_id=template_id, template_title=template_title
            )
            tmpl = task_svc.get_recurring_template(conn, root_id)
            return {
                "root": _recurring_node_dict(tmpl["root"]),
                "subtasks": [_recurring_node_dict(s) for s in tmpl["subtasks"]],
            }

    @mcp.tool()
    def add_recurring_template(
        title: str,
        confirmed: bool = False,
        description: str | None = None,
        important: bool | None = None,
        urgent: bool | None = None,
        size: str = "medium",
        category: str | None = None,
        create_category: bool = False,
        category_color: str | None = None,
        category_frame_style: str = "subtle",
        project: str | None = None,
        due_date: str | None = None,
    ) -> dict:
        """Create a recurring template root (Recurring section — not an active task).

        Set important/urgent as explicit flags on the template (and its clones).
        Start clones the tree onto Active Recurring. confirmed=True required to write.
        """
        imp = 1 if important else 0
        urg = 1 if urgent else 0
        preview = {
            "title": title,
            "description": description,
            "important": bool(imp),
            "urgent": bool(urg),
            "size": size,
            "category": category,
            "project": project,
            "due_date": due_date,
        }
        blocked = _needs_confirm(confirmed, preview, "add_recurring_template")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            if create_category and category:
                category_id = _resolve_or_create_category(
                    conn,
                    category,
                    color=category_color,
                    frame_style=category_frame_style,
                )
            else:
                category_id = _resolve_category_or_error(conn, category)
            project_id = _resolve_project_or_error(conn, project)
            row = task_svc.create_recurring_template(
                conn,
                title=title,
                description=description,
                important=imp,
                urgent=urg,
                size=size,
                category_id=category_id,
                project_id=project_id,
                due_date=due_date,
            )
            detail = task_svc.get_task_detail(conn, row["id"])
            return _slim_mutate(detail)

    @mcp.tool()
    def add_recurring_subtask(
        title: str,
        confirmed: bool = False,
        template_id: int | None = None,
        template_title: str | None = None,
        description: str | None = None,
        size: str = "medium",
        important: bool | None = None,
        urgent: bool | None = None,
        due_date: str | None = None,
    ) -> dict:
        """Add a subtask to a recurring template root. Cloned with start_recurring.

        Subtasks attach to the template root only. Optional important/urgent override
        per subtask quadrant. confirmed=True required.
        """
        preview = {
            "title": title,
            "template_id": template_id,
            "template_title": template_title,
            "description": description,
            "size": size,
            "important": important,
            "urgent": urgent,
        }
        blocked = _needs_confirm(confirmed, preview, "add_recurring_subtask")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            root_id = _resolve_recurring_root_or_error(
                conn, template_id=template_id, template_title=template_title
            )
            row = task_svc.add_recurring_subtask(
                conn,
                template_root_id=root_id,
                title=title,
                description=description,
                size=size,
                important=(1 if important else 0) if important is not None else None,
                urgent=(1 if urgent else 0) if urgent is not None else None,
                due_date=due_date,
            )
            detail = task_svc.get_task_detail(conn, row["id"])
            out = _slim_mutate(detail)
            out["template_root_id"] = root_id
            return out

    @mcp.tool()
    def update_recurring_task(
        task_id: int,
        confirmed: bool = False,
        title: str | None = None,
        description: str | None = None,
        size: str | None = None,
        category: str | None = None,
        create_category: bool = False,
        category_color: str | None = None,
        category_frame_style: str = "subtle",
        project: str | None = None,
        due_date: str | None = None,
        important: bool | None = None,
        urgent: bool | None = None,
        accent_color: str | None = None,
    ) -> dict:
        """Patch a recurring template root or subtask. confirmed=True required to write."""
        fields = {
            k: v
            for k, v in {
                "title": title,
                "description": description,
                "size": size,
                "category": category,
                "create_category": create_category if category is not None else None,
                "project": project,
                "due_date": due_date,
                "important": important,
                "urgent": urgent,
                "accent_color": accent_color,
            }.items()
            if v is not None
        }
        if not fields:
            raise ValueError("At least one field to update is required.")
        preview = {"task_id": task_id, **fields}
        blocked = _needs_confirm(confirmed, preview, "update_recurring_task")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            updates: dict[str, Any] = {}
            if title is not None:
                updates["title"] = title
            if description is not None:
                updates["description"] = description
            if size is not None:
                updates["size"] = size
            if due_date is not None:
                updates["due_date"] = due_date
            if accent_color is not None:
                updates["accent_color"] = accent_color or None
            if important is not None:
                updates["important"] = 1 if important else 0
            if urgent is not None:
                updates["urgent"] = 1 if urgent else 0
            if category is not None:
                if category == "":
                    updates["category_id"] = None
                elif create_category:
                    updates["category_id"] = _resolve_or_create_category(
                        conn,
                        category,
                        color=category_color,
                        frame_style=category_frame_style,
                    )
                else:
                    updates["category_id"] = _resolve_category_or_error(conn, category)
            if project is not None:
                updates["project_id"] = (
                    _resolve_project_or_error(conn, project) if project else None
                )
            task_svc.update_recurring_task(conn, task_id, **updates)
            detail = task_svc.get_task_detail(conn, task_id)
            return _slim_mutate(detail)

    @mcp.tool()
    def start_recurring(template_id: int, confirmed: bool = False) -> dict:
        """Clone a recurring template into active tasks. confirmed=True required."""
        preview = {"template_id": template_id}
        blocked = _needs_confirm(confirmed, preview, "start_recurring")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            new_id = task_svc.instantiate_recurring(conn, template_id)
            row = task_svc.get_task(conn, new_id)
            return _slim_mutate(row)

    @mcp.tool()
    def list_projects() -> list[dict]:
        """List active projects."""
        with open_db(focus_db_path) as conn:
            return [
                {"id": p["id"], "name": p["name"], "description": p["description"]}
                for p in proj_svc.list_projects(conn)
            ]

    @mcp.tool()
    def list_categories() -> list[dict]:
        """List categories with colour and frame style."""
        with open_db(focus_db_path) as conn:
            rows = task_svc.list_categories(conn)
            by_id = {r["id"]: r["name"] for r in rows}
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "parent": by_id.get(r["parent_id"]) if r["parent_id"] else None,
                    "color": r["color"],
                    "frame_style": r["frame_style"] if "frame_style" in r.keys() else "subtle",
                }
                for r in rows
            ]

    # ------------------------------------------------------------------ #
    # Bulk / composite tools — collapse multi-task work into one call.    #
    # Each reuses the single-op focus_services functions above; one       #
    # confirm approves the whole batch (not per item).                    #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def add_tasks(
        tasks: list[dict], confirmed: bool = False, allow_duplicate: bool = False
    ) -> dict:
        """Bulk-add several tasks in one call. confirmed=False returns a preview of every row.

        Each item in `tasks` takes the same fields as add_task: title (required),
        description, important, urgent, size, category ('Parent > Sub'), create_category,
        category_color, category_frame_style, project, due_date, accent_color, priority_index.
        One confirmed=True writes the whole batch. Use this instead of calling add_task N times.

        Duplicate guard: each preview row lists any existing look-alikes under
        `possible_duplicates`. On confirm, rows that exactly match a still-active task are
        skipped (returned under `skipped`) unless allow_duplicate=True — so re-running an
        email sweep won't re-create tasks already on the board.
        """
        if not tasks:
            raise ValueError("Provide at least one task.")
        previews = []
        with open_db(focus_db_path) as conn:
            for t in tasks:
                if not t.get("title"):
                    raise ValueError("Every task needs a title.")
                imp = 1 if t.get("important") else 0
                urg = 1 if t.get("urgent") else 0
                previews.append({
                    "title": t["title"],
                    "important": bool(imp),
                    "urgent": bool(urg),
                    "quadrant": _quadrant_label(imp, urg),
                    "size": t.get("size", "medium"),
                    "category": t.get("category"),
                    "project": t.get("project"),
                    "due_date": t.get("due_date"),
                    "possible_duplicates": _find_duplicate_candidates(conn, t["title"]),
                })
        blocked = _needs_confirm(
            confirmed, {"tasks": previews, "count": len(previews)}, "add_tasks"
        )
        if blocked:
            return blocked
        created = []
        skipped = []
        with open_db(focus_db_path) as conn:
            for t in tasks:
                imp = 1 if t.get("important") else 0
                urg = 1 if t.get("urgent") else 0
                dups = _find_duplicate_candidates(conn, t["title"])
                if not allow_duplicate and _blocking_duplicates(dups):
                    skipped.append({"title": t["title"], "duplicates": dups})
                    continue
                category = t.get("category")
                if t.get("create_category") and category:
                    category_id = _resolve_or_create_category(
                        conn,
                        category,
                        color=t.get("category_color"),
                        frame_style=t.get("category_frame_style", "subtle"),
                    )
                else:
                    category_id = _resolve_category_or_error(conn, category)
                project_id = _resolve_project_or_error(conn, t.get("project"))
                row = task_svc.add_task(
                    conn,
                    title=t["title"],
                    description=t.get("description"),
                    important=imp,
                    urgent=urg,
                    size=t.get("size", "medium"),
                    category_id=category_id,
                    project_id=project_id,
                    due_date=t.get("due_date"),
                    source=t.get("source", "mcp"),
                )
                if t.get("accent_color"):
                    task_svc.update_task(conn, row["id"], accent_color=t["accent_color"])
                if t.get("priority_index") is not None:
                    task_svc.set_task_priority(conn, row["id"], t["priority_index"])
                created.append(_slim_mutate(task_svc.get_task(conn, row["id"])))
        return {
            "ok": True,
            "count": len(created),
            "tasks": created,
            "skipped": skipped,
        }

    @mcp.tool()
    def bulk_set_status(
        task_ids: list[int], status: str, confirmed: bool = False
    ) -> dict:
        """Move several tasks to the same status in one call. confirmed=True required.

        status ∈ active | pipeline (alias) | in_progress | done | archived.
        For done/archived, an active timer on an affected task is stopped first.
        Per-task issues (not found, recurring, archived) are reported inline, not fatal.
        """
        if status == "pipeline":
            status = "active"
        valid = {"active", "in_progress", "done", "archived"}
        if status not in valid:
            raise ValueError(f"status must be one of {sorted(valid)}.")
        if not task_ids:
            raise ValueError("Provide at least one task_id.")
        blocked = _needs_confirm(
            confirmed,
            {"task_ids": task_ids, "status": status, "count": len(task_ids)},
            "bulk_set_status",
        )
        if blocked:
            return blocked
        results = []
        with open_db(focus_db_path) as conn:
            for task_id in task_ids:
                task = task_svc.get_task(conn, task_id)
                if not task:
                    results.append({"id": task_id, "ok": False, "error": "not found"})
                    continue
                if task["is_recurring"]:
                    results.append(
                        {"id": task_id, "ok": False, "error": "recurring template"}
                    )
                    continue
                if status == "in_progress" and task["status"] == "archived":
                    results.append(
                        {"id": task_id, "ok": False, "error": "archived — unarchive first"}
                    )
                    continue
                if status in ("done", "archived"):
                    active = timer_svc.get_active_entry(conn)
                    if active and active["task_id"] == task_id:
                        timer_svc.stop_timer(conn)
                if status == "active":
                    task_svc.move_to_pipeline(conn, task_id)
                elif status == "in_progress":
                    task_svc.move_to_in_progress(conn, task_id)
                elif status == "done":
                    task_svc.complete_task(conn, task_id)
                elif status == "archived":
                    task_svc.archive_task(conn, task_id)
                row = task_svc.get_task(conn, task_id)
                results.append(
                    {"id": row["id"], "title": row["title"], "status": row["status"], "ok": True}
                )
        return {"ok": True, "status": status, "results": results}

    @mcp.tool()
    def bulk_place(
        task_ids: list[int],
        task_type: str | None = None,
        quadrant: str | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Ensure several tasks are on Active. confirmed=True required.

        Optional task_type ∈ adhoc|recurring|project applied to each.
        Legacy `quadrant` (do/sched/del/later) is accepted but ignored for
        placement — important/urgent flags are set from it for back-compat only.
        """
        if task_type is not None and task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}.")
        if quadrant is not None and quadrant not in _QUADRANT_FLAGS:
            raise ValueError(f"quadrant must be one of {sorted(_QUADRANT_FLAGS)}.")
        if not task_ids:
            raise ValueError("Provide at least one task_id.")
        imp = urg = None
        if quadrant is not None:
            imp, urg = _QUADRANT_FLAGS[quadrant]
        blocked = _needs_confirm(
            confirmed,
            {
                "task_ids": task_ids,
                "band": "active",
                "task_type": task_type,
                "count": len(task_ids),
            },
            "bulk_place",
        )
        if blocked:
            return blocked
        results = []
        with open_db(focus_db_path) as conn:
            for task_id in task_ids:
                task = task_svc.get_task(conn, task_id)
                if not task:
                    results.append({"id": task_id, "ok": False, "error": "not found"})
                    continue
                if imp is not None:
                    task_svc.update_task(conn, task_id, important=imp, urgent=urg)
                task_svc.set_task_band(conn, task_id, band="active", target_type=task_type)
                row = task_svc.get_task(conn, task_id)
                results.append({
                    "id": task_id,
                    "band": "active",
                    "type": task_svc.resolve_task_type(row),
                    "ok": True,
                })
        return {"ok": True, "band": "active", "results": results}

    @mcp.tool()
    def add_time_entry(
        task_id: int,
        date: str,
        start: str,
        end: str,
        tz: str = "America/Edmonton",
        confirmed: bool = False,
    ) -> dict:
        """Retroactively log time on a task (when the live timer wasn't running).

        date='YYYY-MM-DD'; start/end are local wall-clock times ('09:00' or '9:00 AM')
        in `tz` (default America/Edmonton, DST-aware). Times are converted to UTC and
        stored exactly like live-timer entries. Works on any task, including completed
        ones. confirmed=True required. Preview shows the resolved UTC range + duration.
        """
        start_dt = _parse_local_dt(date, start, tz)
        end_dt = _parse_local_dt(date, end, tz)
        if end_dt <= start_dt:
            raise ValueError("end must be after start (same day).")
        start_utc = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_utc = end_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        minutes = int((end_dt - start_dt).total_seconds() // 60)
        preview = {
            "task_id": task_id,
            "date": date,
            "start": start,
            "end": end,
            "tz": tz,
            "duration_minutes": minutes,
            "stored_utc": {"started_at": start_utc, "ended_at": end_utc},
        }
        blocked = _needs_confirm(confirmed, preview, "add_time_entry")
        if blocked:
            return blocked
        with open_db(focus_db_path) as conn:
            task = task_svc.get_task(conn, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found.")
            entry = timer_svc.add_manual_entry(conn, task_id, start_utc, end_utc)
            total = timer_svc.total_time_on_task(conn, task_id)
            return {
                "ok": True,
                "entry_id": entry["id"],
                "task_id": task_id,
                "task_title": task["title"],
                "duration_minutes": minutes,
                "task_total_seconds": total,
            }

    @mcp.tool()
    def start_work_on(
        task_id: int, confirm_switch: bool = False, confirmed: bool = False
    ) -> dict:
        """Move a task to In Progress AND start its timer in one call. confirmed=True required.

        Replaces the move_to_in_progress → start_timer two-step. If a timer is already
        running on another task, the task is still moved; pass confirm_switch=True to switch
        the timer over to it.
        """
        preview = {"task_id": task_id, "action": "move to in_progress + start timer"}
        blocked = _needs_confirm(confirmed, preview, "start_work_on")
        if blocked:
            return blocked
        move_result = _apply_move_to_in_progress(task_id)
        with open_db(focus_db_path) as conn:
            active = timer_svc.get_active_entry(conn)
            if active and active["task_id"] != task_id and not confirm_switch:
                return {
                    "ok": False,
                    "needs_confirm": True,
                    "message": (
                        "Moved to in_progress, but a timer is running on another task. "
                        "Re-call with confirm_switch=True to switch."
                    ),
                    "moved": move_result,
                    "current_task_id": active["task_id"],
                    "current_task_title": active["task_title"],
                }
            timer_svc.start_timer(conn, task_id)
            entry = timer_svc.get_active_entry(conn)
            return {
                "ok": True,
                "task_id": task_id,
                "status": "in_progress",
                "started_at": entry["started_at"],
                "elapsed_seconds": 0,
            }
