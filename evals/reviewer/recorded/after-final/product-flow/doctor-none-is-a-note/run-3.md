Assessment: request-changes — the worst case (a config dir whose agents get none of the configured MCP tools) now produces a note, so `crew doctor` exits 0 where it used to warn.
Read beyond the package: `doctor_mcp.py` only. It is the one file in the working directory, and the other helpers it calls aren't there.

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:17`** (h1) — A config dir with no reachable MCP server is downgraded from WARN to a note, so doctor exits 0
```
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
The owner configures code search and docs, installs, and runs `crew doctor`. Agents in `~/.claude` have neither server, for example because the config lives in a different dir or the plugin isn't enabled. Before this change that dir got a WARN per capability and a non-zero exit. Now it gets a quiet note and exit 0. A script or CI that gates on doctor reads that as healthy, and the owner finds out only when the agents have no tools. This is the case the check exists to catch. Collapsing the output is fine, but the severity has to stay.
Fix: emit one `Line("warn", "mcp", ...)` instead of the note. Keep the single line per dir, and have the text say what to do, such as "add one of {configured names} to this dir's MCP config".

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:17`** (h1) — The message says nothing about which servers are missing or how to fix it
```
NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"
```
The per-capability WARN named the missing servers (code search, docs, and the names). The collapsed line drops them, and it has no next step. The owner can't tell what to add or where.
Fix: include `', '.join(sorted(configured))` and point to `MCP_HOWTO` in the message.

3. [nit · 2] **`.agent/tools/maintenance/doctor_mcp.py:17`** (h1) — A secondary config dir is judged the same way as the primary
`claude_files` returns the primary dir first, then any other dir that install covers. A secondary dir with no servers now gets only a note. That may be intended if the owner doesn't use it. But it also hides the case where the secondary dir really is the one in use.
Fix: keep the WARN for every dir install covers. If secondary dirs should be softer, make that a deliberate, documented rule.

Criteria: 0 satisfied, 1 partially satisfied, 1 contradicted, 0 unverified. The criteria are inferred from the change description, since no spec was provided. "Doctor reports whether agents will have the tools" is contradicted for the none-reachable case. "A WARN makes doctor exit non-zero" is only partly met, because the case that most needs it no longer produces a WARN.