"""Codex ("unverified live", from its docs): Claude-shaped hooks in ~/.codex/hooks.json (`SubagentStop` carries
`last_assistant_message`), TOML agents in ~/.codex/agents, skills in ~/.agents/skills, and Starlark `prefix_rule`s in
~/.codex/rules. Payloads and answers are Claude Code's, so the claude-code adapter normalises and encodes them.
"""

from __future__ import annotations

import json
from pathlib import Path

from crew.harness import adapters, claude_code

ID = "codex"


def normalize(native: str, payload: dict, harness: str = ID) -> dict | None:
    return claude_code.normalize(native, payload, harness)


def encode(native: str, result: dict) -> tuple[str, str, int]:
    return claude_code.encode(native, result)


def agent_toml(agent: Path, sandbox: str) -> str:
    """One agent as Codex TOML: its name, description and body; JSON strings are valid TOML basic strings."""
    from crew.lib.markdown import frontmatter

    text = agent.read_text(encoding="utf-8")
    meta, _ = frontmatter(text)
    body = text.split("\n---\n", 1)[1].lstrip("\n") if text.startswith("---\n") else text
    fields = {"name": agent.stem, "description": str((meta or {}).get("description") or ""), "sandbox_mode": sandbox, "developer_instructions": body}
    return "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in fields.items())


def prefix_rules() -> str:
    return "".join(f'prefix_rule(pattern = {json.dumps(pattern)}, decision = "forbidden")\n' for pattern in adapters.manifest(ID)["prefix_rules"])


def render(checkout: Path, home: Path) -> dict[str, tuple[str, str]]:
    """The agents (an inline orchestrator is not one), the skills, the forbidden prefixes and the hooks."""
    sandbox = adapters.manifest(ID)["sandbox"]
    hooks = json.dumps({"hooks": claude_code.hooks(checkout, ID)}, indent=2) + "\n"
    found = {".codex/rules/el-capitan.rules": ("file", prefix_rules()), ".codex/hooks.json": ("file", hooks)}
    for agent in adapters.agents(checkout):
        kind = adapters.access(agent)
        if kind in sandbox:
            found[f".codex/agents/{agent.stem}.toml"] = ("file", agent_toml(agent, sandbox[kind]))
    found.update({f".agents/skills/{skill.name}": ("link", str(skill)) for skill in adapters.skills(checkout)})
    return found
