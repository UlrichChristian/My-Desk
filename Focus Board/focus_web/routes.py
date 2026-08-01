"""Focus Board blueprint — all routes at /focus."""

from datetime import date, datetime

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from focus_db.connection import get_db
from focus_services import colors as color_svc
from focus_services import projects as proj_svc
from focus_services import tasks as task_svc
from focus_services import time_tracker as timer_svc
from services.auth import login_required

focus_bp = Blueprint(
    "focus",
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/focus/static",
)

_EFFORT_LABELS = {"small": "Small", "medium": "Med", "big": "Large"}

_ENTHUSIASM_EMOJI = {1: "😩", 2: "😐", 3: "🙂", 4: "😄", 5: "🤩"}


def _int_or_none(val) -> int | None:
    try:
        return int(val) if val else None
    except (TypeError, ValueError):
        return None


def _checkbox_int(name: str) -> int:
    return 1 if request.form.get(name) else 0


def _request_json() -> dict:
    """JSON body when present; empty dict for form posts (avoids 415 on request.json)."""
    return request.get_json(silent=True) or {}


def _resolve_category_id(conn) -> int | None:
    """Resolve category from parent/subcategory selects or new category text."""
    raw_parent = request.form.get("parent_category_id")
    new_cat = (request.form.get("new_category") or "").strip()
    new_sub = (request.form.get("new_subcategory") or "").strip()
    child_id = _int_or_none(request.form.get("category_id"))
    parent_id = _int_or_none(raw_parent) if raw_parent not in (None, "", "__new__") else None
    cat_color = request.form.get("new_category_color") or None
    cat_frame = request.form.get("new_category_frame_style") or "subtle"

    if raw_parent == "__new__" and new_cat:
        parent_id = task_svc.get_or_create_category(
            conn, new_cat, None, color=cat_color, frame_style=cat_frame
        )
    if new_sub and parent_id:
        return task_svc.get_or_create_category(conn, new_sub, parent_id)
    if child_id:
        return child_id
    if parent_id:
        return parent_id
    return None


def _accent_hex_from_form() -> str | None:
    val = (request.form.get("accent_color") or "").strip()
    if not val or val == "__inherit__":
        return None
    if val.lower() in color_svc.palette_hex_ids():
        return val
    return None


def _effort_label(size: str | None) -> str:
    return _EFFORT_LABELS.get(size or "medium", "Med")


def _enrich_task(conn, row: dict) -> dict:
    """Attach subtask counters, time badges, and accent styling to a task dict."""
    row["subtasks_remaining"] = task_svc.subtasks_remaining(conn, row["id"])
    done, total = task_svc.subtask_progress(conn, row["id"])
    row["subtask_done"] = done
    row["subtask_total"] = total
    row["effort_label"] = _effort_label(row.get("size"))
    row["task_type"] = task_svc.resolve_task_type(row)

    accent, frame_style = color_svc.resolve_task_accent(row)
    row["accent"] = accent
    row["frame_style"] = frame_style
    row["has_accent"] = accent is not None

    urgent = row.get("urgent", 0)
    if urgent:
        row["time_badge"] = _due_badge(row.get("due_date"))
    else:
        row["time_badge"] = _pending_badge(
            row.get("pending_since"), row.get("created_on")
        )
    return row


def _redirect_board():
    return redirect(url_for("focus.board"))


def _pending_badge(pending_since: str | None, created_on: str | None) -> dict | None:
    stamp = pending_since or created_on
    if not stamp:
        return None
    try:
        start = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
    except ValueError:
        start = date.fromisoformat(stamp[:10])
    days = (date.today() - start).days
    return {"type": "pending", "days": days, "text": f"⏳ {days}d pending"}


def _due_badge(due_date: str | None) -> dict | None:
    if not due_date:
        return None
    try:
        due = date.fromisoformat(due_date[:10])
    except ValueError:
        return None
    delta = (due - date.today()).days
    if delta < 0:
        return {"type": "overdue", "days": delta, "text": f"{abs(delta)}d overdue"}
    if delta == 0:
        return {"type": "today", "days": 0, "text": "due today"}
    return {"type": "due", "days": delta, "text": f"due in {delta}d"}


