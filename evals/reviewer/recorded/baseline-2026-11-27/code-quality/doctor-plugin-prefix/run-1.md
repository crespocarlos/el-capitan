Assessment: request-changes — the prefix match can credit one plugin with another plugin's servers, so doctor can report a server as reachable when it isn't, and the change adds no tests.

1. [blocking · 3] **`.agent/tools/maintenance/doctor_mcp.py:15`** — `read_object` is called but not defined or imported
```python
installed = read_object(directory / "plugins" / "installed_plugins.json").get("plugins")
```
A search of the working directory finds no `def read_object` and no import of it. The file is described as an excerpt, so the helper may live in the full module. As submitted, this raises `NameError` on the first call. I couldn't see the full module, so confidence is 3.
Fix: import or define `read_object`, and have it return `{}` when the file is missing or malformed. The `.get` call depends on that.

2. [attention · 4] **`.agent/tools/maintenance/doctor_mcp.py:17`** — the prefix match is ambiguous when plugin names contain underscores
```python
served = {name for name in names if name.startswith(f"plugin_{plugin_id.split('@')[0]}_")}
```
Plugin `foo` produces the prefix `plugin_foo_`. That also matches `plugin_foo_bar_x`, which belongs to plugin `foo_bar` with server `x`. If `foo` is installed and enabled but `foo_bar` is not, doctor credits `foo_bar`'s server as provided. If `foo` is installed and `foo_bar` is disabled, the server is reported reachable anyway. This is the false "reachable" result the feature is meant to prevent.
Fix: build the set of installed plugin names. Exclude a name when a longer installed plugin name matches it with a more specific prefix. Alternatively, compare against the exact `plugin_<plugin>_<server>` names derived from each plugin's own manifest.

3. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:8`** — no tests for the new behavior
The function has several branches: user scope versus project scope, `enabledPlugins` set to false, malformed installs, and the prefix collision from finding 2. None of them has a test. Each branch is a distinct way to get the answer wrong.
Fix: add table-style tests to the existing doctor test file. Cover user scope, project scope, disabled plugin, and a `foo` / `foo_bar` collision.

4. [nit · 3] **`.agent/tools/maintenance/doctor_mcp.py:16`** — the loop does too much in one expression and has an unexplained guard order
`installed.items() if isinstance(installed, dict) else []` and the combined `continue` condition make the control flow hard to follow. The `not isinstance(installs, list)` check sits after the cheaper checks for no reason. Early guards and a short comment would let the next reader see why entries are skipped.
Fix: use `if not isinstance(installed, dict): return set(), {}`, then separate guard clauses inside the loop.