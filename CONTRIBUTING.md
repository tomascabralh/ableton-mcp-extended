# Contributing

This repo has an unusual two-process architecture, which makes the dev loop different from a typical Python package. Read this once before your first change.

## The two components

1. **`MCP_Server/`** — the MCP server. Runs on your host machine in a normal Python environment.
2. **`AbletonMCP_Remote_Script/__init__.py`** — a MIDI Remote Script. Runs **inside Ableton Live's embedded Python interpreter**.

They communicate over a TCP socket on `localhost:9877`.

## Editing `MCP_Server/`

```bash
uv pip install -e .
python -m MCP_Server.server
```

Or run without installing: `uvx ableton-mcp`.

Lint before pushing: `uvx ruff check MCP_Server/` (CI runs the same check).

## Editing `AbletonMCP_Remote_Script/__init__.py`

**Edits to this file have no effect until you manually copy it into Ableton's MIDI Remote Scripts directory AND reload the Control Surface.** This is the single biggest "why isn't my change taking effect?" trap.

1. Copy `AbletonMCP_Remote_Script/__init__.py` into Ableton's MIDI Remote Scripts folder, under a folder named `AbletonMCP/` (see the README's *Installing the Ableton Remote Script* section for per-OS paths).
2. In Ableton: Preferences → Link/Tempo/MIDI → set Control Surface to *None*, then back to *AbletonMCP*. Toggling forces a reload.
3. Re-test. Live's log file (and `show_message` toasts) are your debugging surface.

Constraints for this file:

- **Must stay Python 2 compatible** — no f-strings, no walrus operator, no type annotations. Older Ableton versions ship Python 2. The file already uses `from __future__ import ...` and a `Queue`/`queue` import shim; keep that pattern.
- **Any new state-mutating command must run on Ableton's main thread.** Dispatch it via `self.schedule_message(0, fn)` and return the result through a `queue.Queue`, the way the existing mutating commands in `_process_command` do. Calling the Live API directly from the socket thread will hang or crash Live.

## Adding a new tool

An end-to-end tool requires changes in three places — see `CLAUDE.md` for the exact list (a `@mcp.tool()` in `server.py`, the `is_modifying_command` list if it mutates state, and routing in `_process_command` in the Remote Script).

## Commit style

Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`. Subject line ≤ 72 chars, imperative mood, no trailing period.
