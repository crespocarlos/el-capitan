#!/usr/bin/env bash
# Temporary harness probe (docs/probe.md), inert unless EL_CAPITAN_PROBE=1 is set in the harness
# environment. Usage from a registration: probe.sh <claude|cursor> <event>. When on, it appends one
# JSON line per event to ~/.agent/state/probe.log holding NAMES only, never a value: the top-level and
# `tool_input` field names, the `tool_name` value (a name), the CLAUDE_*/CURSOR_* variable names, and
# for a subagent event which fields hold a `.jsonl` path or a string over 200 characters. An observer:
# it always exits 0, prints nothing, or `{}` on the Cursor events that expect a decision.
set +e
exec 2>/dev/null
HARNESS=${1:-unknown}
EVENT=${2:-}
case "$HARNESS:$EVENT" in
  cursor:preToolUse | cursor:beforeShellExecution | cursor:subagentStart) ANSWER='{}' ;;
  *) ANSWER= ;;
esac
finish() {
  [ -n "$ANSWER" ] && printf '%s\n' "$ANSWER"
  exit 0
}
if [ "${EL_CAPITAN_PROBE:-}" != 1 ]; then
  cat >/dev/null
  finish
fi
command -v python3 >/dev/null || { cat >/dev/null; finish; }
LOG=$HOME/.agent/state/probe.log
mkdir -p -m 700 "$HOME/.agent/state"
PROBE_ENV_NAMES=$(compgen -e | grep -E '^(CLAUDE|CURSOR)_' | sort) \
  PROBE_HARNESS=$HARNESS PROBE_EVENT=$EVENT PROBE_LOG=$LOG python3 -I -c '
import datetime, json, os, re, sys

def name(text):
    return re.sub(r"[^A-Za-z0-9_.:-]", "?", str(text))[:80]

raw = sys.stdin.read()
try:
    event = json.loads(raw) if raw.strip() else {}
except ValueError:
    event = None
record = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
          "harness": name(os.environ["PROBE_HARNESS"]),
          "env": [name(n) for n in os.environ.get("PROBE_ENV_NAMES", "").split() if n]}
if not isinstance(event, dict):
    record.update(event=name(os.environ["PROBE_EVENT"]), unreadable=True)
else:
    record["event"] = name(os.environ["PROBE_EVENT"] or event.get("hook_event_name") or "")
    record["fields"] = sorted(name(k) for k in event)
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        record["tool_input_fields"] = sorted(name(k) for k in tool_input)
    if isinstance(event.get("tool_name"), str):
        record["tool_name"] = name(event["tool_name"])
    edits = event.get("edits", tool_input.get("edits") if isinstance(tool_input, dict) else None)
    if isinstance(edits, list):
        record["edits_fields"] = sorted({name(k) for item in edits if isinstance(item, dict) for k in item})
    if record["event"].lower() in ("subagentstart", "subagentstop"):
        jsonl, long = set(), set()

        def walk(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, path + [name(key)])
            elif isinstance(value, list):
                for item in value:
                    walk(item, path + ["[]"])
            elif isinstance(value, str):
                where = ".".join(path)
                if value.endswith(".jsonl"):
                    jsonl.add(where)
                if len(value) > 200:
                    long.add(where)

        walk(event, [])
        record.update(has_jsonl=bool(jsonl), jsonl_fields=sorted(jsonl), has_long=bool(long), long_fields=sorted(long))
old = os.umask(0o077)
with open(os.environ["PROBE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(record, sort_keys=True) + "\n")
os.umask(old)
'
finish
