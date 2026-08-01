# Focus Board — Context & Design

## What this is
Flask Blueprint at `/focus` on :5002 (My Desk). Personal task management
for Christian Ulrich. Migrated from the v5 operating canvas (HTML + localStorage).

## Architecture
- Entry: registered in `C:/Christian/c.py` at url_prefix `/focus`
- DB: `C:/Christian/Focus Board/focus.db` (own SQLite)
- Blueprint name: `focus`
- Templates: `templates/focus/` (namespaced)
- Static: `static/focus/` (namespaced)

## Standing rule
Every automation mirrored in Process Street: to-do step + audit step.

## Task flow
```
Quick-add → Pipeline (unplaced, no project) OR Project backlog (placed=0, has project_id)
         → drag to quadrant (placed=1) → Start → In Progress → Done
Recurring templates live in Recurring section; Start clones tree into saved quadrants.
```

## Board section order (top → bottom)
Timer · Quick-add · In Progress Today · Focus Matrix · Pipeline · Projects · Recurring · Recently Completed

## Quadrant colours
- Do First  (important + urgent):      Orange  #f07c3a
- Schedule  (important + not urgent):  Green   #6ebe44
- Delegate  (not important + urgent):  Blue    #1a99d6
- Later     (not important + not urgent): Grey #9aa5ab

Quadrant left-accent colours are unchanged. Category/task accent adds an **outer gradient frame** on matrix, kanban, and pipeline tiles (see below).

## Category colours & gradient frames
- Each category has a curated EA palette colour (`categories.color`) and frame intensity (`categories.frame_style`: `subtle` | `medium` | `bold`).
- Tasks may override with optional `accent_color` (swatch picker only — no free-form hex).
- `focus_services/colors.py` — palette, `FRAME_STYLES`, `resolve_task_accent()`.
- **Categories page:** `/focus/categories` — add parent/sub, edit colour + frame style.
- Quick-add and task edit forms support inline new category with colour + frame.
- CSS: `.has-accent.frame-{subtle|medium|bold}` gradient border on task surfaces; category chips use accent colour.

## Procrastination marker (manual v1)
- `tasks.procrastinate` — manual toggle only (no auto-learning in this app).
- Edit task checkbox + board quick toggle (`POST /focus/task/<id>/procrastinate`).
- Visual: inner red inset ring (`.procrastinate`) stacks inside outer category frame when both set.

## Key schema notes
- `placed=0` + `status='pipeline'` + no `project_id` → pipeline list
- `placed=0` + `status='pipeline'` + `project_id` → project backlog (Projects section)
- `placed=1` + `status='pipeline'` → Focus Matrix
- `placed=1` + `status='in_progress'` → Kanban board
- `status='done'` → recently completed (reopen via board Reopen button or MCP `reopen_task`)
- `status='archived'` → hidden from board (set via Edit → Archive task)
- `is_recurring=1` → template only (Recurring section; excluded from active lists)
- `pending_since` → stamped when task lands in Schedule/Later; drives ⏳ days-pending badge
- `size` column (shown as **Effort** in UI): Small / Med / Large — drives 1-3-5 rule counter
- `enthusiasm` field: 1-5 integer, set on completion (😩😐🙂😄🤩)
- `source` field: manual | process_street | email_sweep | canvas_import
- `priority_index` — MCP-only focus rank (1 = do first). Not shown on web board. Cleared on complete/archive.

## MCP focus queue (priority_index)
- Separate from board `sort_order` (drag order within a quadrant/list).
- Claude assigns via `set_priority_queue([id, ...])` or `set_task_priority(task_id, n)`.
- `list_priority_queue()` returns the ordered focus list during check-ins.
- `reindex_task_priorities()` compacts to 1..n when numbers get sparse.
- Root active tasks only (not subtasks, recurring templates, done, or archived).

## Integrations (phases)
- Phase 2: Workspace MCP server at `C:/Christian/mcp/server.py` — focus tools in `mcp/focus_mcp.py`
  - All mutating tools require `confirmed=True` unless user explicitly requested the change in the same turn (preview otherwise).
  - Lifecycle: `archive_task`, `unarchive_task`, `list_archived_tasks`, `move_to_pipeline`, `reopen_task` (done → pipeline/in_progress).
  - Task wording: `get_task_style_guide` + read-only `suggest_task_wording`; style note at `Knowledge App/notes/focus-task-style.md`.
  - Timer: `move_to_in_progress` (or `start_work`) → `start_timer` (cautious switch confirm) → `stop_timer`; `complete_task` stops active timer.
  - Categories: `add_category` (parent or sub); `add_task` / `update_task` accept `create_category=True` to create missing categories inline (parity with web quick-add).
  - Focus queue: `list_priority_queue`, `set_priority_queue`, `set_task_priority`, `reindex_task_priorities` (MCP-only `priority_index` on tasks).
  - Recurring templates: `get_recurring_template`, `add_recurring_template`, `add_recurring_subtask`, `update_recurring_task`, `list_recurring_templates`, `start_recurring` (clone to active board).
  - Board reads: `list_active_board` (in-progress + matrix quadrants), `search_tasks` (fuzzy title/description).
- Phase 3: Process Street API (key in `.env`)
- Email sweep: Claude chat + Outlook MCP + workspace MCP (no app button)

## Logging
Session notes → `C:/Christian/Knowledge App/logs/YYYY-MM-DD.md`
(No journal table in this app — Knowledge App will handle that later)

## Canvas migration
34 items seeded on first run from `My operating canvas.html` localStorage data.
Source = `canvas_import` on all migrated rows.
