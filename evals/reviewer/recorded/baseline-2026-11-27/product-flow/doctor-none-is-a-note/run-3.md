Assessment: request-changes — the change turns the worst case, a config dir with no reachable MCP server, from a WARN into a note, so `crew doctor` exits 0 when agents have no tools.

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:17`** (hunk 1) — A config dir with zero reachable servers no longer fails the check
```python
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
The owner runs `crew doctor` to learn whether agents will have code search and docs. Before this change, each missing capability produced a WARN and a non-zero exit. Now the total-absence case, which is the one that most needs attention, produces only a note and exit 0. A broken primary `~/.claude` install, or a typo in a server name, looks healthy to any script or CI step that checks the exit code. Partial coverage still warns, so the check is stricter for a dir with one server than for a dir with none. The consolidation is reasonable, but it should not lower the severity.
Fix: emit a single `Line("warn", ...)` instead of `"note"`, so the exit stays non-zero and the output stays collapsed to one line per dir.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:1`** (hunk 1) — The collapsed message doesn't say what is missing or how to fix it
```python
NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"
```
The per-capability lines named the missing servers, for example "code search (a, b)". The collapsed line drops those names and doesn't mention `MCP_HOWTO`. The owner learns that nothing works in this dir but not which servers were expected, so they can't tell a typo from a missing plugin.
Fix: include the sorted `configured` names and a pointer to the how-to, for example `"... none of: {names} is reachable; see crew mcp setup"`.