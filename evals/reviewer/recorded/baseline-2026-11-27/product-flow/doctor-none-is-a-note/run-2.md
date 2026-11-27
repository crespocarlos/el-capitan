Assessment: request-changes — the change turns the worst case (an agent with no configured MCP server) from a failing WARN into a passing note, which defeats the purpose of `crew doctor`.

1. [blocking · 4] **`.agent/tools/maintenance/doctor_mcp.py:17`** (no hunk index in package) — a config dir with no reachable MCP server no longer fails `crew doctor`
```python
if not (user | set().union(*reach.values())) & configured:
    lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
    continue
```
Before this change, a dir that reached nothing produced a WARN per capability, so `crew doctor` exited non-zero. Now it produces one `note`, and notes don't affect the exit code. The owner runs doctor to learn whether agents will have code search and docs. If the primary dir (`~/.claude` or `CLAUDE_CONFIG_DIR`) reaches none of the servers, that is a total failure. Doctor will now report it as informational and exit 0. Scripts and CI that gate on the exit code will pass with agents that have no tools. Collapsing three lines into one reads better, but it should not lower the severity. This is a regression introduced by the diff.
Fix: keep the single consolidated line, but emit it as `Line("warn", ...)` so the exit code stays non-zero. If a secondary dir is truly optional, downgrade only that case and keep the primary dir (the first one from `claude_files`) as a WARN.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:1`** — the consolidated message names no missing servers and gives no next step
```python
NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"
```
The per-capability lines used to say what was missing, for example "code search (name)". The new line drops the server names and gives no way to recover. The owner can't tell which servers to add to this dir, or whether the dir is the problem at all rather than a wrong server name. `MCP_HOWTO` already exists for this.
Fix: list the configured server names in the message, for example `", ".join(sorted(configured))`, and point to the how-to or the config file to edit.