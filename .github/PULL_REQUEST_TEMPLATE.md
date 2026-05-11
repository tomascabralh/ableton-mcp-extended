## Summary
<!-- 1-3 bullets describing what changed -->

## Why
<!-- Motivation, linked issue, or context. One or two sentences. -->

## Test plan
<!-- Concrete steps a reviewer can run to validate -->
- [ ]
- [ ]

## Checklist
- [ ] Commits follow Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`)
- [ ] **If `AbletonMCP_Remote_Script/__init__.py` changed:** I tested by copying it into Ableton's `MIDI Remote Scripts/AbletonMCP/` folder and reloading the Control Surface in Live. *(Edits to that file have no effect on a running session until it is manually recopied — see `CONTRIBUTING.md`.)*
- [ ] **If `AbletonMCP_Remote_Script/__init__.py` changed:** the change is Python 2 compatible (no f-strings, walrus, or type annotations) and any new state-mutating command is dispatched via `schedule_message`
- [ ] **If `MCP_Server/` changed:** `python -m MCP_Server.server` (or `uvx ableton-mcp`) starts without errors, and `ruff check MCP_Server/` is clean
- [ ] No new runtime dependencies beyond what's declared in `pyproject.toml`
