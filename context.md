# c.app — Context & Planning

## Overview
`c.app` is Christian's personal, custom workspace — a unified hub that ties together
several domain-specific apps and tools under one roof.

**Entry point:** `C:/Christian/c.py`
**Supporting files:** `C:/Christian/c App/`

---

## Areas

### 1. Payroll App
- Existing standalone Flask app at `C:/Christian/Payroll App/`, runs on port 5001.
- **Decision pending:** Whether Payroll stays as a separate process (linked from c.app)
  or gets absorbed into c.app so there is only one server to run.
  - *Argument for keeping separate:* Payroll App is already mature, has its own git
    history, and decoupling means a payroll bug can't crash the whole workspace.
  - *Argument for embedding:* Single server, single URL, unified nav — no need to
    manage two processes.

### 2. Focus Board
- To be designed. Discussion in progress.
- Folder: `C:/Christian/` (no dedicated subfolder yet — will live under c App/).

### 3. Financial Management App
- Folder exists at `C:/Christian/Financial Management App/` but is currently empty.
- Scope and features to be defined.

### 4. Reconciliation App
- Lives in its own subfolder (reference copy only — dead folder, not to be modified).
- **Not connected to c.app at this time.**

---

## Tech Stack
- Python / Flask (consistent with Payroll App and Reconciliation App)
- Effortless Admin design system: Roboto, sky-blue (`#1a99d6`), EA CSS variables, FontAwesome icons
- SQLite database at `C:/Christian/c App/c.db`
- Password hashing: PBKDF2-HMAC-SHA256 via stdlib `hashlib` (no third-party deps) — mirrored from Reconciliation App

---

## Authentication & Permissions

### Mirrored from Reconciliation App
The login flow, password hashing, and session management are taken directly from
`Reconciliation App/App v3/`:
- `services/auth.py` — session helpers (`session_username`, `is_authenticated`, decorators)
- `scripts/users.py` — user CRUD, `authenticate()`, `hash_password()`, `verify_password()`
- `web/auth.py` — `/login` and `/logout` routes
- `templates/login.html` — login form (select name + password field)

### What's different in c.app
The Reconciliation App uses a single `role` column on the `users` table ("user", "manager", "admin").
c.app replaces that with a proper permissions system — three tables:

```sql
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT,
    password_hash TEXT,           -- NULL = no password required
    is_active     INTEGER DEFAULT 1,
    created_on    TEXT            -- ISO-8601 UTC
);

CREATE TABLE permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,  -- e.g. 'payroll', 'focus', 'financial', 'admin'
    description TEXT
);

CREATE TABLE user_permissions (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    permission_id INTEGER NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (user_id, permission_id)
);
```

**Permission names drive visibility:** a hub card is shown only if the logged-in user
holds the matching permission. The `admin` permission unlocks user management within c.app.

### Seed permissions (created on first run)
| name           | description                          |
|----------------|--------------------------------------|
| `payroll`      | Access the Payroll App               |
| `focus` | Access the Focus Board         |
| `financial`    | Access the Financial Management area |
| `admin`        | Manage users and permissions         |

---

## Open Decisions

| # | Decision | Status |
|---|----------|--------|
| 1 | Payroll: launch-on-click from hub, spawns subprocess on :5001 | **Decided** |
| 2 | Focus Board app — scope and feature set | **Discussing** |
| 3 | Financial Management app — scope and feature set | **Not started** |
| 4 | Port for c.app | **Decided: 5002** (5000 used by Reconciliation App; override via `C_APP_PORT`) |
| 5 | Single git repo vs per-app repos | Not discussed |

---

## Discussion Log

**2026-06-26** — Initial scoping session.
- `c.py` to live at base of `C:/Christian/`, all c.app assets under `C:/Christian/c App/`.
- Reconciliation App is reference-only; do not connect.
- Three active areas: Payroll, Focus Board, Financial Management.
- Decided to document everything in this file before writing any code.
- **Launcher pattern confirmed:** `c.py` starts c.app on port 5002 (configurable via `C_APP_PORT`).
- **Payroll card — launch-on-click:** clicking the Payroll card sends a request to c.app,
  which spawns the Payroll App as a background subprocess on port 5001 (if not already running),
  then redirects the browser to `http://localhost:5001`. Subsequent clicks detect it's already
  running and redirect immediately.
- **First user:** Christian Ulrich, username `culrich`, no password (empty = no hash required).
- **Auth pattern confirmed:** mirror login/session/password logic from Reconciliation App,
  replace single `role` column with `permissions` + `user_permissions` tables so app
  visibility is permission-driven, not role-driven.

---

## Design Changes

**2026-06-26 — Page width widened (860px → 1600px).**
- *What:* Raised the `.container` `max-width` from 860px to 1600px in the shared
  My Desk stylesheet. Horizontal padding (`0 24px`) and centering (`margin: … auto`)
  unchanged. The login card keeps its own 420px width (centered).
- *Why:* The content column was too narrow and did not use the available screen width.
- *Scope:* Global across all My Desk apps that use the shared shell — hub, login, and the
  `/focus` blueprint. The standalone Payroll App was widened to match
  (base `.container` and the `body.calc-page` override both raised to 1600px).
  The Reconciliation App is untouched (reference-only).
- *Files touched:* `c App/static/style.css` (line ~116), `Payroll App/static/style.css`
  (lines ~135 and ~506).