_ACTIVE_TYPE_META = {
    "adhoc":     {"label": "To-do",     "icon": "•"},
    "recurring": {"label": "Recurring", "icon": "↻"},
    "project":   {"label": "Projects",  "icon": "▤"},
}


@focus_bp.route("/focus")
@login_required
def board():
    """Type-based board: Today · Active (To-do/Project/Recurring) · Pipeline · Completed."""
    conn = get_db()

    today = [_enrich_task(conn, dict(r)) for r in task_svc.list_in_progress(conn)]

    # Active band, grouped by resolved type
    active = {}
    for t_key, rows in task_svc.list_active_by_type(conn).items():
        active[t_key] = [_enrich_task(conn, dict(r)) for r in rows]

    # To-do keeps the Eisenhower model, rendered vertically. A reached due date
    # is promoted to Do Now without mutating its explicit flags.
    adhoc_quadrants = {
        "do": [],
        "schedule": [],
        "delegate": [],
        "later": [],
    }
    today_date = date.today()
    for row in active.get("adhoc", []):
        due_reached = False
        if row.get("due_date"):
            try:
                due_reached = date.fromisoformat(row["due_date"][:10]) <= today_date
            except ValueError:
                pass
        row["due_reached"] = due_reached
        if due_reached or (row.get("urgent") and row.get("important")):
            quadrant = "do"
        elif row.get("important"):
            quadrant = "schedule"
        elif row.get("urgent"):
            quadrant = "delegate"
        else:
            quadrant = "later"
        adhoc_quadrants[quadrant].append(row)

    adhoc_sections = [
        {
            "key": "do",
            "label": "Do Now",
            "note": "urgent + important, or due",
            "tasks": adhoc_quadrants["do"],
        },
        {
            "key": "schedule",
            "label": "Schedule",
            "note": "important, not urgent",
            "tasks": adhoc_quadrants["schedule"],
        },
        {
            "key": "delegate",
            "label": "Delegate",
            "note": "urgent, not important",
            "tasks": adhoc_quadrants["delegate"],
        },
        {
            "key": "later",
            "label": "Later",
            "note": "neither urgent nor important",
            "tasks": adhoc_quadrants["later"],
        },
    ]

    # Project column: every active project, even with zero Active tasks yet
    project_groups: list[dict] = []
    seen: dict = {}
    for proj in proj_svc.list_projects(conn):
        pid = proj["id"]
        seen[pid] = {
            "project_id": pid,
            "name": proj["name"],
            "completion_pct": int(proj["completion_pct"] or 0),
            "tasks": [],
        }
        project_groups.append(seen[pid])
    for row in active.get("project", []):
        pid = row.get("project_id")
        if pid in seen:
            seen[pid]["tasks"].append(row)
        else:
            # Orphaned project link — still show under a named group
            seen[pid] = {
                "project_id": pid,
                "name": row.get("project_name") or "No project",
                "completion_pct": 0,
                "tasks": [row],
            }
            project_groups.append(seen[pid])

    # Recurring Active groups: roots only; expand shows their subtasks
    recurring_groups: list[dict] = []
    for row in active.get("recurring", []):
        if row.get("parent_id"):
            continue
        group = dict(row)
        group["subtasks"] = [
            _enrich_task(conn, dict(s))
            for s in task_svc.list_child_tasks(conn, row["id"])
        ]
        recurring_groups.append(group)

    # Pipeline = all not-yet-active tasks (placed=0), with or without a project
    pipeline = [_enrich_task(conn, dict(r)) for r in task_svc.list_unplaced(conn)]
    pipeline += [_enrich_task(conn, dict(r)) for r in task_svc.list_unplaced_by_project(conn)]

    completed = []
    for t in task_svc.list_recently_completed(conn, 8):
        row = dict(t)
        row["total_secs"] = timer_svc.total_time_on_task(conn, row["id"])
        row["enthusiasm_emoji"] = _ENTHUSIASM_EMOJI.get(row.get("enthusiasm"), "")
        completed.append(row)

    # Recurring templates (Start → clones into the Active Recurring column)
    recurring = []
    for tmpl in task_svc.list_recurring_templates(conn):
        recurring.append({
            "root": dict(tmpl["root"]),
            "subtasks": [dict(s) for s in tmpl["subtasks"]],
        })

    active_timer = timer_svc.get_active_entry(conn)
    if active_timer:
        active_timer = dict(active_timer)
    elapsed = timer_svc.elapsed_seconds(active_timer["started_at"]) if active_timer else None
    size_counts = task_svc.count_in_progress_by_size(conn)

    projects = [dict(r) for r in proj_svc.list_projects(conn)]
    project_management = []
    for project in projects:
        done, total = task_svc.project_task_counts(conn, project["id"])
        project_management.append({
            "project": project,
            "done": done,
            "total": total,
        })
    parent_categories = [dict(r) for r in task_svc.list_parent_categories(conn)]
    all_categories = [dict(r) for r in task_svc.list_categories(conn)]
    top_level_tasks = [dict(r) for r in task_svc.list_top_level_tasks(conn)]
    recurring_roots = [dict(r) for r in task_svc.list_recurring_roots(conn)]

    return render_template(
        "focus/board.html",
        today=today,
        active=active,
        adhoc_sections=adhoc_sections,
        active_type_meta=_ACTIVE_TYPE_META,
        project_groups=project_groups,
        recurring_groups=recurring_groups,
        pipeline=pipeline,
        completed=completed,
        recurring=recurring,
        active_timer=active_timer,
        elapsed=elapsed,
        size_counts=size_counts,
        projects=projects,
        project_management=project_management,
        parent_categories=parent_categories,
        all_categories=all_categories,
        top_level_tasks=top_level_tasks,
        recurring_roots=recurring_roots,
        enthusiasm_emoji=_ENTHUSIASM_EMOJI,
        palette=color_svc.PALETTE,
        frame_styles=color_svc.FRAME_STYLES,
    )


