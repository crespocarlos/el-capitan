"""The Cursor app: one local plugin at ~/.cursor/plugins/local/el-capitan carrying the rules, the agents and
`hooks/hooks.json` (local plugins load in the editor, the CLI and self-hosted workers). Payloads carry the shell
command at the top level and `conversation_id`; every answer is one JSON object, `{}` at least (a `failClosed`
registration reads silence as a crash): `permission: deny`, `additional_context`, `followup_message`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from crew.harness import adapters

ID = "cursor"
PLUGIN = adapters.manifest(ID)["plugin"]
STOPPED = ("error", "aborted")
# A tool's fields Cursor may send at the top level instead of under `tool_input` (the Delete path key is undocumented).
FIELDS = ("command", "file_path", "path", "target_file", "content", "old_string", "new_string", "replace_all", "edits")
USAGE = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_tokens", "cache_write": "cache_write_tokens"}
STATS = {"duration_ms": "duration_ms", "tool_calls": "tool_call_count", "messages": "message_count"}
FOLLOWS_UP = ("stop", "subagentStop")


def tool_of(native: str, payload: dict) -> str:
    return "Shell" if native.endswith("ShellExecution") else adapters.text(payload.get("tool_name"))


def subagent_fields(payload: dict) -> dict:
    """A stopped subagent: who it was, its dispatch prompt (`task`), whether it ended, and where its transcript is."""
    live = os.environ.get("CURSOR_TRANSCRIPT_PATH")
    own = payload.get("agent_transcript_path")
    ids = [adapters.text(payload.get(key)) for key in ("subagent_id", "child_conversation_id") if payload.get(key)]
    conversations = [payload.get("parent_conversation_id"), payload.get("conversation_id"), Path(live).stem if live else None]
    places = adapters.transcript_places(own, [payload.get("transcript_path"), live, own], ids, conversations, Path.home() / ".cursor" / "projects")
    status, loop = adapters.text(payload.get("status")), adapters.count(payload.get("loop_count"))
    return {
        "keys": sorted(payload),
        "agent_id": adapters.text(payload.get("subagent_id")),
        "agent_type": adapters.text(payload.get("subagent_type")),
        "prompt": adapters.text(payload.get("task")),
        "summary": adapters.text(payload.get("summary")) if status == "completed" else "",
        "status": status,
        "stopped": status in STOPPED,
        "resumable": status == "completed" and loop == 0,
        "loop": loop,
        "model": adapters.text(payload.get("subagent_model")),
        "stats": {key: adapters.count(payload.get(field)) for key, field in STATS.items()},
        "transcripts": places[0],
        "transcript_dirs": places[1],
    }


def stop_fields(payload: dict) -> dict:
    """A turn's end: its generation, model and loop, the workspace, and its token counts when all four are there."""
    counts = {key: payload.get(field) for key, field in USAGE.items()}
    roots = payload.get("workspace_roots")
    first = roots[0] if isinstance(roots, list) and roots and isinstance(roots[0], str) else ""
    return {
        "generation": adapters.text(payload.get("generation_id")),
        "model": adapters.text(payload.get("model_id") or payload.get("model")),
        "loop": adapters.count(payload.get("loop_count")),
        "workspace": first or adapters.text(payload.get("cwd")),
        **({"usage": counts} if all(isinstance(value, int) and value >= 0 for value in counts.values()) else {}),
    }


def normalize(native: str, payload: dict, harness: str = ID) -> dict | None:
    spec = adapters.manifest(harness)
    tool = tool_of(native, payload)
    inner = fields if isinstance(fields := payload.get("tool_input"), dict) else {}
    event = {
        "harness": harness,
        "native": native,
        "events": adapters.events_for(spec, native, tool),
        "deny_rules": adapters.deny_rules(spec, None),
        "cwd": adapters.text(payload.get("cwd")),
        "session": adapters.text(payload.get("conversation_id") or payload.get("session_id")),
        "tool": tool,
        "input": {**{key: payload[key] for key in FIELDS if key in payload}, **inner},
        "failure": native.endswith("Failure"),
        "output": adapters.text(payload.get("output") or payload.get("tool_output")),
        "prompt": adapters.text(payload.get("prompt")),
    }
    if native == "subagentStop":
        return {**event, **subagent_fields(payload)}
    return {**event, **stop_fields(payload)} if native == "stop" else event


def encode(native: str, result: dict) -> tuple[str, str, int]:
    """(stdout, stderr, exit code): always one JSON object, never silence."""
    if result.get("deny"):
        reply: dict = {"permission": "deny", "user_message": result["deny"], "agent_message": result["deny"]}
    elif result.get("followup") and native in FOLLOWS_UP:
        reply = {"followup_message": result["followup"]}
    elif result.get("context") and native == "sessionStart":
        reply = {"additional_context": result["context"]}
    else:
        reply = {}
    return json.dumps(reply) + "\n", "", 0


def hooks(checkout: Path, harness: str = ID) -> dict:
    """`hooks/hooks.json`: one entry per native event, fail-closed for a guard, once per stop for a follow-up."""
    found: dict[str, list] = {}
    for entry in adapters.registrations(harness, adapters.hooks_dir(checkout)):
        hook = {"command": entry["command"], "timeout": entry["timeout"]}
        hook.update({"matcher": entry["matcher"]} if entry["matcher"] else {})
        hook.update({"failClosed": True} if entry["closed"] else {})
        hook.update({"loop_limit": 1} if entry["event"] in FOLLOWS_UP else {})
        found.setdefault(entry["event"], []).append(hook)
    return {"version": 1, "hooks": found}


def render(checkout: Path, home: Path) -> dict[str, tuple[str, str]]:
    """The plugin: its manifest, the rules, the agents and the hooks."""
    plugin = {"name": "el-capitan", "description": "el-capitan: spec-driven agentic engineering pipeline", "version": "0.0.0"}
    found = {
        f"{PLUGIN}/.cursor-plugin/plugin.json": ("file", json.dumps(plugin, indent=2) + "\n"),
        f"{PLUGIN}/hooks/hooks.json": ("file", json.dumps(hooks(checkout), indent=2) + "\n"),
    }
    found.update({f"{PLUGIN}/rules/{rule.name}": ("link", str(rule)) for rule in adapters.rules(checkout)})
    found.update(adapters.agent_entries(checkout, home, f"{PLUGIN}/agents"))
    return found
