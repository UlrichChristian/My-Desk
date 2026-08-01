"""
My Desk — workspace MCP server (stdio).

Exposes workspace tools to Claude, gated by the permissions stored in c.db.
Run by an MCP client (e.g. Claude Desktop / Claude Code) via stdio — not by c.py.

Permission model
-----------------
The acting user defaults to `culrich` (override with env MY_DESK_USER). At startup
we read that user's permissions from c.db and only register the tool groups they
are entitled to. Today that means the `focus` permission unlocks the
focus tools; future apps (financial, knowledge) plug in the same way.

Database access
---------------
This process runs outside Flask, so it cannot use the request-scoped `g`
connections. Each tool opens its own short-lived sqlite connection. The service
modules take a plain connection and never import Flask, so they are reused as-is.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime

# ── Make the workspace packages importable ──────────────────────────────────
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_MCP_DIR)
_C_APP_DIR = os.path.join(_ROOT, "c App")
_FOCUS_APP_DIR = os.path.join(_ROOT, "Focus Board")
sys.path.insert(0, _C_APP_DIR)        # claims `services`, `db`
sys.path.insert(1, _FOCUS_APP_DIR)     # claims `focus_services`, `focus_db`

from mcp.server.fastmcp import FastMCP

from services.users import get_user_permissions

# ── Paths & config ───────────────────────────────────────────────────────────
C_DB_PATH = os.path.join(_C_APP_DIR, "c.db")
FOCUS_DB_PATH = os.path.join(_FOCUS_APP_DIR, "focus.db")
KNOWLEDGE_LOGS_DIR = os.path.join(_ROOT, "Knowledge App", "logs")
KNOWLEDGE_NOTES_DIR = os.path.join(_ROOT, "Knowledge App", "notes")
ACTING_USER = os.environ.get("MY_DESK_USER", "culrich")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@contextmanager
def _open(db_path: str):
    """Yield a row-factory sqlite connection, always closed afterwards."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def _current_permissions() -> set[str]:
    with _open(C_DB_PATH) as conn:
        return get_user_permissions(conn, ACTING_USER)


# ── Server ────────────────────────────────────────────────────────────────────
mcp = FastMCP("My Desk")

_PERMS = _current_permissions()


# ── Focus Board tools ─────────────────────────────────────────────────────────
if "focus" in _PERMS:
    sys.path.insert(0, _MCP_DIR)
    from focus_mcp import register_focus_tools

    register_focus_tools(
        mcp,
        focus_db_path=FOCUS_DB_PATH,
        notes_dir=KNOWLEDGE_NOTES_DIR,
        open_db=_open,
    )