@focus_bp.route("/focus/task/<int:task_id>/band", methods=["POST"])
@login_required
def set_band(task_id):
    """Move lifecycle band; an optional To-do quadrant updates explicit flags."""
    data = _request_json()
    band = data.get("band")
    if band not in ("today", "active", "pipeline"):
        abort(400)
    quadrant = data.get("quadrant")
    quadrant_flags = {
        "do": (1, 1),
        "schedule": (1, 0),
        "delegate": (0, 1),
        "later": (0, 0),
    }
    if quadrant is not None and quadrant not in quadrant_flags:
        abort(400)
    conn = get_db()
    if band == "active" and quadrant:
        important, urgent = quadrant_flags[quadrant]
        task_svc.update_task(
            conn,
            task_id,
            important=important,
            urgent=urgent,
        )
    task_svc.set_task_band(conn, task_id, band=band, target_type=data.get("type"))
    return jsonify({"ok": True})


@focus_bp.route("/focus/task/add", methods=["POST"])
@login_required
def add_task():
    conn = get_db()
    title = (request.form.get("title") or "").strip()
    if not title:
        return _redirect_board()

    important = _checkbox_int("important")
    urgent = _checkbox_int("urgent")
    is_recurring = _checkbox_int("is_recurring")
    project_id = _int_or_none(request.form.get("project_id"))
    parent_id = _int_or_none(request.form.get("parent_id"))

    # Inherit placement from parent when adding subtask via tile
    inherit_parent = request.form.get("inherit_parent")
    if inherit_parent and parent_id:
        parent = task_svc.get_task(conn, parent_id)
        if parent:
            important = parent["important"]
            urgent = parent["urgent"]
            placed = parent["placed"]
            if parent["is_recurring"]:
                is_recurring = 1
            if not project_id:
                project_id = parent["project_id"]
        else:
            placed = 0
    else:
        # Important/urgent are flags only — new tasks land in Pipeline,
        # unless Activate was requested (e.g. add from a project group).
        placed = 1 if request.form.get("activate") else 0

    category_id = _resolve_category_id(conn)

    try:
        if is_recurring and parent_id:
            parent_id, redirect_note = task_svc.resolve_recurring_parent(
                conn, parent_id, is_recurring=bool(is_recurring)
            )
            if redirect_note:
                flash(redirect_note, "success")
            important, urgent, placed = task_svc.placement_from_recurring_root(
                conn, parent_id, important=important, urgent=urgent, placed=placed
            )
    except ValueError as exc:
        flash(str(exc), "error")
        return _redirect_board()

    task_svc.add_task(
        conn,
        title=title,
        description=request.form.get("description") or None,
        important=important,
        urgent=urgent,
        placed=placed,
        category_id=category_id,
        project_id=project_id,
        parent_id=parent_id,
        size=request.form.get("size") or "medium",
        due_date=request.form.get("due_date") or None,
        is_recurring=is_recurring,
        source="manual",
    )
    return _redirect_board()


