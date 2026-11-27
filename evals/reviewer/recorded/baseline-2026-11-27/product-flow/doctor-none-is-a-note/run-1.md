Assessment: request-changes — a config dir with no reachable MCP server, the worst case, now produces only a note and exit 0, so `crew doctor` reports success when agents have no tools.

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:15`** — a config dir with no reachable server no longer fails `crew doctor`
```python
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
This is the worst outcome for the owner: agents run from that dir have neither code search nor docs. Before the change it produced a WARN per capability and a non-zero exit. Now it produces a note and `crew doctor` exits zero. This matters most for the primary dir (`~/.claude` or `CLAUDE_CONFIG_DIR`). If the owner has configured servers and none reach the primary dir, a green run hides the exact problem the command exists to catch. Collapsing several WARNs into one line is reasonable, but the collapsed line should still be a WARN.
Fix: emit `Line("warn", "mcp", ...)` for the collapsed case. If secondary dirs should stay quiet, downgrade to a note only for non-primary dirs, since `claude_files` returns the primary one first.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:1`** — the collapsed message names neither the missing servers nor a next step
```python
NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"
```
The per-capability lines used to say which capability and which server names (`code search (a, b)`) were missing. The new line drops that, so the owner can't tell what to add or where. Other cases that use `MCP_HOWTO` give a pointer, and this one doesn't.
Fix: append the configured server names, for example `sorted(configured)`, and a short hint such as "install them for this dir or see MCP_HOWTO".