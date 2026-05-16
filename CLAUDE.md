# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Run / install

- Run the MCP server (preferred, no permanent install): `uvx ableton-mcp`
- Run from source for development: `python -m MCP_Server.server`
- Install in editable mode: `uv pip install -e .` (uses `pyproject.toml`, requires Python ≥ 3.10)
- Entry point: `MCP_Server.server:main` (registered as the `ableton-mcp` script)
- Docker / Smithery: `python -m MCP_Server.server` over stdio (`Dockerfile`, `smithery.yaml`)

There is no test suite. Linting is via Ruff: `ruff check MCP_Server/` (config in `pyproject.toml`, also run in CI by `.github/workflows/lint.yml`). `AbletonMCP_Remote_Script/` is excluded from lint because it must stay Python 2 compatible.

## Architecture

The repo ships **two separately-deployed components** that talk over a TCP socket. Understanding this split is essential — they run in different processes, on different Python interpreters, and have different constraints.

### 1. `MCP_Server/server.py` — the MCP server (host machine)

- A `FastMCP` server (from the `mcp` package) that exposes Ableton operations as MCP tools to Claude Desktop / Cursor over stdio.
- Holds a **single global persistent socket** (`_ableton_connection`) to the Remote Script on `localhost:9877`. `get_ableton_connection()` retries up to 3 times and validates each new connection by sending a `get_session_info` ping. On any socket error, the global is cleared so the next call reconnects.
- Each `@mcp.tool()` is a thin wrapper that calls `AbletonConnection.send_command(command_type, params)` and stringifies the JSON result. **State-modifying commands** are listed explicitly in `send_command`'s `is_modifying_command` set — they get a longer socket timeout (12s vs 8s). The remote script blocks on Ableton's main thread until the op finishes before replying (bounded by a 10s `queue.get` timeout on its side), so the modifying-command socket timeout must stay above that 10s. Keep that list in sync when adding mutating tools.
- Application-level errors from Ableton (`{"status":"error",...}`) are raised as `AbletonError` and pass through `send_command` *without* clearing `self.sock`. Only real I/O failures (timeout, `ConnectionError`, broken framing) tear the connection down. Don't downgrade `AbletonError` to a plain `Exception` — you'll re-introduce the "every Ableton error costs a full reconnect" bug.
- `receive_full_response` reads in chunks until the accumulated bytes parse as valid JSON and returns the parsed dict (no length prefix on the wire — partial-JSON-decode-failure is the framing signal). Both sides set `TCP_NODELAY` to avoid Nagle/delayed-ACK stalls on localhost.

### 2. `AbletonMCP_Remote_Script/__init__.py` — the Ableton MIDI Remote Script (inside Live)

- A `ControlSurface` subclass loaded by Ableton Live as a "Control Surface" (Preferences → Link/Tempo/MIDI → Control Surface dropdown → AbletonMCP). It runs **inside Ableton's embedded Python**, not the host venv.
- On startup it binds a TCP server on `localhost:9877` in a daemon thread and accepts multiple clients, each handled in its own thread.
- **Threading rule (critical):** the Live API is only safe to call from Ableton's main thread. Commands that mutate state (the list in `_process_command`: `create_midi_track`, `set_track_name`, `create_clip`, `add_notes_to_clip`, `set_clip_name`, `set_tempo`, `fire_clip`, `stop_clip`, `start_playback`, `stop_playback`, `load_browser_item`, `delete_track`, `delete_clip`, `batch`, `create_clip_with_notes`, `create_track_with_instrument`) are dispatched to the main thread via `self.schedule_message(0, fn)` and the worker thread blocks on a `queue.Queue` for the result with a 10s timeout. Read-only commands run directly on the worker thread. **Any new mutating command must follow the same pattern** — calling Live API directly from the socket thread will hang or crash Live.
- The file uses `from __future__ import ...` and a `try: import Queue / except ImportError: import queue` shim. Older Ableton versions shipped Python 2; **keep this code Python-2 compatible** unless you confirm the supported Ableton versions have all moved to Python 3.
- Installation is manual: the user copies this file into Ableton's `MIDI Remote Scripts/AbletonMCP/` directory (see README for the per-OS paths). The repo's working copy is **not** what Ableton runs — edits here only take effect after the user re-copies and reloads the Control Surface in Live.

### Wire protocol

JSON over TCP, no framing:
- Request: `{"type": "<command_name>", "params": {...}}`
- Response: `{"status": "success", "result": {...}}` or `{"status": "error", "message": "..."}`
- The client (server.py) detects message boundaries by trying to JSON-decode the accumulated buffer on each chunk — every response must be exactly one JSON object.

### Adding a new tool

To add an end-to-end capability, all three of these must be updated:

1. `MCP_Server/server.py`: add a `@mcp.tool()` function that calls `ableton.send_command("<name>", {...})`.
2. `MCP_Server/server.py`: if it mutates Live state, add `"<name>"` to the `is_modifying_command` list in `AbletonConnection.send_command`.
3. `AbletonMCP_Remote_Script/__init__.py`: if it mutates state, add `"<name>"` to the main-thread dispatch list in `_process_command` AND add a branch in `_dispatch_state_command` that calls your `_handler`. If it's read-only, just add an `elif` branch inline in `_process_command`.

### Batching for write-heavy workloads

Every state-mutating command pays one `_Framework` tick (~0–100ms, avg ~50ms) via `schedule_message`, because the remote script's timer fires every 100ms. To collapse a multi-step build into a single tick, use the `batch` tool (generic — takes a list of sub-commands) or one of the composite tools (`create_clip_with_notes`, `create_track_with_instrument`). All sub-commands run inside one `main_thread_task` on the Remote Script (`_dispatch_state_command` is reused recursively), so N operations cost ~1 tick instead of N. Prefer batching over chaining individual tools when you know up front what you want to build.

### Browser/URI model

Loading instruments, effects, and drum kits goes through Ableton's browser. Tools take either a path (`get_browser_items_at_path("drums/acoustic/kit1")`) or an opaque URI (`load_instrument_or_effect(track_index, "query:Synths#...:FileId_5116")`) returned by browser queries. URIs are not stable across machines/library versions — always discover via `get_browser_tree` / `get_browser_items_at_path` before loading.

## Gotchas

- **FastMCP constructor signature drifts across `mcp` package versions.** Commit `a31dcdb` removed a `description=` kwarg that newer FastMCP doesn't accept. If you bump the `mcp` dependency, re-verify the `FastMCP(...)` call in `server.py:187`.
- **Only run one MCP server instance** (Claude Desktop *or* Cursor, not both) — they'll both try to grab the single socket connection to Ableton.
- The Remote Script's socket server binds with `SO_REUSEADDR`, but if Live crashes mid-session the port may briefly be in `TIME_WAIT` — restart Live (not just toggle the Control Surface) if reconnection won't take.
- `get_ableton_connection` "pings" by sending an empty bytestring (`b''`) — this is a no-op on a live socket but raises on a dead one. Don't replace it with a real command or you'll spam Live with traffic on every tool call.
