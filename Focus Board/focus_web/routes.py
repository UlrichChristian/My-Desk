"""Focus Board blueprint — all routes at /focus."""

import json
from datetime import date, datetime

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
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

_QUADRANT_META = {
    "do":    {"label": "Do First",  "color": "#f07c3a", "important": 1, "urgent": 1},
    "sched": {"label": "Schedule",  "color": "#6ebe44", "important": 1, "urgent": 0},
    "del":   {"label": "Delegate",  "color": "#1a99d6", "important": 0, "urgent": 1},
    "later": {"label": "Later",     "color": "#9aa5ab", "important": 0, "urgent": 0},
}

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


def _quadrant_key(important: int, urgent: int) -> str:
    if important and urgent:
        return "do"
    if important:
        return "sched"
    if urgent:
        return "del"
    return "later"


def _enrich_task(conn, row: dict) -> dict:
    """Attach subtask counters, time badges, and accent styling to a task dict."""
    row["subtasks_remaining"] = task_svc.subtasks_remaining(conn, row["id"])
    done, total = task_svc.subtask_progress(conn, row["id"])
    row["subtask_done"] = done
    row["subtask_total"] = total
    row["effort_label"] = _effort_label(row.get("size"))

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


def _recurring_quadrant_label(task: dict) -> str:
    if not task.get("placed"):
        return "Pipeline"
    return _QUADRANT_META[_quadrant_key(task["important"], task["urgent"])]["label"]


@focus_bp.route("/focus")
@login_required
def board():
    conn = get_db()

    unplaced = [_enrich_task(conn, dict(r)) for r in task_svc.list_unplaced(conn)]
    in_progress = [_enrich_task(conn, dict(r)) for r in task_svc.list_in_progress(conn)]
    projects = [dict(r) for r in proj_svc.list_projects(conn)]
    parent_categories = [dict(r) for r in task_svc.list_parent_categories(conn)]
    all_categories = [dict(r) for r in task_svc.list_categories(conn)]
    top_level_tasks = [dict(r) for r in task_svc.list_top_level_tasks(conn)]
    recurring_roots = [dict(r) for r in task_svc.list_recurring_roots(conn)]
    active_timer = timer_svc.get_active_entry(conn)
    if active_timer:
        active_timer = dict(active_timer)
    size_counts = task_svc.count_in_progress_by_size(conn)

    quadrants = {}
    for q_key, q_tasks in task_svc.list_by_quadrant(conn).items():
        quadrants[q_key] = [_enrich_task(conn, dict(t)) for t in q_tasks]

    # Project backlogs
    backlog_rows = [_enrich_task(conn, dict(r)) for r in task_svc.list_unplaced_by_project(conn)]
    backlog_by_proj: dict[int, list] = {}
    for row in backlog_rows:
        backlog_by_proj.setdefault(row["project_id"], []).append(row)

    projects_done, projects_total = task_svc.projects_aggregate_counts(conn)
    project_backlogs = []
    for proj in projects:
        pid = proj["id"]
        done, total = task_svc.project_task_counts(conn, pid)
        project_backlogs.append({
            "project": proj,
            "tasks": backlog_by_proj.get(pid, []),
            "done": done,
            "total": total,
        })

    # Recurring templates
    recurring = []
    for tmpl in task_svc.list_recurring_templates(conn):
        root = dict(tmpl["root"])
        root["quadrant_label"] = _recurring_quadrant_label(root)
        subs = []
        for s in tmpl["subtasks"]:
            sd = dict(s)
            sd["quadrant_label"] = _recurring_quadrant_label(sd)
            subs.append(sd)
        recurring.append({"root": root, "subtasks": subs})

    completed = []
    for t in task_svc.list_recently_completed(conn, 5):
        row = dict(t)
        row["total_secs"] = timer_svc.total_time_on_task(conn, row["id"])
        row["enthusiasm_emoji"] = _ENTHUSIASM_EMOJI.get(row.get("enthusiasm"), "")
        completed.append(row)

    elapsed = None
    if active_timer:
        elapsed = timer_svc.elapsed_seconds(active_timer["started_at"])

    return render_template(
        "focus/board.html",
        unplaced=unplaced,
        quadrants=quadrants,
        quadrant_meta=_QUADRANT_META,
        in_progress=in_progress,
        completed=completed,
        projects=projects,
        project_backlogs=project_backlogs,
        projects_done=projects_done,
        projects_total=projects_total,
        parent_categories=parent_categories,
        all_categories=all_categories,
        top_level_tasks=top_level_tasks,
        recurring_roots=recurring_roots,
        recurring=recurring,
        active_timer=active_timer,
        elapsed=elapsed,
        size_counts=size_counts,
        enthusiasm_emoji=_ENTHUSIASM_EMOJI,
        effort_labels=_EFFORT_LABELS,
        palette=color_svc.PALETTE,
        frame_styles=color_svc.FRAME_STYLES,
    )


