Assessment: comment — The file is an excerpt, so I can't confirm the problem statement or the callers. The prefix matching and the enabled check both look doubtful.

1. [attention · 4] **`.agent/tools/maintenance/doctor_mcp.py:15`** — prefix match credits a server to the wrong plugin when plugin names share a prefix
```
served = {name for name in names if name.startswith(f"plugin_{plugin_id.split('@')[0]}_")}
```
Plugin `foo` matches `plugin_foo_bar_x`, which belongs to plugin `foo_bar` with server `x`. With `foo` installed and `foo_bar` not, doctor reports `plugin_foo_bar_x` as reachable. This is the false "ok" that doctor exists to prevent. The match also credits servers of a plugin that is not installed, and `split('@')[0]` is recomputed for every plugin.
Fix: build the set of installed plugin names first. Assign each configured name to its longest matching installed plugin prefix, and only credit it if that plugin is the one being processed.

2. [needs more info · 3] **`.agent/tools/maintenance/doctor_mcp.py:16`** — a plugin with no `enabledPlugins` entry counts as enabled
```
if enabled.get(plugin_id) is False or not served or not isinstance(installs, list):
```
Only an explicit `false` disables a plugin. A plugin that is installed but absent from `enabledPlugins` is credited. The summary says "installed, enabled plugin". Does Claude Code treat a missing key as enabled? If it does not, doctor reports servers as reachable for plugins that never load.

2. [nit · 3] **`.agent/tools/maintenance/doctor_mcp.py:9`** — `read_object` is neither defined nor imported in this file
```
installed = read_object(directory / "plugins" / "installed_plugins.json").get("plugins")
```
The file says it is an excerpt, and my grep found no `read_object` definition in the working directory. If the helper is not imported where the full module is assembled, this raises `NameError`. I could not confirm that either way.