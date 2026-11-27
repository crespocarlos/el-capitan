"""Held-out design-challenge cases for the architecture reviewer, in the format of `evals/reviewer/cases/`.

Each case is a change whose approach history rejected for a simpler or reused one. A catch must both challenge the
approach and name the approach history chose, so a reply that only lists defects inside the diff does not score.

Usage: python3 build_design_cases.py [out dir]   (default: ./cases next to this file)
The writer (`git_diff`, `line_of`, the record shape) is copied from `evals/reviewer/build_cases.py`.
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

CASES: list[dict] = []
OUT = Path(__file__).resolve().parent / "cases"


def case(**kw: object) -> None:
    CASES.append(kw)


# Wording that challenges the approach itself. Every case pairs it with a group naming the approach history chose,
# so these words alone (or a "Fix: use X instead" on an in-diff defect) never score.
CHALLENGE = ["instead", "rather than", "unnecessary", "not needed", "needless*", "no need", "redundant", "replace*",
             "over-engineer*", "overengineer*", "overbuilt", "over-built", "reinvent*", "re-implement*", "reimplement*",
             "hand-roll*", "duplicat*", "parallel", "wrong approach", "wrong layer", "wrong place", "redirect*",
             "rethink", "reconsider", "heavyweight", "too heavy", "machinery", "not the right", "better approach",
             "better fit", "belongs in", "should live", "should be a", "should be one", "move this", "move it",
             "prefer*", "don't build", "do not build"]

CONFIG = '''{
  "mcp": {
    "docs": ["docs-internal", "docs-public"],
    "code_search": ["plugin_codeindex_codeindex", "code-search"]
  }
}
'''

# ---------------------------------------------------------------- 1. mirror MCP servers between config dirs

INSTALL_BLOCKS_BEFORE = '''"""Install steps that need more than shell: config dirs and the manifest (excerpt)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST = Path.home() / ".agent" / "install-manifest.json"


def config_dirs(home: Path) -> list[Path]:
    """Every Claude config dir install writes to: `~/.claude` first, then each one recorded in the manifest."""
    recorded = json.loads(MANIFEST.read_text()).get("config_dirs", []) if MANIFEST.is_file() else []
    return [home / ".claude", *(Path(p) for p in recorded if Path(p) != home / ".claude")]