@focus_bp.route("/focus/task/add", methods=["POST"])
@login_required
def add_task():
    conn = get_db()
    title = (request.form.get("title") or "").strip()
    if not title:
        return redirect(url_for("focus.board"))

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
            placed = 1 if (important or urgent) else 0
    else:
        placed = 1 if (important or urgent) else 0

    # Project-only tasks stay unplaced in backlog
    if project_id and not important and not urgent:
        placed = 0

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
        return redirect(url_for("focus.board"))

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
    return redirect(url_for("focus.board"))


@focus_bp.route("/focus/project/add", methods=["POST"])
@login_required
def add_project():
    conn = get_db()
    name = (request.form.get("name") or "").strip()
    if name:
        proj_svc.add_project(
            conn, name=name, description=request.form.get("description") or None
        )
    return redirect(url_for("focus.board"))


@focus_bp.route("/focus/projects/reorder", methods=["POST"])
@login_required
def reorder_projects():
    conn = get_db()
    data = _request_json()
    order = [int(x) for x in data.get("order", [])]
    if order:
        proj_svc.reorder_projects(conn, order)
    return jsonify({"ok": True})


@focus_bp.route("/focus/task/<int:task_id>/place", methods=["POST"])
@login_required
def place_task(task_id):
    conn = get_db()
    if request.is_json:
        quadrant = _request_json().get("quadrant", "later")
    else:
        quadrant = request.form.get("quadrant", "later")
    meta = _QUADRANT_META.get(quadrant, _QUADRANT_META["later"])
    task_svc.place_task(conn, task_id, meta["important"], meta["urgent"])
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("focus.board"))


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
            return redirect(url_for("focus.board"))
        active = timer_svc.get_active_entry(conn)
        if active and active["task_id"] == task_id:
            timer_svc.stop_timer(conn)
        enthusiasm = _int_or_none(
            request.form.get("enthusiasm") or _request_json().get("enthusiasm")
        )
        task_svc.complete_task(conn, task_id, enthusiasm)
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("focus.board"))


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
        return redirect(url_for("focus.board"))
    if request.is_json:
        return jsonify({"ok": True, "status": to_status})
    return redirect(url_for("focus.board"))


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


@focus_bp.route("/focus/task/<int:task_id>/order", methods=["POST"])
@login_required
def update_order(task_id):
    conn = get_db()
    data = _request_json()
    sort_order = int(data.get("sort_order", 0))
    quadrant = data.get("quadrant")
    if quadrant:
        meta = _QUADRANT_META.get(quadrant, _QUADRANT_META["later"])
        task_svc.place_task(conn, task_id, meta["important"], meta["urgent"])
    task_svc.update_sort_order(conn, task_id, sort_order)
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
        )
        if not has_subtasks:
            updates["parent_id"] = _int_or_none(request.form.get("parent_id"))
        task_svc.update_task(conn, task_id, **updates)
        return redirect(url_for("focus.board"))

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
    return redirect(url_for("focus.board"))


@focus_bp.route("/focus/recurring/<int:template_id>/start", methods=["POST"])
@login_required
def start_recurring(template_id):
    conn = get_db()
    task_svc.instantiate_recurring(conn, template_id)
    return redirect(url_for("focus.board"))


@focus_bp.route("/focus/timer/start/<int:task_id>", methods=["POST"])
@login_required
def start_timer(task_id):
    conn = get_db()
    timer_svc.start_timer(conn, task_id)
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("focus.board"))


@focus_bp.route("/focus/timer/stop", methods=["POST"])
@login_required
def stop_timer():
    conn = get_db()
    timer_svc.stop_timer(conn)
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("focus.board"))


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
