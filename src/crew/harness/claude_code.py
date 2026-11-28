"""Claude Code: hooks and permissions merged into each config dir's settings.json, always-on rules imported from
~/.claude/el-capitan, ~/.claude/agents and ~/.claude/skills. Payloads carry `tool_input` and `tool_response`;
a deny is exit 2 with the reason on stderr, context is stdout (`additionalContext` after a tool call), a stop goes on
with `decision: block`. Cursor also runs the Claude-format hooks it finds (`cursor_version` in the payload): while
its plugin's hooks are installed, that copy does nothing here.
"""

from __future__ import annotations

import json
from pathlib import Path

from crew.harness import adapters

ID = "claude-code"
AGENTS = ".claude/agents"


def subagent_fields(payload: dict) -> dict:
    """A stopped subagent: who it was, its reply, and where its transcript is."""
    own = payload.get("agent_transcript_path")
    places = adapters.transcript_places(own, [payload.get("transcript_path"), own], [], [], Path.home())
    active = payload.get("stop_hook_active") is True
    return {
        "keys": sorted(payload),
        "agent_id": adapters.text(payload.get("agent_id")),
        "agent_type": adapters.text(payload.get("agent_type")),
        "reply": adapters.text(payload.get("last_assistant_message")),
        "resumable": not active,
        "loop": int(active),
        "transcripts": places[0],
        "transcript_dirs": places[1],
    }


def output_of(response: object) -> str:
    if isinstance(response, dict):
        return f"{response.get('stdout') or ''}\n{response.get('stderr') or ''}"
    return response if isinstance(response, str) else ""


def normalize(native: str, payload: dict, harness: str = ID) -> dict | None:
    """The normalised event, or None for Cursor's copy of a Claude-format registration while the plugin's hooks are
    installed (they answer it); without them the copy is judged, with Cursor's lack of deny rules."""
    copy = "cursor_version" in payload
    if copy and (Path.home() / adapters.manifest("cursor")["plugin"] / "hooks" / "hooks.json").is_file():
        return None
    spec = adapters.manifest(harness)
    tool = adapters.text(payload.get("tool_name") or payload.get("notification_type"))
    tool = "Bash" if tool == "Shell" else tool  # Cursor's copy names the shell `Shell`
    event = {
        "harness": harness,
        "native": native,
        "events": adapters.events_for(spec, native, tool),
        "deny_rules": not copy and adapters.deny_rules(spec, payload.get("permission_mode")),
        "cwd": adapters.text(payload.get("cwd")),
        "session": adapters.text(payload.get("session_id")),
        "tool": "Shell" if tool == "Bash" else tool,
        "input": payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {},
        "failure": native.endswith("Failure"),
        "output": output_of(payload.get("tool_response")),
        "prompt": adapters.text(payload.get("prompt")),
    }
    return {**event, **subagent_fields(payload)} if native == "SubagentStop" else event


def encode(native: str, result: dict) -> tuple[str, str, int]:
    """(stdout, stderr, exit code) for one result: `deny`, `followup` or `context`, or none of them."""
    if result.get("deny"):
        return "", result["deny"] + "\n", 2
    if result.get("followup"):
        return json.dumps({"decision": "block", "reason": result["followup"]}) + "\n", "", 0
    context = result.get("context", "")
    if context and native == "PostToolUse":
        return json.dumps({"hookSpecificOutput": {"hookEventName": native, "additionalContext": context}}) + "\n", "", 0
    return (context + "\n" if context else ""), "", 0


def hooks(checkout: Path, harness: str = ID) -> dict:
    """The Claude-shaped `hooks` object: one entry per native event and matcher, each running `crew-hook.py`."""
    found: dict[str, list] = {}
    for entry in adapters.registrations(harness, adapters.hooks_dir(checkout)):
        hook = {"type": "command", "timeout": entry["timeout"], "command": entry["command"]}
        found.setdefault(entry["event"], []).append({**({"matcher": entry["matcher"]} if entry["matcher"] else {}), "hooks": [hook]})
    return found


def render(checkout: Path, home: Path) -> dict[str, tuple[str, str]]:
    """Every file this harness reads, relative to HOME: the settings fragment install merges into each config dir
    (`merge`), the rules the imports name, the agents and the skills."""
    fragment = {"permissions": adapters.manifest(ID)["permissions"], "hooks": hooks(checkout)}
    found = {".claude/settings.json": ("merge", json.dumps(fragment, indent=2) + "\n")}
    found.update({f".claude/el-capitan/{rule.stem}.md": ("link", str(rule)) for rule in adapters.rules(checkout)})
    found.update(adapters.agent_entries(checkout, home, AGENTS))
    found.update({f".claude/skills/{skill.name}": ("link", str(skill)) for skill in adapters.skills(checkout)})
    return found