def record(section: str, entry: dict) -> None:
    """Append one entry to a manifest section, so uninstall can undo exactly what install did."""
    data = json.loads(MANIFEST.read_text()) if MANIFEST.is_file() else {}
    data.setdefault(section, []).append(entry)
    MANIFEST.write_text(json.dumps(data, indent=2) + "\\n")


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    if command == "config-dirs":
        print("\\n".join(str(p) for p in config_dirs(Path.home())))
        return 0
    print(f"install_blocks: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

INSTALL_BLOCKS_AFTER = '''"""Install steps that need more than shell: config dirs and the manifest (excerpt)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST = Path.home() / ".agent" / "install-manifest.json"


def config_dirs(home: Path) -> list[Path]:
    """Every Claude config dir install writes to: `~/.claude` first, then each one recorded in the manifest."""
    recorded = json.loads(MANIFEST.read_text()).get("config_dirs", []) if MANIFEST.is_file() else []
    return [home / ".claude", *(Path(p) for p in recorded if Path(p) != home / ".claude")]


def record(section: str, entry: dict) -> None:
    """Append one entry to a manifest section, so uninstall can undo exactly what install did."""
    data = json.loads(MANIFEST.read_text()) if MANIFEST.is_file() else {}
    data.setdefault(section, []).append(entry)
    MANIFEST.write_text(json.dumps(data, indent=2) + "\\n")


def configured_servers(home: Path) -> list[str]:
    """The server names `~/.agent/config.json` `mcp` lists, docs and code search alike."""
    mcp = json.loads((home / ".agent" / "config.json").read_text()).get("mcp") or {}
    return [*mcp.get("docs", []), *mcp.get("code_search", [])]


def mirror_mcp(home: Path) -> list[str]:
    """Copy each configured server's definition from `~/.claude.json` into every other config dir's `.claude.json`,
    at the same scope (user level, or the same `projects.<path>`), so a session on a second config dir reaches the
    same servers. A server the user already defined there is kept; each copy is recorded for uninstall."""
    source = json.loads((home / ".claude.json").read_text())
    scopes = [((), source.get("mcpServers", {}))]
    scopes += [(("projects", project), entry.get("mcpServers", {})) for project, entry in source.get("projects", {}).items()]
    names, copied = configured_servers(home), []
    for directory in config_dirs(home)[1:]:
        path = directory / ".claude.json"
        target = json.loads(path.read_text()) if path.is_file() else {}
        for keys, servers in scopes:
            for name in (n for n in names if n in servers):
                into = target
                for key in keys:
                    into = into.setdefault(key, {})
                into = into.setdefault("mcpServers", {})
                if name in into:
                    continue
                into[name] = servers[name]
                record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
                copied.append(f"{directory}: {name}")
        path.write_text(json.dumps(target, indent=2) + "\\n")
    return copied


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    if command == "config-dirs":
        print("\\n".join(str(p) for p in config_dirs(Path.home())))
        return 0
    if command == "mirror-mcp":
        for line in mirror_mcp(Path.home()):
            print(f"  mirrored MCP server {line}")
        return 0
    print(f"install_blocks: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''  # noqa: E501

INSTALL_SH_BEFORE = '''# Link agents, skills and rules into every Claude config dir, and render the read-only agents' tools.
while IFS= read -r dir; do
  link_config_dir "$dir"
done < <(python3 "$SCRIPT_DIR/.claude/install_blocks.py" config-dirs)
render_readonly_agents
'''  # noqa: E501

INSTALL_SH_AFTER = '''# Link agents, skills and rules into every Claude config dir, and render the read-only agents' tools.
while IFS= read -r dir; do
  link_config_dir "$dir"
done < <(python3 "$SCRIPT_DIR/.claude/install_blocks.py" config-dirs)
render_readonly_agents
# Sessions on a second config dir (such as ~/.claude-work) get the same MCP servers as ~/.claude.
run python3 "$SCRIPT_DIR/.claude/install_blocks.py" mirror-mcp
'''  # noqa: E501

case(id="design-mcp-mirror-config-dirs", lens="architecture", hand_seeded=True,
     source="hand-seeded from task D01FEE1F (spec abandoned and deleted; its drafts are in the session record of "
            "task 2D916668), replaced by task 2D916668 SPEC.md (Summary, the lookups criteria, Hints: copying "
            "servers between Claude config dirs is out of scope)",
     summary="The owner already has their MCP servers installed (docs servers and a code-search plugin) and names "
             "them in `~/.agent/config.json` `mcp` (a copy is in the working directory as `.agent/config.json`). "
             "Install renders those servers into the read-only agents' `tools:` lists, which works for sessions on "
             "`~/.claude`. A session on a second Claude config dir, such as `~/.claude-work`, has no MCP servers, so "
             "its crew agents fall back to text search. Install now mirrors the configured servers: it copies each "
             "definition from `~/.claude.json` into every other recorded config dir's `.claude.json`, at the same "
             "scope, records each copy in the install manifest, and never overwrites a server the user defined "
             "there.",
     defect="The wrong fix for the need. Copying server definitions into Claude Code's own state file "
            "(`<dir>/.claude.json`) duplicates the owner's configuration (headers, env, per-dir OAuth sign-in), "
            "drifts from the source, needs manifest bookkeeping and uninstall, and still misses plugin-provided "
            "servers, which live under `<dir>/plugins/`, not in `.claude.json`. The servers are already installed "
            "and the agents already have them in their tool lists; what was missing is instructions telling every "
            "working agent when and how to use them. History abandoned the mirroring spec: no copying; one shared "
            "lookups reference that each crew agent points to, plus doctor fixes (detect plugin servers, check "
            "only projects with crew work, report without telling the owner to configure Claude).",
     files=[(".claude/install_blocks.py", INSTALL_BLOCKS_BEFORE, INSTALL_BLOCKS_AFTER),
            ("install.sh", INSTALL_SH_BEFORE, INSTALL_SH_AFTER)],
     context={".agent/config.json": CONFIG},
     locations=[(".claude/install_blocks.py", "def mirror_mcp(home: Path) -> list[str]:"),
                (".claude/install_blocks.py", "into[name] = servers[name]"),
                ("install.sh", "install_blocks.py\" mirror-mcp")])

# ---------------------------------------------------------------- 2. read-only agents by a deny list

LINT_BEFORE = '''"""Prompt lint rules over `.cursor/agents` (excerpt)."""
from __future__ import annotations

import re
from pathlib import Path

TOOLS_LINE = re.compile(r"^tools:[ \\t]*(.*)$", re.MULTILINE)
# Agents that only read and report: reviewer personas, explorers and spec critics.
READONLY_AGENTS = ("reviewer-adversarial", "reviewer-architecture", "reviewer-code-quality", "reviewer-product-flow",
                   "reviewer-prompt-quality", "reviewer-layers", "specwriter-adversarial", "specwriter-scope",
                   "specwriter-explorer", "reviewer-explorer")
READONLY_TOOLS = ("Read", "Grep", "Glob")


def lint_readonly_tools(root: Path) -> Findings:
    """Each read-only agent declares exactly the native read tools."""
    findings: Findings = []
    for stem in READONLY_AGENTS:
        path = root / ".cursor/agents" / f"{stem}.md"
        line = TOOLS_LINE.search(path.read_text(errors="replace"))
        tools = tuple(tool.strip() for tool in line.group(1).split(",")) if line else ()
        if tools != READONLY_TOOLS:
            findings.append((rel(root, path), 1, "readonly-tools", f"declare tools: {', '.join(READONLY_TOOLS)}"))
    return findings
'''

LINT_AFTER = '''"""Prompt lint rules over `.cursor/agents` (excerpt)."""
from __future__ import annotations

import re
from pathlib import Path

TOOLS_LINE = re.compile(r"^tools:[ \\t]*(.*)$", re.MULTILINE)
DENY_LINE = re.compile(r"^disallowedTools:[ \\t]*(.*)$", re.MULTILINE)
# Agents that only read and report: reviewer personas, explorers and spec critics.
READONLY_AGENTS = ("reviewer-adversarial", "reviewer-architecture", "reviewer-code-quality", "reviewer-product-flow",
                   "reviewer-prompt-quality", "reviewer-layers", "specwriter-adversarial", "specwriter-scope",
                   "specwriter-explorer", "reviewer-explorer")
# In Claude Code an explicit `tools:` list shuts every MCP server out, so read-only agents carry no `tools:` line and
# inherit the session's tools, the docs and code-search servers included. This one list denies what writes or acts
# outside the review; the search servers are read-only and stay available.
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", "Skill", "SendMessage", "TaskStop",
                       "EnterWorktree", "ExitWorktree", "Artifact", "ArtifactData", "ArtifactComments",
                       "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", "mcp__linear__*", "mcp__jira__*",
                       "mcp__notion__*", "mcp__filesystem__*")