@focus_bp.route("/focus/project/add", methods=["POST"])
@login_required
def add_project():
    conn = get_db()
    name = (request.form.get("name") or "").strip()
    if name:
        proj_svc.add_project(
            conn, name=name, description=request.form.get("description") or None
        )
    return _redirect_board()


@focus_bp.route("/focus/project/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    conn = get_db()
    project_row = proj_svc.get_project(conn, project_id)
    if not project_row:
        abort(404)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Project name is required.", "error")
        else:
            raw_pct = (request.form.get("completion_pct") or "").strip()
            try:
                completion_pct = int(raw_pct) if raw_pct != "" else 0
            except ValueError:
                flash("Completion must be a whole number from 0 to 100.", "error")
                completion_pct = None
            if completion_pct is not None:
                proj_svc.update_project(
                    conn,
                    project_id,
                    name=name,
                    description=(request.form.get("description") or "").strip() or None,
                    status="archived" if _checkbox_int("archived") else "active",
                    completion_pct=completion_pct,
                )
                return _redirect_board()

    done, total = task_svc.project_task_counts(conn, project_id)
    return render_template(
        "focus/project_form.html",
        project=dict(project_row),
        done=done,
        total=total,
    )


@focus_bp.route("/focus/projects/reorder", methods=["POST"])
@login_required
def reorder_projects():
    conn = get_db()
    data = _request_json()
    order = [int(x) for x in data.get("order", [])]
    if order:
        proj_svc.reorder_projects(conn, order)
    return jsonify({"ok": True})


@focus_bp.route("/focus/task/<int:task_id>/status", methods=["POST"])
@login_required
def update_status(task_id):
    conn = get_db()
    new_status = request.form.get("status") or _request_json().get("status")
    if new_status == "in_progress":
        task_svc.move_to_in_progress(conn, task_id)
    elif new_status == "pipeline":
        task_svc.move_to_pipeline(conn, task_id)
    elif new_status == "done":
        task = task_svc.get_task(conn, task_id)
        if task and task["is_recurring"]:
            if request.is_json:
                return jsonify({"ok": False, "error": "Cannot complete recurring template"}), 400
            return _redirect_board()
        active = timer_svc.get_active_entry(conn)
        if active and active["task_id"] == task_id:
            timer_svc.stop_timer(conn)
        enthusiasm = _int_or_none(
            request.form.get("enthusiasm") or _request_json().get("enthusiasm")
        )
        task_svc.complete_task(conn, task_id, enthusiasm)
    if request.is_json:
        return jsonify({"ok": True})
    return _redirect_board()


@focus_bp.route("/focus/task/<int:task_id>/reopen", methods=["POST"])
@login_required
def reopen_task(task_id):
    conn = get_db()
    to_status = request.form.get("to_status") or _request_json().get("to_status") or "pipeline"
    if to_status not in ("pipeline", "in_progress"):
        to_status = "pipeline"
    try:
        task_svc.reopen_task(conn, task_id, to_status=to_status)
    except ValueError as exc:
        if request.is_json:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return _redirect_board()
    if request.is_json:
        return jsonify({"ok": True, "status": to_status})
    return _redirect_board()


@focus_bp.route("/focus/task/<int:task_id>/time", methods=["GET"])
@login_required
def task_time(task_id):
    """Time-entry history + total for a task (JSON). Timestamps are UTC ISO."""
    conn = get_db()
    if not task_svc.get_task(conn, task_id):
        abort(404)
    entries = timer_svc.list_entries_for_task(conn, task_id, limit=100)
    return jsonify({
        "ok": True,
        "total_seconds": timer_svc.total_time_on_task(conn, task_id),
        "entries": [
            {
                "id": e["id"],
                "started_at": e["started_at"],
                "ended_at": e["ended_at"],
                "duration_seconds": e["duration_seconds"],
            }
            for e in entries
        ],
    })


@focus_bp.route("/focus/task/<int:task_id>/time/add", methods=["POST"])
@login_required
def task_time_add(task_id):
    """Add a manual (retroactive) time entry. Body: {started_at, ended_at} UTC ISO."""
    conn = get_db()
    if not task_svc.get_task(conn, task_id):
        abort(404)
    data = _request_json()
    try:
        timer_svc.add_manual_entry(
            conn, task_id, data.get("started_at"), data.get("ended_at")
        )
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})