# ── Knowledge journal tools ─────────────────────────────────────────────────────
if "knowledge" in _PERMS:

    def _journal_path(date: str) -> str:
        if not _DATE_RE.match(date):
            raise ValueError("date must be in YYYY-MM-DD format")
        return os.path.join(KNOWLEDGE_LOGS_DIR, f"{date}.md")

    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @mcp.tool()
    def journal_add_entry(
        text: str, topic: str | None = None, date: str | None = None
    ) -> dict:
        """Append a timestamped entry to a daily journal/log file (Knowledge App/logs).

        A free-form running log — no rigid structure required. Creates the day's
        file (YYYY-MM-DD.md) with a date header if it doesn't exist yet, then appends
        a "## HH:MM — topic" entry. Use it for notes, decisions, correspondence,
        carrier info, time spent on off-board work — whatever's worth keeping.

        Args:
            text: The entry body (markdown allowed).
            topic: Optional short heading shown next to the timestamp.
            date: Optional YYYY-MM-DD; defaults to today (local time).
        """
        day = date or _today()
        path = _journal_path(day)
        os.makedirs(KNOWLEDGE_LOGS_DIR, exist_ok=True)
        created = not os.path.exists(path)
        heading = "## " + datetime.now().strftime("%H:%M") + (f" — {topic}" if topic else "")
        block = (f"# {day}\n" if created else "") + f"\n{heading}\n{text.strip()}\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
        return {
            "ok": True, "date": day, "heading": heading,
        }

    @mcp.tool()
    def journal_read(date: str | None = None) -> dict:
        """Read a day's journal file (default today). Returns its markdown text."""
        day = date or _today()
        path = _journal_path(day)
        if not os.path.exists(path):
            return {"exists": False, "date": day, "content": ""}
        # errors="replace": tolerate legacy/mixed-encoding entries (e.g. cp1252 dashes)
        with open(path, encoding="utf-8", errors="replace") as f:
            return {"exists": True, "date": day, "content": f.read()}

    @mcp.tool()
    def journal_list() -> list[dict]:
        """List existing journal entries by date, newest first."""
        if not os.path.isdir(KNOWLEDGE_LOGS_DIR):
            return []
        files = sorted(
            (f for f in os.listdir(KNOWLEDGE_LOGS_DIR) if f.endswith(".md")),
            reverse=True,
        )
        return [{"date": f[:-3], "file": os.path.join(KNOWLEDGE_LOGS_DIR, f)} for f in files]

    @mcp.tool()
    def journal_search(query: str, limit: int = 50) -> list[dict]:
        """Search all journal files for a term (case-insensitive).

        Returns matching lines with their date and line number, newest files first.
        """
        results: list[dict] = []
        if not os.path.isdir(KNOWLEDGE_LOGS_DIR) or not query.strip():
            return results
        q = query.lower()
        for fn in sorted(
            (f for f in os.listdir(KNOWLEDGE_LOGS_DIR) if f.endswith(".md")),
            reverse=True,
        ):
            try:
                with open(os.path.join(KNOWLEDGE_LOGS_DIR, fn), encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if q in line.lower():
                            results.append({"date": fn[:-3], "line": i, "text": line.rstrip()})
                            if len(results) >= limit:
                                return results
            except OSError:
                continue
        return results

    # ── Evergreen reference notes ────────────────────────────────────────────
    def _note_path(name: str) -> str:
        slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
        if not slug:
            raise ValueError("note name required")
        return os.path.join(KNOWLEDGE_NOTES_DIR, f"{slug}.md")

    def _title_from_name(name: str) -> str:
        slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
        return slug.replace("-", " ").title() or "Note"

    def _parse_note_meta(text: str) -> tuple[str | None, str | None, list[str]]:
        title = description = None
        headings: list[str] = []
        for line in text.splitlines():
            s = line.strip()
            if title is None and s.startswith("# "):
                title = s[2:].strip()
            elif description is None and s.startswith("> "):
                description = s[2:].strip()
            elif s.startswith("## "):
                headings.append(s[3:].strip())
        return title, description, headings

    def _set_description(text: str, name: str, description: str) -> str:
        lines = text.splitlines()
        t_idx = next((i for i, l in enumerate(lines) if l.strip().startswith("# ")), None)
        if t_idx is None:
            lines.insert(0, f"# {_title_from_name(name)}")
            t_idx = 0
        j = t_idx + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j < len(lines) and lines[j].strip().startswith(">"):
            del lines[j]
        lines.insert(t_idx + 1, f"> {description.strip()}")
        return "\n".join(lines) + "\n"

    @mcp.tool()
    def knowledge_index() -> dict:
        """The Knowledge 'start here' navigator — call this first.

        Returns every evergreen reference note with its title, one-line description,
        and section headings (so you can pick the right note without reading them all),
        plus the most recent daily-journal dates. Use it to route a request quickly:
        scan descriptions/headings, then note_read(...) the relevant one (or journal_read).
        """
        notes = []
        if os.path.isdir(KNOWLEDGE_NOTES_DIR):
            for fn in sorted(f for f in os.listdir(KNOWLEDGE_NOTES_DIR) if f.endswith(".md")):
                path = os.path.join(KNOWLEDGE_NOTES_DIR, fn)
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                title, description, headings = _parse_note_meta(text)
                st = os.stat(path)
                notes.append({
                    "name": fn[:-3],
                    "title": title or fn[:-3],
                    "description": description or "",
                    "headings": headings,
                    "updated": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "bytes": st.st_size,
                })
        recent_journal = []
        if os.path.isdir(KNOWLEDGE_LOGS_DIR):
            recent_journal = sorted(
                (f[:-3] for f in os.listdir(KNOWLEDGE_LOGS_DIR) if f.endswith(".md")),
                reverse=True,
            )[:7]
        return {"notes": notes, "recent_journal": recent_journal}

    @mcp.tool()
    def note_read(name: str) -> dict:
        """Read a reference note's full markdown by name (e.g. 'carriers')."""
        path = _note_path(name)
        if not os.path.exists(path):
            return {"exists": False, "name": name, "content": ""}
        with open(path, encoding="utf-8", errors="replace") as f:
            return {"exists": True, "name": os.path.basename(path)[:-3], "content": f.read()}

    @mcp.tool()
    def note_append(name: str, text: str, heading: str | None = None) -> dict:
        """Append content to a reference note, creating it if it doesn't exist.

        Args:
            name: Note name/slug, e.g. 'carriers'. A new note is seeded with '# Title'.
            text: Markdown to append.
            heading: Optional '## heading' inserted before the text.
        """
        path = _note_path(name)
        os.makedirs(KNOWLEDGE_NOTES_DIR, exist_ok=True)
        created = not os.path.exists(path)
        parts: list[str] = []
        if created:
            parts.append(f"# {_title_from_name(name)}")
        if heading:
            parts.append(f"## {heading.strip()}")
        parts.append(text.strip())
        chunk = "\n\n".join(parts)
        with open(path, "a", encoding="utf-8") as f:
            f.write(("" if created else "\n") + chunk + "\n")
        return {"ok": True, "name": os.path.basename(path)[:-3]}

    @mcp.tool()
    def note_write(name: str, content: str, description: str | None = None) -> dict:
        """Replace a reference note's entire content (use to restructure / clean up).

        If description is provided, a '> description' line is ensured under the title.
        """
        path = _note_path(name)
        os.makedirs(KNOWLEDGE_NOTES_DIR, exist_ok=True)
        body = _set_description(content, name, description) if description else content
        if not body.endswith("\n"):
            body += "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return {"ok": True, "name": os.path.basename(path)[:-3]}

    @mcp.tool()
    def note_describe(name: str, description: str) -> dict:
        """Set/update only the one-line '> description' of a note (powers knowledge_index)."""
        path = _note_path(name)
        os.makedirs(KNOWLEDGE_NOTES_DIR, exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {_title_from_name(name)}\n> {description.strip()}\n")
            return {"ok": True, "name": os.path.basename(path)[:-3]}
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(_set_description(text, name, description))
        return {"ok": True, "name": os.path.basename(path)[:-3]}

    @mcp.tool()
    def note_search(query: str, limit: int = 50) -> list[dict]:
        """Search all reference notes for a term (case-insensitive). Returns {name, line, text}."""
        results: list[dict] = []
        if not os.path.isdir(KNOWLEDGE_NOTES_DIR) or not query.strip():
            return results
        q = query.lower()
        for fn in sorted(f for f in os.listdir(KNOWLEDGE_NOTES_DIR) if f.endswith(".md")):
            try:
                with open(os.path.join(KNOWLEDGE_NOTES_DIR, fn), encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if q in line.lower():
                            results.append({"name": fn[:-3], "line": i, "text": line.rstrip()})
                            if len(results) >= limit:
                                return results
            except OSError:
                continue
        return results


if __name__ == "__main__":
    mcp.run()