def lint_readonly_tools(root: Path) -> Findings:
    """Each read-only agent has no `tools:` line, so it inherits the MCP servers, and denies exactly
    `READONLY_AGENT_DENY`."""
    findings: Findings = []
    for stem in READONLY_AGENTS:
        path = root / ".cursor/agents" / f"{stem}.md"
        text = path.read_text(errors="replace")
        if TOOLS_LINE.search(text):
            findings.append((rel(root, path), 1, "agents-inherit-tools", "drop the tools: line so MCP is inherited"))
        deny = DENY_LINE.search(text)
        listed = tuple(tool.strip() for tool in deny.group(1).split(",")) if deny else ()
        if listed != READONLY_AGENT_DENY:
            findings.append((rel(root, path), 1, "agents-inherit-tools", "set disallowedTools to READONLY_AGENT_DENY"))
    return findings
'''

AGENT_BEFORE = '''---
name: specwriter-scope
description: "Spec scope and implementer critic for PR boundaries, task granularity, and builder compatibility. Dispatched by crew-specwriter — do not invoke directly."
readonly: true
tools: Read, Grep, Glob
maxTurns: 14
---

You are a scope critic for a draft spec. Read the spec and the files it names; never edit.
'''  # noqa: E501

AGENT_AFTER = '''---
name: specwriter-scope
description: "Spec scope and implementer critic for PR boundaries, task granularity, and builder compatibility. Dispatched by crew-specwriter — do not invoke directly."
readonly: true
disallowedTools: Write, Edit, NotebookEdit, Bash, Agent, Skill, SendMessage, TaskStop, EnterWorktree, ExitWorktree, Artifact, ArtifactData, ArtifactComments, mcp__github__*, mcp__gitlab__*, mcp__slack__*, mcp__linear__*, mcp__jira__*, mcp__notion__*, mcp__filesystem__*
maxTurns: 14
---

