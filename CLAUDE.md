# My Desk — Claude Instructions

## Project structure
```
C:/Christian/
├── c.py                  Entry point — run this to start My Desk on :5002
├── mcp/                  Workspace MCP — config + server
│   ├── .mcp.json         Claude Code MCP config (canonical location)
│   └── server.py
├── context.md            Living design doc — read this for full context
├── CLAUDE.md             This file
├── c App/                Auth, hub, DB (users/permissions), shared services
├── Focus Board/     Blueprint at /focus — tasks, timer, pipeline
├── Financial Management App/  Blueprint at /financial — payment match
├── Knowledge App/        Blueprint at /knowledge — not built yet
│   └── logs/             ← Claude session logs live here as dated .md files
└── Payroll App/          Standalone app on :5001 (launch-on-click from hub)
```

## Logging rule (important)
After any Claude chat or Cowork session that produces decisions, discoveries,
or notes worth keeping — write a brief log entry to:
  `C:/Christian/Knowledge App/logs/YYYY-MM-DD.md`

Append to the file if it already exists for today. Format:
```
## HH:MM — [topic]
[notes]
```

## Scope guidance
- Working on Focus Board? Stay in `C:/Christian/Focus Board/`
  and `C:/Christian/c.py` + `C:/Christian/c App/web/hub.py` only.
- Working on c.app core (auth, hub)? Stay in `C:/Christian/c App/`.
- Do NOT modify `C:/Christian/Reconciliation App/` — reference copy only.
- Do NOT modify `C:/Christian/Payroll App/` unless specifically asked.
- MCP server work? Stay in `C:/Christian/mcp/`. Config is `mcp/.mcp.json` only (no root copy).
  Claude Code reads project-scope MCP from the repo root — register once with:
  `claude mcp add-json my-desk --scope project - < mcp/.mcp.json` (or paste the JSON via `/mcp`).

## Standing rule
Every automation must be mirrored in Process Street with a to-do step AND
an audit step. No black-box automations.

## Active work
See `context.md` for full roadmap and current decisions.
See `Focus Board/context.md` for Focus Board design details.
