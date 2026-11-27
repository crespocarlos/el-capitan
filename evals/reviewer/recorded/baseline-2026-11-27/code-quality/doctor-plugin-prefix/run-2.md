Assessment: request-changes — the `plugin_<plugin>_` prefix match can credit one plugin with a sibling plugin's servers, so doctor can still misreport reachability. The change also adds no tests.

1. [attention · 4] **`.agent/tools/maintenance/doctor_mcp.py:16`** — prefix match credits servers to the wrong plugin
```python
served = {name for name in names if name.startswith(f"plugin_{plugin_id.split('@')[0]}_")}
```
Plugin `foo` and plugin `foo_bar` collide. The name `plugin_foo_bar_search` starts with `plugin_foo_`, so an installed, enabled `foo` is credited with `foo_bar`'s server. If `foo_bar` is disabled or uninstalled, doctor reports its server reachable when it is not. The same happens when two marketplaces ship the same plugin name (`foo@a` and `foo@b`), because the `@` suffix is dropped. The `enabled.get(plugin_id) is False` check then applies per id, so one enabled copy can credit servers that the disabled copy's id was meant to exclude.
Fix: resolve ownership across all installed plugins. Give each server name to the plugin with the longest matching prefix, or read each plugin's manifest for its real server names. Cover the collision case in a test.

2. [attention · 3] **`.agent/tools/maintenance/doctor_mcp.py:7`** — no tests for new matching and scoping logic
```python
def plugin_servers(directory: Path, settings: dict, names: set[str]) -> ...
```
The function has several branches and the diff adds no test for any of them: user scope versus project scope, `enabledPlugins` false versus absent, a malformed `installed_plugins.json`, the prefix collision above, and `realpath` normalization of the project path. A regression in any of these would silently misreport doctor output.
Fix: add a table-driven test for `plugin_servers` in the existing doctor test module. It should cover disabled, user-scope, project-scope, malformed-input and prefix-collision cases.

3. [nit · 2] **`.agent/tools/maintenance/doctor_mcp.py:17`** — `served` is computed before the skip checks
```python
if enabled.get(plugin_id) is False or not served or not isinstance(installs, list):
```
The set comprehension runs for every plugin, including disabled ones and ones with malformed `installs`. Checking `enabled` and `installs` first would avoid that work. The cost is small and the code is harder to read than it needs to be.
Fix: check `enabled.get(plugin_id) is False` and `isinstance(installs, list)` first, then compute `served`.