You are a scope critic for a draft spec. Read the spec and the files it names; never edit.
'''  # noqa: E501

case(id="design-readonly-deny-list", lens="architecture", hand_seeded=True,
     source="hand-seeded from task EF8C1BD6 SPEC.md: the first criteria (one deny list per agent class) and the "
            "owner's amendment that replaced them with an install-rendered allowlist (PR #33)",
     summary="Read-only agents (reviewer personas, explorers, spec critics) declared `tools: Read, Grep, Glob`. In "
             "Claude Code an explicit `tools:` list shuts out every MCP server, so these agents never reach the docs "
             "and code-search servers the owner names in `~/.agent/config.json` `mcp` (a copy is in the working "
             "directory as `.agent/config.json`). They now drop `tools:` and inherit the session's tools, MCP "
             "included, and one `disallowedTools` list, defined once in `lint_prompts.py`, denies the tools that "
             "write or act outside the review. The lint holds every read-only agent to that exact list; "
             "`specwriter-scope` shows the new frontmatter.",
     defect="A deny list fails open: every tool it does not name is granted, so claude.ai connectors "
            "(`mcp__claude_ai_*`), plugin servers, WebFetch, WebSearch and any server or tool added later reach the "
            "read-only agents, and staying read-only depends on the list never going stale. The owner's amendment "
            "replaced it: keep an allowlist, `tools: Read, Grep, Glob{{mcp_servers}}`, which install renders with "
            "one `mcp__<server>__*` per server named in `~/.agent/config.json` `mcp` (nothing configured renders the "
            "plain list), and drop `disallowedTools`.",
     files=[(".agent/tools/maintenance/lint_prompts.py", LINT_BEFORE, LINT_AFTER),
            (".cursor/agents/specwriter-scope.md", AGENT_BEFORE, AGENT_AFTER)],
     context={".agent/config.json": CONFIG},
     locations=[(".agent/tools/maintenance/lint_prompts.py", "READONLY_AGENT_DENY = (\"Write\""),
                (".agent/tools/maintenance/lint_prompts.py", "if TOOLS_LINE.search(text):"),
                (".cursor/agents/specwriter-scope.md", "disallowedTools:")])

# ---------------------------------------------------------------- 3. ship by a manual chain of commands

IMPLEMENT_BEFORE = '''### Step 6: Launch worker

Dispatch `crew-builder` with the task directory and the approved SPEC.md. Each task's `Verify:` command runs after
the worker reports.

### Step 7: Hand off

- **Stop after all tasks pass.** Never commit, push, or create a PR; output the handoff before stopping.

> Next: run `crew review` to verify the change, then `crew commit`, then `crew open pr`.
'''

IMPLEMENT_AFTER = '''### Step 6: Launch worker

Dispatch `crew-builder` with the task directory and the approved SPEC.md. Each task's `Verify:` command runs after
the worker reports.

### Step 7: Ship

After every task passes and the owner says go, commit and open the draft PR from the task's recorded worktree, so
the owner no longer runs `crew commit` and `crew open pr` by hand. Run these in order and stop at the first
failure:

```bash
cd "$(jq -r .worktree "$TASK_DIR/.task-id")"
BASE=$(jq -r .base "$TASK_DIR/.task-id")
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
git fetch origin "$BASE" && git merge --no-edit "origin/$BASE"
bash evals/test.sh -n auto        # the spec's `## Tests` commands
git push -u origin HEAD
PR_URL=$(GH_PAGER=cat gh pr create --draft --title "$TITLE" --body-file "$BODY_FILE" --base "$BASE") && echo "$PR_URL"
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
```

If a step fails, fix the cause, commit the fix, and run the remaining steps again.

> Next: run `crew review` first if the change has not been reviewed.
'''

case(id="design-ship-manual-chain", lens="architecture", hand_seeded=True,
     source="hand-seeded from task 1D001C12 SPEC.md, Phase 2 (one command ships a task): the skills' manual commit "
            "and PR chain replaced by `crew-task.py ship`",
     summary="Shipping a task took three separate skills (`crew implement`, `crew commit`, `crew open pr`). "
             "`crew-implement` now ends with a Ship step: after the owner's go, the orchestrator runs the listed "
             "commands in the task's recorded worktree to stage, commit, merge the base, re-run the spec's tests, "
             "push, open the draft PR and mark the task done. `crew-task.py` is the task CLI that owns the task "
             "state (`.task-id`, PROGRESS.md and the gates such as `mark-done`).",
     defect="Shipping as a prose chain the model runs step by step is the wrong layer. Nothing records which steps "
            "finished, so after a stop (a conflict, a failing test, a lost session) the model reconstructs where it "
            "was and a re-run commits again or opens a second PR; `git add -A` stages secrets and large files "
            "unchecked; the tests run with no time limit and under the session's environment; and every skill that "
            "ships carries its own copy of the chain. History replaced the chain with one resumable command, "
            "`crew-task.py ship <TASK_DIR> --title --body-file`: it stages with secret and size checks, commits, "
            "merges the base, re-runs the spec's tests with limits, pushes, opens the draft PR and marks done, "
            "appending a `SHIP <step>` entry to PROGRESS.md per finished step so a re-run continues from the first "
            "unfinished one. The skills only call it.",
     files=[(".cursor/skills/crew-implement/SKILL.md", IMPLEMENT_BEFORE, IMPLEMENT_AFTER)],
     locations=[(".cursor/skills/crew-implement/SKILL.md", "git add -A"),
                (".cursor/skills/crew-implement/SKILL.md", "If a step fails, fix the cause")])

# ---------------------------------------------------------------- 4. approval gate by marker files and two hooks

SETTINGS_BEFORE = '''{
  "permissions": {
    "allow": [
      "Read(~/.agent/**)"
    ],
    "ask": [
      "Bash(git push --force*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "bash \\"$HOME/.claude/hooks/guard/credentials.sh\\"" }
        ]
      }
    ]
  }
}
'''

SETTINGS_AFTER = '''{
  "permissions": {
    "allow": [
      "Read(~/.agent/**)"
    ],
    "ask": [
      "Bash(git push --force*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "bash \\"$HOME/.claude/hooks/guard/credentials.sh\\"" }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          { "type": "command", "command": "bash \\"$HOME/.claude/hooks/review-address-gate.sh\\"" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "bash \\"$HOME/.claude/hooks/review-address-approval.sh\\"; exit 0" }
        ]
      }
    ]
  }
}
'''

GATE = '''#!/usr/bin/env bash
# Deny edits under `crew review address` until the user's own prompt approved a fix set.
#
# Two markers under ~/.agent/review-address, both scoped to a session and a review directory:
#   pending  — written by the skill when it presents the verdict table;
#   approved — written only by review-address-approval.sh, from the user's own message.
# No pending marker, or one from another session, means an ordinary edit: allow.
set -euo pipefail
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"

session=$(hook_field session_id)
state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"

[ -f "$pending" ] || hook_allow
armed_session=$(jq -r '.session // empty' "$pending" 2>/dev/null || true)
[ -n "$session" ] && [ "$armed_session" = "$session" ] || hook_allow
armed_review=$(jq -r '.review_dir // empty' "$pending" 2>/dev/null || true)

if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \\
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
fi
hook_deny "Review-address gate: the verdict table for ${armed_review:-this review} has no approval yet. Reply with the fixes to apply (all / none / numbers)."
'''  # noqa: E501

APPROVAL = '''#!/usr/bin/env bash
# UserPromptSubmit: record the approval half of the review-address gate. Only a user turn reaches this hook, so the
# model cannot write `approved` itself. Inert until the skill has written `pending`.
set +e
state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"
[ -f "$pending" ] || exit 0

input=$(cat)
prompt=$(printf '%s' "$input" | jq -r '.prompt // empty' 2>/dev/null)
armed_session=$(jq -r '.session // empty' "$pending" 2>/dev/null)
armed_review=$(jq -r '.review_dir // empty' "$pending" 2>/dev/null)
[ "$(printf '%s' "$input" | jq -r '.session_id // empty')" = "$armed_session" ] || exit 0

# `none` authorizes no edit, so it records nothing; any other accepted answer authorizes at least one fix.
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|ok|approve[d]?|apply( all)?|go ahead|proceed)[[:space:].!]*$|^[[:space:]]*[0-9]+([[:space:],]+[0-9]+)*[[:space:]]*$'; then
  mkdir -p "$state"
  jq -n --arg s "$armed_session" --arg r "$armed_review" --arg p "$prompt" '{session:$s, review_dir:$r, prompt:$p}' > "$approved"
fi
exit 0
'''  # noqa: E501

case(id="design-review-address-marker-gate", lens="architecture", hand_seeded=True,
     source="hand-seeded from task EE4BA3D2 SPEC.md (Decisions: the review-address marker protocol is replaced; "
            "task 5) and the two hooks it deleted (el-capitan 81477dc to 3d8fa25)",
     summary="`crew review address` presents a verdict table of review findings and must not edit anything until "
             "the owner says which fixes to apply. Prose in the skill did not hold that gate, so it is now "
             "structural: the skill writes a `pending` marker (session and review directory) when it presents the "
             "table, a UserPromptSubmit hook writes `approved` when the owner's own message answers it, and a "
             "PreToolUse hook on Edit and Write denies while a pending marker in this session has no matching "
             "approval. Both hooks are registered in the settings template that install merges into each Claude "
             "config dir.",
     defect="Two hooks, two state files and a model-written marker rebuild an approval gate the harness already "
            "has. The model writes `pending`, so it can disarm the gate by not writing it; the markers go stale "
            "across sessions and need scoping; a regex over the owner's reply decides what counts as approval. A "
            "`permissions.ask` rule on the edits of the review-address flow makes the harness ask the owner before "
            "the first edit, with no state and no forgeable marker. History deleted both hooks and the marker reads "
            "and added the ask rule (task EE4BA3D2, task 5).",
     files=[(".claude/hooks/review-address-gate.sh", None, GATE),
            (".claude/hooks/review-address-approval.sh", None, APPROVAL),
            (".claude/settings.json", SETTINGS_BEFORE, SETTINGS_AFTER)],
     locations=[(".claude/hooks/review-address-gate.sh", '[ -f "$pending" ] || hook_allow'),
                (".claude/hooks/review-address-approval.sh", "> \"$approved\""),
                (".claude/settings.json", "review-address-gate.sh")])

# ---------------------------------------------------------------- 5. a private git helper beside lib/git.py

GIT_LIB = '''"""The one door to git for the Python tools (excerpt). Every helper raises `GitError` when git cannot answer;
empty output is never read as an answer."""
from __future__ import annotations

import subprocess
from pathlib import Path

LOCAL_TIMEOUT = 10


class GitError(RuntimeError):
    """Git could not answer: not a repository, a missing ref or remote, a timeout."""


def run_git(root: Path | None, arguments: list[str], timeout: float = LOCAL_TIMEOUT) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, timeout=timeout, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        raise GitError(f"git {' '.join(arguments)}: {error}") from error


def output(root: Path | None, arguments: list[str]) -> str:
    return run_git(root, arguments).stdout.strip()


def current_branch(root: Path | None) -> str:
    """The checked-out branch; raises `GitError` on a detached HEAD."""
    branch = output(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch == "HEAD":
        raise GitError(f"{root}: detached HEAD")
    return branch


def remote_url(root: Path | None, name: str = "origin") -> str | None:
    """The remote's URL, or None when the repository has no such remote."""
    if name not in output(root, ["remote"]).split():
        return None
    return output(root, ["remote", "get-url", name])


def slug_from_url(url: str | None) -> str | None:
    """`owner/name` of a GitHub remote URL (ssh or https), or None."""
    if not url:
        return None
    tail = url.strip().rstrip("/").removesuffix(".git")
    parts = tail.replace(":", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else None
'''  # noqa: E501

DOCTOR_WORKTREES = '''"""Doctor: each task's recorded worktree exists, is on the task's branch, and has the task's repository as origin."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

TASKS = Path.home() / ".agent" / "tasks"


def _git(tree: Path, *args: str) -> str:
    """One git read in `tree`: its stripped stdout."""
    result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def _slug(url: str) -> str:
    """`owner/name` of a remote URL, ssh or https."""
    tail = url.rstrip("/").removesuffix(".git")
    return "/".join(tail.replace(":", "/").split("/")[-2:])


def check_worktrees(tasks: Path = TASKS) -> list[tuple[str, str]]:
    """One WARN row per task whose recorded worktree is missing, on another branch, or from another repository."""
    rows = []
    for meta_path in sorted(tasks.glob("*/.task-id")):
        meta = json.loads(meta_path.read_text())
        if not meta.get("worktree"):
            continue
        tree, name = Path(meta["worktree"]), meta.get("slug", meta_path.parent.name)
        if not tree.is_dir():
            rows.append(("WARN", f"{name}: the recorded worktree {tree} is missing"))
            continue
        branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != meta.get("branch"):
            rows.append(("WARN", f"{name}: {tree} is on {branch}, not {meta.get('branch')}"))
        origin = _git(tree, "remote", "get-url", "origin")
        if _slug(origin) != _slug(meta.get("repo_remote_url", "")):
            rows.append(("WARN", f"{name}: {tree} has origin {origin or '(none)'}, not the task's repository"))
    return rows
'''  # noqa: E501

case(id="design-private-git-helper", lens="architecture", hand_seeded=True,
     source="hand-seeded from task D2673565 SPEC.md (Centralize git access in one library: private git helpers and "
            "hand-rolled subprocess calls routed through lib/git.py)",
     summary="`crew doctor` gains a check that every task's recorded worktree (`.task-id` `worktree`) still exists, "
             "is on the task's branch, and has the task's repository (`repo_remote_url`) as `origin`. The new module "
             "reads git through a small `_git` helper and compares remotes by their `owner/name`. The tools' "
             "shared git module is in the working directory as `.agent/tools/lib/git.py`.",
     defect="The check re-implements git access the shared library already provides: `current_branch`, "
            "`remote_url` and `slug_from_url` in `lib/git.py`, all raising `GitError`. The private `_git` ignores "
            "git's failure (`check=False`, no timeout) and reads empty output as an answer (no origin becomes an "
            "empty slug, a detached HEAD becomes the branch 'HEAD'), and `_slug` is a second URL parser. History "
            "(task D2673565) centralized git in `lib/git.py` precisely to remove private helpers with their own "
            "failure modes; new code calls the library.",
     files=[(".agent/tools/maintenance/doctor_worktrees.py", None, DOCTOR_WORKTREES)],
     context={".agent/tools/lib/git.py": GIT_LIB},
     locations=[(".agent/tools/maintenance/doctor_worktrees.py", "def _git(tree: Path, *args: str) -> str:"),
                (".agent/tools/maintenance/doctor_worktrees.py", 'branch = _git(tree, "rev-parse"'),
                (".agent/tools/maintenance/doctor_worktrees.py", "def _slug(url: str) -> str:")])

# ---------------------------------------------------------------- keywords: [challenge, better approach, ...]

KEYWORDS: dict[str, list[list[str]]] = {
    "design-mcp-mirror-config-dirs": [
        CHALLENGE,
        ["instruction*", "lookups", "guidance", "doctor", "already installed", "already available", "already reach*",
         "already in their tool*", "already in the tool*", "out of scope", "owner's config*", "user's config*",
         "Claude's own config*", "Claude Code's own"]],
    "design-readonly-deny-list": [
        CHALLENGE,
        ["allowlist*", "allow-list*", "allow list*", "whitelist*", "explicit list", "explicit tools", "default-deny",
         "deny by default", "deny-by-default", "fail closed", "fails closed"],
        ["config*", "render*", "install*", "placeholder", "templat*", "generat*"]],
    "design-ship-manual-chain": [
        CHALLENGE,
        ["one command", "single command", "subcommand*", "sub-command*", "one tool", "single tool", "codif*",
         "in code", "in Python", "one script", "single script", "a script", "one CLI", "the CLI"],
        ["resum*", "idempot*", "checkpoint*", "re-run*", "rerun*", "pick up", "picks up", "continue*",
         "where it stopped", "progress", "partial*"]],
    "design-review-address-marker-gate": [
        CHALLENGE,
        ["ask rule*", "ask permission*", "ask-permission*", "ask-before-edit", "ask before", "asks before",
         "asks the owner", "asks the user", "permission prompt*", "approval prompt*", "permission rule*",
         "ask list", "ask entry", "ask section", "ask array", "permissions ask", "harness asks", "built-in prompt*",
         "native prompt*", "native approval", "built-in approval", "native permission*", "built-in permission*"]],
    "design-private-git-helper": [
        CHALLENGE,
        ["librar*", "existing helper*", "shared helper*", "shared module", "git module", "centrali*",
         "already provides", "already provided", "already exists", "already exist", "reuse*", "re-use*",
         "one door"]],
}


# ---------------------------------------------------------------- writer (copied from evals/reviewer/build_cases.py)

def git_diff(path: str, before: str | None, after: str) -> str:
    """One file's diff in git's shape, so the persona reads what a real review sends."""
    old = [] if before is None else before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    head = f"diff --git a/{path} b/{path}\n"
    if before is None:
        head += "new file mode 100644\n"
    body = difflib.unified_diff(old, new, "/dev/null" if before is None else f"a/{path}", f"b/{path}", n=3)
    return head + "".join(body)


def line_of(text: str, needle: str, where: str) -> int:
    hits = [n for n, line in enumerate(text.splitlines(), 1) if needle in line]
    if len(hits) != 1:
        raise SystemExit(f"{where}: {needle!r} matches {len(hits)} lines")
    return hits[0]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    for c in CASES:
        directory = out / c["id"]
        directory.mkdir(parents=True, exist_ok=True)
        kind = c.get("kind", "diff")
        texts: dict[str, str] = dict(c.get("context") or {})
        diff = "".join(git_diff(p, b, a) for p, b, a in c["files"])
        (directory / "change.diff").write_text(diff, encoding="utf-8")
        texts.update({p: a for p, _, a in c["files"]})
        locations = [{"file": f, "line": line_of(texts[f], needle, c["id"])} for f, needle in c["locations"]]
        record = {"id": c["id"], "lens": c["lens"], "kind": kind, "hand_seeded": c.get("hand_seeded", False),
                  "source": c["source"], "summary": c["summary"], "defect": c["defect"],
                  "locations": locations, "refs": c.get("refs", []), "keywords": KEYWORDS[c["id"]],
                  "context": c.get("context") or {},
                  # A design reply names its better mechanism in backticks, so its keywords match code too.
                  "match_code": True,
                  "after": {p: a for p, _, a in c.get("files", [])}}
        (directory / "case.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(CASES)} cases written to {out}")


if __name__ == "__main__":
    main()