@focus_bp.route("/focus/time/<int:entry_id>/edit", methods=["POST"])
@login_required
def task_time_edit(entry_id):
    """Edit an entry's start/end. Body: {started_at, ended_at} UTC ISO."""
    conn = get_db()
    data = _request_json()
    try:
        row = timer_svc.update_entry(
            conn, entry_id, data.get("started_at"), data.get("ended_at")
        )
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not row:
        return jsonify({"ok": False, "error": "Entry not found."}), 404
    return jsonify({"ok": True})


@focus_bp.route("/focus/time/<int:entry_id>/delete", methods=["POST"])
@login_required
def task_time_delete(entry_id):
    conn = get_db()
    timer_svc.delete_entry(conn, entry_id)
    return jsonify({"ok": True})


@focus_bp.route("/focus/tasks/reorder", methods=["POST"])
@login_required
def reorder_tasks():
    conn = get_db()
    data = _request_json()
    order = [int(x) for x in data.get("order", [])]
    if order:
        task_svc.reorder_tasks(conn, order)
    return jsonify({"ok": True})


@focus_bp.route("/focus/task/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    conn = get_db()
    task_row = task_svc.get_task(conn, task_id)
    if not task_row:
        abort(404)
    if request.method == "POST":
        archived = _checkbox_int("archived")
        if archived and task_row["status"] != "archived":
            active = timer_svc.get_active_entry(conn)
            if active and active["task_id"] == task_id:
                timer_svc.stop_timer(conn)
            task_svc.archive_task(conn, task_id)
        elif not archived and task_row["status"] == "archived":
            task_svc.unarchive_task(conn, task_id)
        has_subtasks = bool(task_svc.get_subtasks(conn, task_id))
        updates = dict(
            title=request.form.get("title", task_row["title"]),
            description=request.form.get("description") or None,
            size=request.form.get("size") or "medium",
            category_id=_resolve_category_id(conn),
            project_id=_int_or_none(request.form.get("project_id")),
            due_date=request.form.get("due_date") or None,
            is_recurring=_checkbox_int("is_recurring"),
            accent_color=_accent_hex_from_form(),
            procrastinate=_checkbox_int("procrastinate"),
            waiting_on=(request.form.get("waiting_on") or "").strip() or None,
            important=_checkbox_int("important"),
            urgent=_checkbox_int("urgent"),
        )
        if "type_override" in request.form:
            override = (request.form.get("type_override") or "").strip() or None
            updates["type_override"] = (
                override if override in ("adhoc", "recurring", "project") else None
            )
        if not has_subtasks:
            updates["parent_id"] = _int_or_none(request.form.get("parent_id"))
        task_svc.update_task(conn, task_id, **updates)
        return _redirect_board()

    task = dict(task_row)
    categories = task_svc.list_categories(conn)
    parent_categories = task_svc.list_parent_categories(conn)
    projects = proj_svc.list_projects(conn)
    has_subtasks = bool(task_svc.get_subtasks(conn, task_id))
    parent_tasks = task_svc.list_parent_task_options(
        conn,
        exclude_task_id=task_id,
        for_recurring=bool(task["is_recurring"]),
        current_parent_id=task["parent_id"],
    )

    # Resolve current category into parent + child for the form
    current_parent_id = None
    current_child_id = None
    if task["category_id"]:
        cat = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (task["category_id"],)
        ).fetchone()
        if cat:
            if cat["parent_id"]:
                current_parent_id = cat["parent_id"]
                current_child_id = cat["id"]
            else:
                current_parent_id = cat["id"]

    return render_template(
        "focus/task_form.html",
        task=task,
        categories=categories,
        parent_categories=parent_categories,
        parent_tasks=parent_tasks,
        has_subtasks=has_subtasks,
        projects=projects,
        current_parent_id=current_parent_id,
        current_child_id=current_child_id,
        effort_labels=_EFFORT_LABELS,
        palette=color_svc.PALETTE,
        frame_styles=color_svc.FRAME_STYLES,
    )


