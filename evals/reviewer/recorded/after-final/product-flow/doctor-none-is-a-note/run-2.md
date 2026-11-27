Assessment: request-changes — the owner configured MCP servers, but a config dir that reaches none of them now produces a note, so `crew doctor` exits 0 for the worst case.
Read beyond the package: doctor_mcp.py (grep only; the helpers `claude_capability`, `claude_files` and `available` are not in the working directory)

The person here is the owner who runs `crew doctor` after install to learn whether agents will have code search and docs.

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:18`** — a config dir with no reachable server is downgraded from WARN to a note, so doctor exits 0
```
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
The owner has configured servers, and the primary `~/.claude` reaches none of them, for example because the server is registered in a different config dir or scope. Before this change that dir produced one WARN per capability and a non-zero exit. Now it produces a single note and doctor exits 0, so the install looks healthy while agents have no code search or docs. This is the worst case, and it is the one that now passes. The note also doesn't say what to do next, for example register the server or point `CLAUDE_CONFIG_DIR` at the right dir.
Fix: emit `Line("warn", ...)` for this case, keeping the single collapsed line, and add a next step such as "add the server with `claude mcp add`". If the intent is to tolerate secondary dirs that reach nothing, downgrade only when another dir does reach a configured server. The primary dir, which `claude_files` returns first, should always WARN.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:16`** — the new reachability test treats a partial result differently from none
```
if not (user | set().union(*reach.values())) & configured:
```
A dir that reaches only the code-search server still gets per-capability lines, and the docs one WARNs. A dir that reaches nothing gets a quieter note. So the report is less severe the more is broken, and the owner sees a failure for the milder case and a pass for the worse one. Fix: keep severity monotonic. Zero reachable servers should be at least as loud as one missing capability.

3. [nit · 2] **`.agent/tools/maintenance/doctor_mcp.py:18`** — the note doesn't name the capabilities or servers
The old lines listed the capability and the expected server names, for example `code search (name)`. The collapsed note drops them, so the owner can't tell which server to add. Cost: an extra lookup in config to find the names.

Criteria: 0 satisfied, 0 partially satisfied, 1 contradicted, 0 unverified (a WARN makes doctor exit non-zero, and the none-reachable case now yields only a note)