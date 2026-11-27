Assessment: request-changes — a config dir where the owner's configured MCP servers are all missing now produces a note, so `crew doctor` exits 0 even though agents have none of the tools.

Read beyond the package: doctor_mcp.py (grep only)

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:17-19`** — A dir with no configured server is downgraded from WARN to a non-failing note
```
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
The owner configured code search and docs, then ran install. The primary `~/.claude` has neither server, whether from a typo, a failed install or a missing plugin. Doctor now prints a note and exits 0. Before this change, each capability produced a WARN and a non-zero exit. This is the worst case, and it now reads as fine. A script or CI that gates on the exit code passes. An owner who skims the output sees only a note, so they believe agents have the tools when they have none.
Fix: emit a WARN when the dir reaches none of the configured servers. Keep the single consolidated line to avoid per-capability noise, for example `Line("warn", "mcp", NONE_IN_DIR.format(...) + "; run <install/fix command>")`. Reserve a note for secondary dirs that install does not target, if the spec says so.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:1`** — The message says what is wrong but not what to do next
```
NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"
```
It does not name the servers that were expected, which the per-capability lines did through `(', '.join(sorted(names)))`. It also does not point to `MCP_HOWTO` or a fix. Consolidating the lines removed the information the owner needs to recover.
Fix: include the sorted configured names and a next step in the message.