Assessment: request-changes — the owner's main failure case, where a config dir reaches none of the configured servers, now exits 0 because it was downgraded from WARN to a note.
Read beyond the package: none (the grep found only this file, so I couldn't read `claude_capability`, `claude_files` or the other helpers)

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:18` (h1)** — a config dir with no reachable MCP server is reported as a note, so doctor exits 0
```
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
The owner configured code search and docs, then runs `crew doctor` to learn whether agents will have those tools. Suppose the primary `~/.claude` dir reaches neither server, for example because the servers were never registered or the plugin is missing. Before this change that produced a WARN per capability and a non-zero exit. Now it produces one note and exit 0, so scripts and CI see a pass. The owner is told "ok" when every agent lacks the tools. Collapsing the repeated lines is fine, but the severity has to stay.

The change also covers secondary config dirs. A secondary dir that reaches nothing may be benign, but the code does not tell it apart from the primary dir. The primary dir is the first item `claude_files` returns.

Fix: emit `Line("warn", "mcp", ...)` instead of `"note"`. Add the capability labels and a next step to the message, for example "no configured MCP server (code search, docs) is reachable; register one in this dir's settings". If secondary dirs are meant to be softer, make only those notes and keep the primary dir as a WARN.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:18`** — the message doesn't name what is missing or what to do
```
NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"
```
The old WARN named the capability and the server names, for example "code search (a, b)". The new line drops both. The owner can no longer tell which servers were expected, and there is no hint about how to fix it. `MCP_HOWTO` already exists for the no-config case.

Fix: include `', '.join(sorted(configured))` and point to `MCP_HOWTO`.