@focus_bp.route("/focus/categories", methods=["GET", "POST"])
@login_required
def categories():
    conn = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_parent":
            name = (request.form.get("name") or "").strip()
            if name:
                task_svc.get_or_create_category(
                    conn,
                    name,
                    None,
                    color=request.form.get("color") or color_svc.DEFAULT_COLOR,
                    frame_style=request.form.get("frame_style") or "subtle",
                )
        elif action == "add_sub":
            name = (request.form.get("name") or "").strip()
            parent_id = _int_or_none(request.form.get("parent_id"))
            if name and parent_id:
                task_svc.get_or_create_category(conn, name, parent_id)
        elif action == "update":
            cat_id = _int_or_none(request.form.get("category_id"))
            if cat_id:
                task_svc.update_category(
                    conn,
                    cat_id,
                    color=request.form.get("color"),
                    frame_style=request.form.get("frame_style"),
                )
        return redirect(url_for("focus.categories"))

    all_cats = [dict(r) for r in task_svc.list_categories(conn)]
    parents = [c for c in all_cats if not c.get("parent_id")]
    children_by_parent: dict[int, list] = {}
    for c in all_cats:
        if c.get("parent_id"):
            children_by_parent.setdefault(c["parent_id"], []).append(c)

    return render_template(
        "focus/categories.html",
        parents=parents,
        children_by_parent=children_by_parent,
        palette=color_svc.PALETTE,
        frame_styles=color_svc.FRAME_STYLES,
    )


@focus_bp.route("/focus/task/<int:task_id>/procrastinate", methods=["POST"])
@login_required
def toggle_procrastinate(task_id):
    conn = get_db()
    new_val = task_svc.toggle_procrastinate(conn, task_id)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "procrastinate": bool(new_val)})
    return _redirect_board()


@focus_bp.route("/focus/recurring/<int:template_id>/start", methods=["POST"])
@login_required
def start_recurring(template_id):
    conn = get_db()
    task_svc.instantiate_recurring(conn, template_id)
    return _redirect_board()


@focus_bp.route("/focus/timer/start/<int:task_id>", methods=["POST"])
@login_required
def start_timer(task_id):
    conn = get_db()
    timer_svc.start_timer(conn, task_id)
    if request.is_json:
        return jsonify({"ok": True})
    return _redirect_board()


@focus_bp.route("/focus/timer/stop", methods=["POST"])
@login_required
def stop_timer():
    conn = get_db()
    timer_svc.stop_timer(conn)
    if request.is_json:
        return jsonify({"ok": True})
    return _redirect_board()


@focus_bp.route("/focus/timer/status")
@login_required
def timer_status():
    conn = get_db()
    entry = timer_svc.get_active_entry(conn)
    if entry is None:
        return jsonify({"active": False})
    return jsonify({
        "active": True,
        "task_id": entry["task_id"],
        "task_title": entry["task_title"],
        "started_at": entry["started_at"],
        "elapsed_seconds": timer_svc.elapsed_seconds(entry["started_at"]),
    })
