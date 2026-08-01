# CLAUDE.md — operating manual for Christian's productivity sessions

*Read this first. It holds the durable "how to work" procedure; it rarely changes. The day-to-day state lives elsewhere (see Read order).*

## Read order (catch up first)
1. **This file (`CLAUDE.md`)** — how to work in this folder.
2. **`Productivity system - notes & thoughts.md`** — the **source of truth** for current state/content. Read its "▶ Start here" block.
3. **Operating canvas** — sidebar artifact `operating-canvas`, mirrored to `My operating canvas.html`.

Full day-by-day history is archived in `Productivity system - history.md`.

## The files
- **`CLAUDE.md`** (this) — durable procedure / rules. Rarely changes.
- **`Productivity system - notes & thoughts.md`** — active running log + current state. **Source of truth.**
- **`Productivity system - history.md`** — archive of older daily logs.
- **`My operating canvas.html`** — portable copy of the canvas; the **sidebar artifact is the live daily driver**.

## File-editing protocol (CRITICAL)
- **EDIT VIA BASH PYTHON ONLY.** The Edit/Write tools silently truncate a file when the new content differs in byte count (known Cowork bug — the canvas blanked twice this way). The Read tool reads a stale in-memory buffer, so it won't surface the truncation.
- Pattern: `python3` read → replace → write. **Then verify on disk** with `wc -c` + `tail`.
- Applies to every `.md` file here and to `My operating canvas.html`.

## Canvas sync
- Canvas data lives in the browser under localStorage key `operating_canvas_vN`.
- To push a fresh state: edit the SEED in the HTML, **bump the key `vN → vN+1`**, save the folder file, then call `update_artifact` (id `operating-canvas`).
- Keep the folder copy and the sidebar artifact **identical**.
- Keep the HTML **under ~19.5KB** or it truncates.
- Colour palette: **true azure blues**, no purple/indigo cast.

## Notes-file rules
- It is the **source of truth** — work done in *other* chats must be written back into it, or it's lost to this system.
- **Stay lean:** if it nears ~19.5KB, archive older daily logs into `Productivity system - history.md` (don't wait for the weekly review if size forces it).
- At each **weekly review**, move completed daily logs out of the notes file into the archive.

## Standing rules
- **Every automation we build must be mirrored in Process Street** as (1) a to-do step and (2) an audit step. Automation without a documented process + audit = a black box (how the ERL since-inception error stayed hidden).
- **Working style:** concise and direct; earlier mornings; one trusted place over scattered systems.

## Working principles
- **Resolve completely, and quickly.** Find the minimal change that *fully* fixes an issue, make it, verify, then stop. Christian is diligent, precise, and honest — which sometimes surfaces adjacent problems and turns one fix into a can of worms that drags on. Don't silently expand scope.
- **Park tangents, don't chase them.** Problems found along the way get captured as a separate task/note, not solved inline — surface them so nothing is lost, but keep the current fix tight and shippable.
- **Don't let issues drag.** Prefer a decisive, verified resolution now over an open-ended investigation; if deeper work is genuinely needed, scope it as its own item rather than blocking on it.
- **Expect blame-shifting in this industry.** People often push responsibility onto others and wash their hands. Don't get pulled in — keep clean, precise records (journal + Process Street audit steps) so the paper trail speaks for itself.
