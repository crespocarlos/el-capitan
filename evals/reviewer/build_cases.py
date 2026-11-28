"""The source of `evals/reviewer/cases/`: writes each case's case.json plus change.diff (a diff case) or spec.md.

Run `python3 evals/reviewer/build_cases.py` after editing a case here, and commit both. A location is a unique
substring of the file after the change, resolved to its line; keywords are whole words, a trailing `*` a prefix.
The quoted code is the reviewed code, kept byte for byte, so its long lines carry `noqa: E501`.
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


# ---------------------------------------------------------------- shared material

GUARD_BEFORE = '''#!/usr/bin/env bash
# Guard: a task SPEC.md is written only by the task that owns it (the `.task-id` slug).
set -euo pipefail
HOOK_NAME=check-task-spec-owner
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"

path=$(hook_field file_path)
tasks_root="$HOME/.agent/tasks"
case "$path" in */SPEC.md) ;; *) hook_allow ;; esac
task_dir=$(dirname "$path")
case "$task_dir" in "$tasks_root"/*) ;; *) hook_allow ;; esac
# `<tasks>/<uuid>/SPEC.md` only: a nested path such as `<uuid>/review/.../SPEC.md` is not a task spec.
[ "$(dirname "$task_dir")" = "$tasks_root" ] || hook_allow

metadata="$task_dir/.task-id"
[ -f "$metadata" ] || hook_allow
# Nothing to protect: a directory with no SPEC.md cannot lose one, and this is where every new task
# starts.
[ -f "$task_dir/SPEC.md" ] || hook_allow
owner=$(jq -r '.slug // empty' "$metadata" 2>/dev/null) || hook_allow
[ -n "$owner" ] || hook_allow
title=$(head -1 "$task_dir/SPEC.md" | sed 's/^# Spec: //')
[ "$(slugify "$title")" = "$owner" ] \\
  || hook_deny "Task spec guard: $task_dir belongs to '$owner'; write your own task's SPEC.md."
hook_allow
'''

GUARD_AFTER = '''#!/usr/bin/env bash
# Guard: a task SPEC.md is written only by the task that owns it (the `.task-id` slug).
#
# It also guards the Status line. Install allows every edit under `~/.agent/tasks` without a prompt, so
# an Edit or Write that changes the value under `## Status` of an existing task SPEC.md is denied: the
# status moves only through `crew-task.py`, which keeps Gate 1 and Gate 2 with the user. A Write is
# compared with the file on disk; an Edit is applied to the file on disk and the result compared.
set -euo pipefail
HOOK_NAME=check-task-spec-owner
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"

path=$(hook_field file_path)
tasks_root="$HOME/.agent/tasks"
case "$path" in */SPEC.md) ;; *) hook_allow ;; esac
task_dir=$(dirname "$path")
case "$task_dir" in "$tasks_root"/*) ;; *) hook_allow ;; esac
# `<tasks>/<uuid>/SPEC.md` only: a nested path such as `<uuid>/review/.../SPEC.md` is not a task spec.
[ "$(dirname "$task_dir")" = "$tasks_root" ] || hook_allow

# Nothing to protect: a directory with no SPEC.md cannot lose one, and this is where every new task
# starts.
[ -f "$task_dir/SPEC.md" ] || hook_allow

# The first non-blank line under `## Status`, trimmed; empty when the document has no such section.
status_of() {
  printf '%s\\n' "$1" | awk '/^## Status[ \\t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { gsub(/^[ \\t]+|[ \\t]+$/, ""); print; exit }'
}
old_string=$(hook_field old_string)
written=""
if [ -n "$old_string" ]; then
  disk=$(cat "$task_dir/SPEC.md") || hook_fail "cannot read $task_dir/SPEC.md"
  new_string=$(hook_field new_string)
  if [ "$(hook_field replace_all)" = true ]; then written=${disk//"$old_string"/"$new_string"}; else written=${disk/"$old_string"/"$new_string"}; fi
else
  written=$(hook_field content)
  if [ -n "$written" ]; then disk=$(cat "$task_dir/SPEC.md") || hook_fail "cannot read $task_dir/SPEC.md"; fi
fi
if [ -n "$written" ]; then
  before=$(status_of "$disk")
  after=$(status_of "$written")
  [ "$before" = "$after" ] \\
    || hook_deny "Task spec guard: this changes the Status of $task_dir/SPEC.md from '${before:-none}' to '${after:-none}'. The status moves only through crew-task.py mark-approved | mark-implementing | mark-done."
fi

metadata="$task_dir/.task-id"
[ -f "$metadata" ] || hook_allow
owner=$(jq -r '.slug // empty' "$metadata" 2>/dev/null) || hook_allow
[ -n "$owner" ] || hook_allow
title=$(head -1 "$task_dir/SPEC.md" | sed 's/^# Spec: //')
[ "$(slugify "$title")" = "$owner" ] \\
  || hook_deny "Task spec guard: $task_dir belongs to '$owner'; write your own task's SPEC.md."
hook_allow
'''  # noqa: E501

TASK_STATUS ='''"""Task status: the one reader of a spec's `## Status` (excerpt)."""
from __future__ import annotations

import re
from pathlib import Path

# The one reader of `## Status`; hooks and tools must not re-implement it.
STATUS = re.compile(r"^(## Status[ \\t]*\\r?\\n)([^\\n#][^\\n]*?)[ \\t]*$", re.M)
STATES = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD", "DONE")
# A user-only side state: not a transition, but a value the store legitimately holds.
SIDE_STATES = ("ABANDONED",)


def read_status(path: Path | str) -> str | None:
    """Return the status value, "" when unset, or None when the file is unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    match = STATUS.search(text)
    return match.group(2).strip() if match else ""
'''

GUARD_SUMMARY = ("Install now allows every Edit and Write under `~/.agent/tasks` without a prompt, so background "
                 "builders can write task files. To keep Gate 1 with the user, the existing SPEC.md owner hook now "
                 "also denies an Edit or Write that changes the value under `## Status`; only `crew-task.py` "
                 "moves the status, and `task_status.read_status` is what every tool reads.")

SETTINGS_BEFORE = '''{
  "permissions": {
    "allow": [
      "Read(~/.agent/**)"
    ],
    "ask": [
      "Edit(~/.agent/tasks/**/SPEC.md)",
      "Write(~/.agent/tasks/**/SPEC.md)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/check-task-spec-owner.sh"}]}
    ]
  }
}
'''

SETTINGS_AFTER = '''{
  "permissions": {
    "allow": [
      "Read(~/.agent/**)",
      "Edit(~/.agent/tasks/**)",
      "Write(~/.agent/tasks/**)"
    ],
    "additionalDirectories": ["~/.agent/tasks"]
  },
  "hooks": {
    "PreToolUse": [
      {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/check-task-spec-owner.sh"}]}
    ]
  }
}
'''

# ---------------------------------------------------------------- adversarial

case(id="status-guard-cr-heading", lens="adversarial",
     source="task 82FCCD58, review 20261127141048, adversarial finding 1 (a)",
     summary=GUARD_SUMMARY,
     defect="The hook reads Status with its own awk, which does not match a `## Status\\r` heading; "
            "`read_status` accepts `\\r?\\n`, so inserting `## Status\\r\\nAPPROVED` before the real heading "
            "sets APPROVED while the hook still sees DRAFTING.",
     files=[(".claude/hooks/check-task-spec-owner.sh", GUARD_BEFORE, GUARD_AFTER)],
     context={".agent/tools/task/task_status.py": TASK_STATUS},
     locations=[(".claude/hooks/check-task-spec-owner.sh", "printf '%s\\n' \"$1\" | awk")])

case(id="status-guard-second-section", lens="adversarial",
     source="task 82FCCD58, review 20261127141048, adversarial finding 1 (b)",
     summary=GUARD_SUMMARY,
     defect="The awk skips blank lines under the heading while `STATUS` does not: `## Status\\n\\nDRAFTING` plus a "
            "second `## Status\\nAPPROVED` further down reads DRAFTING to the hook and APPROVED to `read_status`.",
     files=[(".claude/hooks/check-task-spec-owner.sh", GUARD_BEFORE, GUARD_AFTER)],
     context={".agent/tools/task/task_status.py": TASK_STATUS},
     locations=[(".claude/hooks/check-task-spec-owner.sh", "printf '%s\\n' \"$1\" | awk")])

SPEC_GUARD = '''#!/usr/bin/env python3
"""The task-directory half of `check-task-spec-owner.sh`: one Write, Edit or MultiEdit payload on stdin.

Prints `skip`, `ok <path>` or `deny <message>`. The Status value is read with the one reader,
`task_status.STATUS`, before and after the write, and a write that leaves more than one `## Status`
heading is refused, since only the first is read.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path


def canonical_reader() -> re.Pattern:
    """`task_status.STATUS`, loaded by path from the checkout this hook links into."""
    source = Path(__file__).resolve().parents[3] / ".agent" / "tools" / "task" / "task_status.py"
    spec = importlib.util.spec_from_file_location("task_status", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.STATUS


STATUS = canonical_reader()
HEADING = re.compile(r"^## Status[ \\t]*\\r?$", re.M)


def status(text: str) -> str:
    match = STATUS.search(text)
    return match.group(2).strip() if match else ""


def verdict(path: str, after: str) -> str:
    """`ok <path>` when the write leaves the Status value alone, else `deny <message>`."""
    if not os.path.exists(path):
        return f"ok {path}"
    with open(path, encoding="utf-8", newline="") as handle:
        disk = handle.read()
    if len(HEADING.findall(after)) > 1:
        return f"deny Task spec guard: this leaves more than one '## Status' heading in {path}."
    before, now = status(disk), status(after)
    if before != now:
        return (f"deny Task spec guard: this changes the Status of {path} from '{before or 'none'}' "
                f"to '{now or 'none'}'. The status moves only through crew-task.py.")
    return f"ok {path}"


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    fields = payload.get("tool_input") or {}
    print(verdict(fields.get("file_path", ""), fields.get("content", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

case(id="status-guard-lone-cr", lens="adversarial",
     source="task 82FCCD58, review 20261127150524, adversarial finding 1",
     summary="The Status guard moves from awk to Python and reads the value with the canonical "
             "`task_status.STATUS`, so the hook and every tool agree on a spec's Status; a write that leaves two "
             "`## Status` headings is refused.",
     defect="The guard compares raw text (`newline=\"\"`, and the payload as sent) while `read_status` reads with "
            "universal newlines: a lone `\\r` after the heading hides a first Status section from the guard's "
            "regex and HEADING count, yet `read_status` sees it and returns APPROVED.",
     files=[(".claude/hooks/lib/spec_guard.py", None, SPEC_GUARD)],
     context={".agent/tools/task/task_status.py": TASK_STATUS},
     locations=[(".claude/hooks/lib/spec_guard.py", 'newline=""'),
                (".claude/hooks/lib/spec_guard.py", "match = STATUS.search(text)")])

case(id="status-guard-path-case", lens="adversarial",
     source="task 82FCCD58, review 20261127141048, adversarial finding 2",
     summary="Background builders cannot answer prompts, so install allows every Edit and Write under "
             "`~/.agent/tasks` and drops the ask rule for task SPEC.md files. The SPEC.md owner hook "
             "(`.claude/hooks/check-task-spec-owner.sh`, unchanged, in the working directory) still guards "
             "each task SPEC.md.",
     defect="With the ask rule gone the hook is the only gate, and it matches the raw path case-sensitively: "
            "`spec.md` on a case-insensitive disk, `..`, `//` or a symlink skip it, so the write goes through with "
            "no prompt.",
     files=[(".claude/settings.json", SETTINGS_BEFORE, SETTINGS_AFTER)],
     context={".claude/hooks/check-task-spec-owner.sh": GUARD_BEFORE},
     locations=[(".claude/hooks/check-task-spec-owner.sh", 'case "$path" in */SPEC.md)'),
                (".claude/hooks/check-task-spec-owner.sh", '[ "$(dirname "$task_dir")" = "$tasks_root" ]')])

GATES_BEFORE = '''def mark_done(task_dir: str | Path, pr_url: str, force: bool) -> int:
    """IMPLEMENTING to DONE with the PR that was opened; a DONE task only gains the PR in its list."""
    r = load_task(task_dir)
    if r is None:
        return 1
    if not force and not GITHUB_PR_URL.fullmatch(pr_url):
        print(f"error: --pr-url {pr_url!r} is not a GitHub PR URL (https://github.com/OWNER/REPO/pull/N); "
              "nothing written (--force records a free-text note instead)", file=sys.stderr)
        return 2
    if head(r) == "DONE":
        print(f"already done: {name(r)}")
        record_pr(r, pr_url)
        return 0
    if head(r) != "IMPLEMENTING":
        print(f"error: {name(r)} is {head(r) or 'unset'}, not IMPLEMENTING; nothing written",
              file=sys.stderr)
        return 1
    problems = done_problems(r)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(f"note: {review_location(r.task)}", file=sys.stderr)
        return 1
    print(f"done: {review_location(r.task)}")
    return 0 if set_status(r, "DONE", f"IMPLEMENTING → DONE (PR opened: {pr_url})") else 1
'''

GATES_AFTER = '''def mark_done(task_dir: str | Path, pr_url: str, force: bool) -> int:
    """IMPLEMENTING to DONE with the PR that was opened; with `--force`, any open state to DONE, a free-text note
    logged as `closed: <note>`. A DONE task only gains the PR in its list."""
    r = load_task(task_dir)
    if r is None:
        return 1
    if not force and not GITHUB_PR_URL.fullmatch(pr_url):
        print(f"error: --pr-url {pr_url!r} is not a GitHub PR URL (https://github.com/OWNER/REPO/pull/N); "
              "nothing written (--force records a free-text note instead)", file=sys.stderr)
        return 2
    state = head(r) or "unset"
    if state == "DONE":
        print(f"already done: {name(r)}")
        record_pr(r, pr_url)
        return 0
    if state != "IMPLEMENTING" and not force:
        print(f"error: {name(r)} is {state}, not IMPLEMENTING; nothing written (--force closes it)",
              file=sys.stderr)
        return 1
    problems = done_problems(r)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(f"note: {review_location(r.task)}", file=sys.stderr)
        return 1
    print(f"done: {review_location(r.task)}")
    note = pr_url if pr_url.startswith("closed:") else f"closed: {pr_url}"
    reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
    return 0 if set_status(r, "DONE", f"{state} → DONE ({reason})") else 1
'''

case(id="force-before-approval", lens="adversarial",
     source="task 285059E1, review 20261127153222, adversarial finding 2",
     summary="Stale tasks pile up in `crew ls`. `crew-task.py mark-done --force --pr-url <note>` now closes a task "
             "as DONE from any open state, with a free-text note logged as `closed: <note>`, so the owner can "
             "close work that will never ship. Gate 1 (`mark-approved`, the owner's approval) is what moves a "
             "spec from DRAFTING to APPROVED, and only an APPROVED spec may be implemented.",
     defect="`--force` with a real PR URL from DRAFTING or APPROVED records `DRAFTING → DONE (PR opened: <url>)`: "
            "shipped work that never passed Gate 1 looks like an ordinary finished task.",
     files=[(".agent/tools/task/task_gates.py", GATES_BEFORE, GATES_AFTER)],
     locations=[(".agent/tools/task/task_gates.py", 'if state != "IMPLEMENTING" and not force:'),
                (".agent/tools/task/task_gates.py", 'reason = f"PR opened: {pr_url}"')])

RECORD_PR = '''"""`record-pr`: after `gh pr create`, record the PR on its task and run the DONE gate (excerpt)."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

CLOSED = ("DONE", "ABANDONED")


def slug_of(title: str) -> str:
    """A task slug from a PR title: lowercase words joined by `-`, at most 60 characters."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].rstrip("-") or "pr"


def minimal_task(tasks_dir: Path, found: Pull, scoped: list[TaskState]) -> str:
    """A DONE task for a PR opened with no spec, in a repo that already has tasks; no gate runs."""
    owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
    directory = tasks_dir / str(uuid.uuid4()).upper()
    directory.mkdir(parents=True)
    meta = {"uuid": directory.name, "repo_remote_url": owner.meta["repo_remote_url"], "branch": found.branch,
            "slug": slug_of(found.title), "created_at": utc_stamp()}
    atomic_write(directory / ".task-id", json.dumps(meta, indent=2) + "\\n")
    title = found.title or found.url
    atomic_write(directory / "SPEC.md", f"# {title}\\n\\n## Status\\nDONE\\n\\n## Summary\\n"
                 f"Recorded by the PR hook: {found.url} was opened with no spec.\\n")
    append_pr(directory, found.url)
    return f"record-pr: no task for {found.branch}; recorded {found.url} as DONE task {directory} (no spec)"


def place(found: Pull, tasks_dir: Path) -> list[str]:
    """Record the PR on its task: the single open `branch` match, else the single match; never on a spec branch."""
    scoped = tasks_in(tasks_dir, found.repos)
    matches = [r for r in scoped if r.meta.get("branch") == found.branch]
    chosen = [r for r in matches if head(r) not in CLOSED] or matches
    if len(chosen) > 1:
        return candidates(f"{len(chosen)} tasks match {found.repos[0]} {found.branch}", chosen, found.url)
    if chosen:
        r = chosen[0]
        if head(r) == "IMPLEMENTING":
            return close(r, found.url, found.branch)
        done = "recorded PR" if append_pr(r.task, found.url) else "already has"
        return [f"record-pr: {r.slug} ({head(r) or 'no status'}): {done} {found.url}"]
    drafted = [r for r in scoped if r.meta.get("spec_branch") == found.branch]
    if drafted:
        names = ", ".join(r.slug for r in drafted)
        return candidates(f"{found.branch} is the spec branch of {names}", drafted, found.url)
    return [minimal_task(tasks_dir, found, scoped)] if scoped else []
'''

case(id="record-pr-duplicate", lens="adversarial",
     source="task B0334A9C, SPEC.md Summary item 1 (a duplicate task created in use); code from commit 130353e",
     summary="A PostToolUse hook runs after `gh pr create` and records the new PR on its task: the task whose "
             "`.task-id` `branch` is the PR's head branch. A PR opened with no spec gets a minimal DONE task, so "
             "every PR shows up in `crew ls`. `crew-task.py mark-done --pr-url <url>` also records the PR on the "
             "task (in its PR list) when the orchestrator closes it by hand, and `mark-implementing` records "
             "`branch` only when `--branch` is passed.",
     defect="Tasks are matched by `.task-id` `branch` only: a task that already holds the PR URL (closed by "
            "`mark-done` before the hook fired) or whose branch was left as the drafting branch is not found, so the "
            "hook creates a duplicate minimal DONE task for work that already has one.",
     files=[(".agent/tools/task/task_record_pr.py", None, RECORD_PR)],
     locations=[(".agent/tools/task/task_record_pr.py", "return [minimal_task(tasks_dir, found, scoped)]"),
                (".agent/tools/task/task_record_pr.py", 'matches = [r for r in scoped if r.meta.get("branch")')])

# ---------------------------------------------------------------- code-quality

DOCTOR = '''"""`crew doctor` MCP checks: which configured servers each Claude config dir can reach (excerpt)."""
from __future__ import annotations

import os
from pathlib import Path


def plugin_servers(directory: Path, settings: dict, names: set[str]) -> tuple[set[str], dict[str, set[str]]]:
    """The configured `plugin_<plugin>_<server>` names the dir's installed plugins provide: at user scope, and per
    project path; a plugin `enabledPlugins` sets to false provides none."""
    installed = read_object(directory / "plugins" / "installed_plugins.json").get("plugins")
    enabled = settings.get("enabledPlugins") if isinstance(settings.get("enabledPlugins"), dict) else {}
    user: set[str] = set()
    projects: dict[str, set[str]] = {}
    for plugin_id, installs in (installed.items() if isinstance(installed, dict) else []):
        served = {name for name in names if name.startswith(f"plugin_{plugin_id.split('@')[0]}_")}
        if enabled.get(plugin_id) is False or not served or not isinstance(installs, list):
            continue
        for install in (entry for entry in installs if isinstance(entry, dict)):
            if install.get("scope") == "user":
                user |= served
            elif isinstance(path := install.get("projectPath"), str):
                projects.setdefault(os.path.realpath(path), set()).update(served)
    return user, projects
'''

case(id="doctor-plugin-prefix", lens="code-quality",
     source="task 2D916668, review 20261127143927, adversarial finding 3",
     summary="`crew doctor` reports whether each configured MCP server is reachable. Claude Code names a plugin's "
             "server `plugin_<plugin>_<server>`; doctor now credits a configured server to an installed, enabled "
             "plugin, so a server that comes from a plugin is no longer reported missing.",
     defect="The match is a name prefix: with plugin `a` installed, `plugin_a_b_srv` (plugin `a_b`) matches "
            "`plugin_a_`, so doctor reports ok for a server whose plugin is missing or disabled; underscores make "
            "the name ambiguous.",
     files=[(".agent/tools/maintenance/doctor_mcp.py", None, DOCTOR)],
     locations=[(".agent/tools/maintenance/doctor_mcp.py", "served = {name for name in names if name.startswith")])

LINT_BEFORE = '''"""Prompt lint rules over `.cursor/agents` (excerpt)."""
from __future__ import annotations

import re
from pathlib import Path

TOOLS_LINE = re.compile(r"^tools:[ \\t]*(.*)$", re.MULTILINE)


def lint_native_tool_ids(root: Path, native: set[str]) -> Findings:
    """Each native id of an agent's `tools:` line is in `native_tools`, so a typo fails."""
    findings: Findings = []
    for path in sorted((root / ".cursor/agents").glob("*.md")):
        line = TOOLS_LINE.search(path.read_text(errors="replace"))
        for tool in (line.group(1).split(",") if line else []):
            if tool.strip() and tool.strip() not in native:
                findings.append((rel(root, path), 1, "tool-id-unknown", f"{tool.strip()} is not a native tool"))
    return findings
'''

LINT_AFTER = '''"""Prompt lint rules over `.cursor/agents` (excerpt)."""
from __future__ import annotations

import re
from pathlib import Path

TOOLS_LINE = re.compile(r"^tools:[ \\t]*(.*)$", re.MULTILINE)
# The review lenses and spec critics declare their tool-call budget once (`tool_budget:`), say it in their text,
# and get two turns past it, so the reply never competes with a tool call for the last turn.
BUDGETED_AGENTS = ("reviewer-adversarial", "reviewer-architecture", "reviewer-code-quality", "reviewer-product-flow",
                   "reviewer-prompt-quality", "specwriter-adversarial", "specwriter-scope")
REPLY_TURNS = 2
STATED_BUDGET = re.compile(r"stop calling tools at (\\d+)\\b", re.IGNORECASE)


def lint_turn_budget(root: Path) -> Findings:
    """Each budgeted agent declares `tool_budget: N` with `maxTurns` at least N + 2 and states "stop calling tools
    at N" once in its text; any other agent that declares a budget is held to the same two checks."""
    findings: Findings = []
    for path in sorted((root / ".cursor/agents").glob("*.md")):
        text = path.read_text(errors="replace")
        frontmatter_text, _, error = parse_frontmatter(text)
        if error:
            continue
        name, body = rel(root, path), text.split("\\n---\\n", 1)[1]
        budget = re.search(r"^tool_budget:[ \\t]*(\\d+)[ \\t]*$", frontmatter_text, re.MULTILINE)
        if not budget:
            if path.stem in BUDGETED_AGENTS:
                findings.append((name, 1, "persona-turn-budget", "declare tool_budget: N in the frontmatter"))
            continue
        calls = int(budget.group(1))
        turns = re.search(r"^maxTurns:[ \\t]*(\\d+)[ \\t]*$", frontmatter_text, re.MULTILINE)
        if not turns or int(turns.group(1)) < calls + REPLY_TURNS:
            findings.append((name, 1, "persona-turn-budget", f"set maxTurns to at least {calls + REPLY_TURNS}"))
        if STATED_BUDGET.findall(body) != [str(calls)]:
            findings.append((name, 1, "persona-turn-budget", f"say the budget once: \\"stop calling tools at {calls}\\""))
    return findings


def lint_native_tool_ids(root: Path, native: set[str]) -> Findings:
    """Each native id of an agent's `tools:` line is in `native_tools`, so a typo fails."""
    findings: Findings = []
    for path in sorted((root / ".cursor/agents").glob("*.md")):
        line = TOOLS_LINE.search(path.read_text(errors="replace"))
        for tool in (line.group(1).split(",") if line else []):
            if tool.strip() and tool.strip() not in native:
                findings.append((rel(root, path), 1, "tool-id-unknown", f"{tool.strip()} is not a native tool"))
    return findings
'''

case(id="lint-budget-allowlist", lens="code-quality",
     source="task 1D001C12, review 20261127163032, code-quality finding 3",
     summary="Every reviewer persona and spec critic must declare its tool-call budget as `tool_budget:` with "
             "`maxTurns` at least two above it; the shared reviewer contract no longer states a fallback number, "
             "so a persona without the key has no budget. A new `persona-turn-budget` lint rule enforces this.",
     defect="The rule only requires the key from a hand-maintained tuple: a new `reviewer-*` or `specwriter-*` "
            "persona nobody adds to `BUDGETED_AGENTS` passes the lint with no budget at all.",
     files=[(".agent/tools/maintenance/lint_prompts.py", LINT_BEFORE, LINT_AFTER)],
     locations=[(".agent/tools/maintenance/lint_prompts.py", "BUDGETED_AGENTS = ("),
                (".agent/tools/maintenance/lint_prompts.py", "if path.stem in BUDGETED_AGENTS:")])

TEST_LINT_BEFORE = '''"""Lint rule rows (excerpt)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("case,files,rule", HANDOFFS, ids=[case for case, _, _ in HANDOFFS])
def test_handoff(case: str, files: dict[str, str], rule: str | None, tmp: Path) -> None:
    root = write(tmp, {"rules/crew-router.mdc": ROUTER, **files})
    assert rules_of(lint_handoffs(root)) == ([rule] if rule else []), case
'''

TEST_LINT_AFTER = '''"""Lint rule rows (excerpt)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# (orchestrator file, the words of its rule): a dispatch that ends with no reply is resumed once with "deliver now".
RESUME_RULES = ((".cursor/agents/references/dispatch.md", "A dispatch that ends with no reply is resumed once, never re-dispatched"),
                (".cursor/agents/crew-specwriter.md", "A critic that returns no reply gets one\\n   resume, never a second dispatch"))


@pytest.mark.parametrize("path, rule", RESUME_RULES, ids=[row[0] for row in RESUME_RULES])
def test_a_silent_dispatch_is_resumed_once(path: str, rule: str) -> None:
    """crew-reviewer (through dispatch.md) and crew-specwriter resume a reply-less persona with `deliver now`."""
    text = (ROOT / path).read_text(encoding="utf-8")
    assert rule in text and "`deliver now: " in text, path


@pytest.mark.parametrize("case,files,rule", HANDOFFS, ids=[case for case, _, _ in HANDOFFS])
def test_handoff(case: str, files: dict[str, str], rule: str | None, tmp: Path) -> None:
    root = write(tmp, {"rules/crew-router.mdc": ROUTER, **files})
    assert rules_of(lint_handoffs(root)) == ([rule] if rule else []), case
'''

case(id="test-pins-prose", lens="code-quality",
     source="task 1D001C12, review 20261127163032, code-quality finding 4",
     summary="crew-reviewer and crew-specwriter must resume a persona that ended with no reply once, with "
             "`deliver now`, and never dispatch it a second time. A test row checks that each orchestrator file "
             "carries the rule.",
     defect="The test pins exact prose, including a line break and three spaces of list indentation: reflowing "
            "the paragraph breaks it while behaviour is unchanged, and a file that states the sentence but "
            "re-dispatches anyway still passes.",
     files=[("evals/tools/test_lint_rules.py", TEST_LINT_BEFORE, TEST_LINT_AFTER)],
     locations=[("evals/tools/test_lint_rules.py", '(".cursor/agents/crew-specwriter.md", "A critic'),
                ("evals/tools/test_lint_rules.py", 'assert rule in text and "`deliver now: " in text')])

# ---------------------------------------------------------------- architecture

INSTALL_BEFORE = '''if [ -d "$SCRIPT_DIR/.cursor/skills" ]; then
  shopt -s nullglob
  for skill in "$SCRIPT_DIR"/.cursor/skills/*/; do
    name=$(basename "$skill")
    run mkdir -p ~/.cursor/skills/$name
    run ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.cursor/skills/$name/SKILL.md
    link_dir_files "$SCRIPT_DIR/.cursor/skills/$name/references" ~/.cursor/skills/$name/references
  done
  shopt -u nullglob
  # Prune skill subdirs whose SKILL.md symlink is broken (skill was deleted from source)
  shopt -s nullglob
  for d in ~/.cursor/skills/*/; do
    skill_md="$d/SKILL.md"
    [[ -L "$skill_md" ]] || continue
    target=$(readlink "$skill_md")
    [[ "$target" == "$SCRIPT_DIR"* ]] || continue
    if [ ! -e "$skill_md" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [dry-run] remove stale skill dir: $d"
      else
        echo "  Removing stale skill: $(basename "$d")"
        rm -f "$skill_md"
        rmdir "$d" 2>/dev/null || true
      fi
    fi
  done
  shopt -u nullglob
fi
'''

INSTALL_AFTER = '''if [ -d "$SCRIPT_DIR/.cursor/skills" ]; then
  shopt -s nullglob
  for skill in "$SCRIPT_DIR"/.cursor/skills/*/; do
    name=$(basename "$skill")
    run mkdir -p ~/.cursor/skills/$name
    run ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.cursor/skills/$name/SKILL.md
    link_dir_files "$SCRIPT_DIR/.cursor/skills/$name/references" ~/.cursor/skills/$name/references
  done
  # A file deleted or moved in the repo leaves a dangling link in its skill folder, at any depth (a whole
  # skill, or one reference). Drop the dangling links into this checkout, then the folders that left empty.
  # `find` does not follow links, and a link elsewhere or a regular file is the user's, so both stay.
  for d in ~/.cursor/skills/*/; do
    [[ -L "${d%/}" ]] && continue
    pruned=0
    while IFS= read -r link; do
      target=$(readlink "$link")
      [[ "$target" == "$SCRIPT_DIR"/* && ! -e "$link" ]] || continue
      pruned=1
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [dry-run] remove broken symlink: $link -> $target"
      else
        echo "  Removing stale symlink: ${link#"$HOME"/}"
        rm -f "$link"
      fi
    done < <(find "$d" -type l)
    if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
      find "$d" -depth -type d -empty -delete
    fi
  done
  shopt -u nullglob
fi
'''

case(id="install-prune-user-folders", lens="architecture",
     source="task 2D916668, review 20261127143927, adversarial finding 8",
     summary="`install.sh` links each skill's files from this checkout into `~/.cursor/skills/<skill>/`, a folder "
             "the user may also keep their own files and folders in. When a skill file is deleted or moved in "
             "the repo, install now prunes the dangling links it left at any depth, not only a whole skill's "
             "SKILL.md, and removes the folders that pruning left empty.",
     defect="Once one dangling link is pruned, `find -empty -delete` removes every empty folder under the skill, "
            "including folders the user created by hand that install never owned.",
     files=[("install.sh", INSTALL_BEFORE, INSTALL_AFTER)],
     locations=[("install.sh", 'find "$d" -depth -type d -empty -delete')])

RECORD_PR_CLOSE = '''"""`record-pr`: after `gh pr create`, record the PR on its task and run the DONE gate (excerpt)."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path


def branch_tree(branch: str) -> Path | None:
    """The worktree that has `branch` checked out, so `mark_done` checks the review against that branch's HEAD."""
    try:
        return next((path for path, name in worktrees() if name == branch), None)
    except GitError:
        return None


def close(r: TaskState, url: str, branch: str) -> list[str]:
    """Append the PR, then run the DONE gate from the branch's worktree when one exists; its words are the output."""
    append_pr(r.task, url)
    lines = [f"record-pr: {r.slug}: recorded PR {url}"]
    out, saved = io.StringIO(), os.getcwd()
    tree = branch_tree(branch)
    try:
        if tree is not None:
            os.chdir(tree)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = mark_done(r.task, url, False)
    finally:
        os.chdir(saved)
    lines += [f"record-pr: {line}" for line in out.getvalue().splitlines() if line.strip()]
    if code != 0:
        lines.append(f"record-pr: {r.slug} stays {head(r)}; after fixing it run: {MARK_DONE.format(dir=r.task, url=url)}")
    return lines


def record(payload: dict, tasks_dir: Path, read: Reader = gh_read) -> list[str]:
    """Record the PR of one hook payload; the printed lines, empty when the payload is not a PR creation."""
    urls = created_urls(payload)
    if len(urls) != 1:
        return []
    saved, cwd = os.getcwd(), payload.get("cwd")
    try:
        if isinstance(cwd, str) and Path(cwd).is_dir():
            os.chdir(cwd)
        found = pull(urls[0], read)
        if found is None:
            return [f"record-pr: cannot read {urls[0]} with gh pr view; reconcile records it at the next session start"]
        return place(found, tasks_dir)
    finally:
        os.chdir(saved)
'''

GIT_LIB = '''"""Git reads used by the task tools (excerpt)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def worktrees(root: Path | None = None) -> list[tuple[Path, str]]:
    """`(path, branch)` for every worktree of the repository at `root`, default the current directory."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=root, capture_output=True, text=True,
                         timeout=10, check=True).stdout
    found, path = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[9:])
        elif line.startswith("branch refs/heads/") and path:
            found.append((path, line[18:]))
    return found
'''

case(id="record-pr-wrong-folder", lens="architecture",
     source="task B0334A9C, SPEC.md Summary item 2 (the DONE gate failed in use); code from commit 130353e",
     summary="The PR hook fires in whatever folder the Claude Code session runs (the payload `cwd`). After "
             "recording a PR on its task it runs the DONE gate, which checks that the latest review covers the "
             "HEAD of the current directory, so the hook first changes into the worktree that holds the PR's "
             "branch. Tasks live in `~/.agent/tasks` and record their repository's remote URL and the worktree "
             "they were implemented in (`.task-id` `worktree`).",
     defect="`branch_tree` lists the worktrees of the process cwd, which `record` set to the payload cwd: a "
            "session opened in another repository never finds the task's worktree, so the gate runs in the wrong "
            "folder and fails. The task's recorded worktree or repository is ignored.",
     files=[(".agent/tools/task/task_record_pr.py", None, RECORD_PR_CLOSE)],
     context={".agent/tools/lib/git.py": GIT_LIB},
     locations=[(".agent/tools/task/task_record_pr.py", "for path, name in worktrees() if name == branch"),
                (".agent/tools/task/task_record_pr.py", "os.chdir(cwd)")])

SHIP = '''"""`crew-task.py ship`: stage, commit, merge the base, re-run the spec's tests, push, open a draft PR (excerpt)."""
from __future__ import annotations

from pathlib import Path


def where_to(task: TaskState, tree: Path) -> tuple[str, str, str, str]:
    """(remote, base, target, head ref): a fork's PR targets `upstream`; the base is the spec's `## Base:` or the
    remote's default branch. Raises `Stop` when the target repository cannot be named."""
    remote = "upstream" if remote_url(tree, "upstream") else "origin"
    named = SPEC_BASE.search(task.text)
    base = named.group(1) if named else default_branch(tree, remote)
    target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
    if not target:
        raise Stop(f"cannot name the GitHub repository of '{remote}' or of the task")
    branch = current_branch(tree)
    if remote == "origin":
        return remote, base, target, branch
    owner = (slug_from_url(remote_url(tree, "origin")) or "").split("/")[0]
    return remote, base, target, f"{owner}:{branch}" if owner else branch


def prepare(task_dir: Path, title: str, body_file: Path) -> Ship | str:
    """The ship context, or why it cannot start (exit 2)."""
    task = load(task_dir)
    branch, recorded = task.meta.get("branch") or "", task.meta.get("worktree") or ""
    tree = Path(recorded) if recorded else None
    if tree is None or not tree.is_dir():
        return f"{name(task)}: the recorded worktree {recorded or '(none)'} is missing; run mark-implementing --root"
    actual = current_branch(tree)
    if not branch or actual != branch:
        return f"{name(task)}: {tree} is on {actual}, not the task's branch {branch or '(none recorded)'}"
    remote, base, target, head_ref = where_to(task, tree)
    return Ship(task, tree, branch, remote, base, target, head_ref, title, body_file)
'''

TASK_ID = '''{
  "uuid": "6F0C1D2E-0000-4000-8000-000000000001",
  "repo_remote_url": "git@github.com:acme/widgets.git",
  "slug": "widgets-retry-budget",
  "spec_branch": "main",
  "branch": "feat/retry-budget",
  "worktree": "/home/dev/worktrees/widgets-retry-budget",
  "base": "main",
  "created_at": "2026-11-20T10:00:00Z"
}
'''

case(id="ship-rederives-target", lens="architecture",
     source="task 1D001C12, review 20261127171102, consolidated finding (adversarial and code-quality)",
     summary="`crew-task.py ship <TASK_DIR>` commits, pushes and opens the task's draft PR in one step. Gate 2 "
             "(`mark-implementing`) records the task's repository (`repo_remote_url`), branch, worktree and base in "
             "`.task-id` (an example is in the working directory as `.task-id`); `ship` runs in that worktree "
             "and refuses when it is not on the task's branch.",
     defect="`where_to` re-derives remote, base and target from whatever remotes the worktree has (upstream "
            "first) and the default branch, instead of the values Gate 2 recorded, and never checks that the "
            "worktree's remote is the task's `repo_remote_url`: a stray `upstream` or a reused path sends the PR "
            "to another repository or base.",
     files=[(".agent/tools/task/task_ship.py", None, SHIP)],
     context={".task-id": TASK_ID},
     locations=[(".agent/tools/task/task_ship.py", 'remote = "upstream" if remote_url(tree, "upstream") else "origin"'),
                (".agent/tools/task/task_ship.py", "target = slug_from_url(remote_url(tree, remote))")])

# ---------------------------------------------------------------- product-flow

TUI_BEFORE = '''"""What the TUI shows and the moves it offers (excerpt)."""
from __future__ import annotations

FORCE_NOTE = "none (committed to main)"  # the `--pr-url` note of `mark-done --force` for a task with no PR
# The gates of `crew-task.py` and the one state each moves from; the CLI refuses any other.
GATES = (("mark-approved", "DRAFTING", "approve"), ("mark-implementing", "APPROVED", "start"),
         ("mark-done", "IMPLEMENTING", "mark done"))


def moves(state: str, task: Path, prs: list[str]) -> list[Move]:
    """The calls `crew-task.py` accepts from `state`: its gate (mark done with the newest PR, or `--force` and a
    note without one), and `blocked` with a reason for any task not DONE. The CLI still checks every gate."""
    found = []
    for command, source, label in GATES:
        if state != source:
            continue
        if command != "mark-done":
            found.append(Move(f"{label} ({command})", (command, str(task))))
        elif prs:
            found.append(Move(f"{label} with PR {prs[-1]} ({command})", (command, str(task), "--pr-url", prs[-1])))
        else:
            found.append(Move(f"{label} without a PR ({command} --force)", (command, str(task), "--force", "--pr-url"),
                              ask="note recorded as the PR", default=FORCE_NOTE))
    if state != "DONE":
        found.append(Move("blocked with a reason (blocked)", ("blocked", str(task)), ask="reason"))
    return found
'''

TUI_AFTER = '''"""What the TUI shows and the moves it offers (excerpt)."""
from __future__ import annotations

FORCE_NOTE = "closed: stale"  # the `--pr-url` note of the close move, `mark-done --force`
# The gates of `crew-task.py` and the one state each moves from; the CLI refuses any other.
GATES = (("mark-approved", "DRAFTING", "approve"), ("mark-implementing", "APPROVED", "start"),
         ("mark-done", "IMPLEMENTING", "mark done"))


def moves(state: str, task: Path, prs: list[str]) -> list[Move]:
    """The calls `crew-task.py` accepts from `state`: its gate (mark done with the newest PR from IMPLEMENTING),
    then, for any task not DONE, `blocked` with a reason and close as done (`mark-done --force` with a note), which
    an IMPLEMENTING task with a PR does not get. The CLI still checks every gate."""
    found = []
    for command, source, label in GATES:
        if state == source and (command != "mark-done" or prs):
            pr = ("--pr-url", prs[-1]) if command == "mark-done" else ()
            found.append(Move(f"{label}{f' with PR {prs[-1]}' if pr else ''} ({command})", (command, str(task), *pr)))
    if state != "DONE":
        found.append(Move("blocked with a reason (blocked)", ("blocked", str(task)), ask="reason"))
    if state != "DONE" and not (state == "IMPLEMENTING" and prs):
        found.append(Move("close as done (mark-done --force)", ("mark-done", str(task), "--force", "--pr-url"),
                          ask="note", default=FORCE_NOTE))
    return found
'''

case(id="tui-close-abandoned", lens="product-flow",
     source="task 285059E1, review 20261127153222, adversarial finding 1",
     summary="The task dashboard gains a \"close as done\" move for stale tasks: DRAFTING, APPROVED, ON-HOLD, or "
             "IMPLEMENTING without a PR. The owner picks it from a task row and types a short note. ABANDONED "
             "is a side state only the owner sets, meaning \"dropped, never to be finished\" (see "
             "`.agent/tools/task/task_status.py` in the working directory).",
     defect="The move is offered for every state but DONE, so an ABANDONED row also offers \"close as done\": one "
            "keypress turns the owner's \"abandoned\" decision into DONE, counted as finished work.",
     files=[("tui/tui_model.py", TUI_BEFORE, TUI_AFTER)],
     context={".agent/tools/task/task_status.py": TASK_STATUS},
     locations=[("tui/tui_model.py", 'if state != "DONE" and not (state == "IMPLEMENTING" and prs):')])

SHIP_STEPS = '''"""`crew-task.py ship`: each step records `SHIP: <step> <value>` and a re-run resumes (excerpt)."""
from __future__ import annotations

from pathlib import Path


def open_pr(ship: Ship) -> str:
    listed = gh("pr", "list", "--repo", ship.target, "--head", ship.branch, "--state", "open", "--json", "url",
                "--jq", ".[0].url // empty")
    existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
    if existing:
        print(f"ship: a PR is already open: {existing}")
        return existing
    created = gh("pr", "create", "--draft", "--title", ship.title, "--body-file", str(ship.body_file),
                 "--base", ship.base, "--repo", ship.target, "--head", ship.head_ref)
    url = pr_url(created.stdout)
    if created.returncode or not url:
        raise Stop(f"gh pr create failed: {(created.stderr or created.stdout).strip() or 'no PR URL printed'}")
    print(f"ship: opened {url}")
    return url


def push_holds(ship: Ship, _: str) -> bool:
    try:
        return rev_parse(ship.tree, f"refs/remotes/origin/{ship.branch}") == head_sha(ship.tree)
    except GitError:
        return False


STEP_RUNS = {"stage": stage, "commit": commit, "merge": merge, "test": test, "push": push, "pr": open_pr, "done": done}
STEP_HOLDS = {"stage": stage_holds, "commit": commit_holds, "merge": merge_holds, "test": test_holds,
              "push": push_holds, "pr": lambda _, value: bool(value), "done": done_holds}


def run(ship: Ship) -> int:
    """Re-check each recorded step in order; run from the first that is missing or no longer holds."""
    recorded = recorded_steps(ship.task.task)
    for step, action in STEP_RUNS.items():
        if step in recorded and STEP_HOLDS[step](ship, recorded[step]):
            print(f"ship: {step} already done ({recorded[step] or 'ok'})")
            continue
        value = action(ship)
        append_entry(ship.task.task, "SHIP", f"{step} {value}".strip())
    return 0
'''

case(id="ship-closed-pr-counts", lens="product-flow",
     source="task 1D001C12, review 20261127171102, consolidated finding (adversarial and code-quality)",
     summary="`crew-task.py ship` is the one command that ships a task: commit, merge the base, re-run the tests, "
             "push, open a draft PR, mark the task DONE. It is idempotent: after a stop the owner fixes the cause "
             "and runs `ship` again, and it continues from the first step that no longer holds, re-checking the "
             "earlier ones.",
     defect="The `pr` step holds whenever a URL was recorded: if the owner closed that PR (or it was merged) "
            "before the re-run, `ship` reports \"pr already done\" and marks the task DONE against a closed PR "
            "instead of opening a new one.",
     files=[(".agent/tools/task/task_ship.py", None, SHIP_STEPS)],
     locations=[(".agent/tools/task/task_ship.py", '"pr": lambda _, value: bool(value)')])

DOCTOR_CHECK_BEFORE = '''def check_mcp(home: Path, wanted: dict[str, list[str]] | None, cwd: Path, environ: dict[str, str]) -> list[Line]:
    """One line per capability (code search, docs) and Claude config dir: ok, or a WARN naming what is missing."""
    capabilities = [(label, set(wanted.get(key) or [])) for key, label in CAPABILITIES if wanted and wanted.get(key)]
    if not capabilities:
        return [Line("note", "mcp", MCP_HOWTO)]
    repo = repo_root(cwd)
    lines = []
    for directory, config_file in claude_files(home, environ):
        user, reach = available(read_object(config_file), read_object(directory / "settings.json"), repo)
        lines += [claude_capability(f"Claude Code {tilde(directory, home)}: {label} ({', '.join(sorted(names))})",
                                    names, user, reach) for label, names in capabilities]
    return lines
'''

DOCTOR_CHECK_AFTER = '''NONE_IN_DIR = "Claude Code {}: no configured MCP server is reachable from this config dir"


def check_mcp(home: Path, wanted: dict[str, list[str]] | None, cwd: Path, environ: dict[str, str]) -> list[Line]:
    """One line per capability (code search, docs) and Claude config dir: ok, or a WARN naming what is missing.
    A config dir that reaches none of the configured servers gets one note instead of a WARN per capability."""
    capabilities = [(label, set(wanted.get(key) or [])) for key, label in CAPABILITIES if wanted and wanted.get(key)]
    if not capabilities:
        return [Line("note", "mcp", MCP_HOWTO)]
    repo, remotes = repo_root(cwd), crew_remotes(home)
    configured = set().union(*(names for _, names in capabilities))
    lines = []
    for directory, config_file in claude_files(home, environ):
        settings = read_object(directory / "settings.json")
        plugins = plugin_servers(directory, settings, configured)
        user, reach = available(read_object(config_file), settings, repo, plugins, remotes)
        if not (user | set().union(*reach.values())) & configured:
            lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
            continue
        lines += [claude_capability(f"Claude Code {tilde(directory, home)}: {label} ({', '.join(sorted(names))})",
                                    names, user, reach) for label, names in capabilities]
    return lines
'''

case(id="doctor-none-is-a-note", lens="product-flow",
     source="task 2D916668, review 20261127143927, adversarial finding 5",
     summary="`crew doctor` checks that every agent can reach the owner's configured MCP servers (code search, "
             "docs) from each Claude Code config dir it finds; the owner runs it after install to learn whether "
             "agents will have those tools. `claude_files` returns the primary config dir (`~/.claude`, or "
             "`CLAUDE_CONFIG_DIR`) first, then any other config dir install covers. A WARN line makes `crew doctor` "
             "exit non-zero; a note does not.",
     defect="A config dir that reaches none of the configured servers is now only a note, even the primary "
            "config dir the owner works in: doctor exits 0 and the owner is never told the agents have no code "
            "search or docs.",
     files=[(".agent/tools/maintenance/doctor_mcp.py", DOCTOR_CHECK_BEFORE, DOCTOR_CHECK_AFTER)],
     locations=[(".agent/tools/maintenance/doctor_mcp.py", 'lines.append(Line("note", "mcp", NONE_IN_DIR')])

# ---------------------------------------------------------------- prompt-quality

LOOKUPS = '''# Lookups

How an agent finds code it cannot name and checks a product or API fact. Your own file still
sets your budget, your tools and where a note goes in your output; this file sets which lookup to
make and what to do when it cannot be made.

The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index,
`docs` for the docs server.

## Code you cannot locate

Search the code index before a text search: it ranks by relevance across whole repositories, so it
finds implementations you could not have guessed the words for. When you already know the file and
line, read it directly; the index is for discovery.

When the index is not in your tools, or a call fails, use the equivalent `Grep`/`Glob`/`Read` call and
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end. The reader needs it to know the
results were not ranked.

## Product and API facts

Any claim about product, API, query-language or configuration behaviour that your work depends on
(writing it, reviewing it, or answering a comment about it) is checked on the docs server and cited
by URL. Search the docs (`search_internal_docs`), then fetch the page you cite. Never settle such a
claim from memory: a guessed option reads the same as a verified one.

With no docs server in your tools, or a failed lookup, mark the claim
`unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or
memory.
'''

CONTRACT_BEFORE = '''# Shared reviewer contract

Your persona file sets your lens; this file sets your output.

## Evidence

Search the code index before reaching for a text search: it finds implementations you could not
have guessed the words for. When the index is unreachable, say `code search unreachable: used text
search` on the line after your `Assessment:` line.

## Product facts (opt-in: applies when the package says the artifact has content for the docs server's product)

Check a claim about that product's API or configuration on the docs server and cite the page.

## Labels

Exactly one label per finding: `[blocking]`, `[attention]`, `[needs more info]`, `[nit]`.
'''

CONTRACT_AFTER = '''# Shared reviewer contract

Your persona file sets your lens; this file sets your output.

## Evidence

Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
Its `code search unreachable` line goes on the line after your `Assessment:` line.

## Labels

Exactly one label per finding: `[blocking]`, `[attention]`, `[needs more info]`, `[nit]`.
'''

ROUTER_BEFORE = '''# Crew router

Every main session in every repository loads this rule.

## Routing

| Request | Route |
| --- | --- |
| `crew spec` | crew-specwriter |
| `crew implement` | crew-implement |
| `crew review` | crew-reviewer |
'''

ROUTER_AFTER = '''# Crew router

Every main session in every repository loads this rule.

Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.

## Routing

| Request | Route |
| --- | --- |
| `crew spec` | crew-specwriter |
| `crew implement` | crew-implement |
| `crew review` | crew-reviewer |
'''

case(id="lookups-docs-scope", lens="prompt-quality",
     source="task 2D916668, review 20261127143927, prompt-quality finding 1 (vendor names neutralised)",
     summary="Lookup guidance for the code index and the docs server moves into one shared reference, "
             "`lookups.md`, and every agent gets a one-line pointer to it: the reviewer contract and the "
             "always-loaded router rule (every main session, every repository, builders included). The docs "
             "server configured today indexes one vendor's product documentation.",
     defect="The docs rule was opt-in, for artifacts with the docs server's product; it now applies to every "
            "product or API claim in every project for every agent, writers included. A claim about an "
            "unrelated library finds no page and is marked `unverified (docs server unreachable)`, though the "
            "server answered; the rule never says which products it covers.",
     files=[(".cursor/agents/references/lookups.md", None, LOOKUPS),
            (".cursor/agents/references/reviewer-contract.md", CONTRACT_BEFORE, CONTRACT_AFTER),
            ("rules/crew-router.mdc", ROUTER_BEFORE, ROUTER_AFTER)],
     locations=[(".cursor/agents/references/lookups.md", "Any claim about product, API, query-language"),
                (".cursor/agents/references/lookups.md", "`unverified (docs server unreachable)`")])

case(id="lookups-pointer-too-late", lens="prompt-quality",
     source="task 2D916668, review 20261127143927, prompt-quality finding 4",
     summary="Lookup guidance for the code index and the docs server moves into one shared reference, "
             "`lookups.md`, and the reviewer contract keeps a one-line pointer to it instead of its own copy. "
             "The intent is unchanged: an agent searches the code index before a text search.",
     defect="The pointer fires only \"when you need code you cannot locate\", which reads as after a search "
            "failed: an agent that greps first and gets a hit never opens lookups.md, so the index-first rule the "
            "contract used to state unconditionally never applies.",
     files=[(".cursor/agents/references/lookups.md", None, LOOKUPS),
            (".cursor/agents/references/reviewer-contract.md", CONTRACT_BEFORE, CONTRACT_AFTER)],
     locations=[(".cursor/agents/references/reviewer-contract.md", "Lookups: follow"),
                (".cursor/agents/references/lookups.md", "Search the code index before a text search")])

CRITIC_BEFORE = '''# Spec critic contract

`crew-specwriter` appends this file to the dispatch prompt of each spec critic. The critic's own file sets
its lens; this file sets evidence, budget and output.

## Evidence

Verify the spec's claims against the codebase, and flag a claim you could not verify instead of
assuming it.

## Output

Group findings by severity (**Critical**, **Important**, **Consider**), omitting an empty level. At most 5
findings across all levels.

**End with one outcome line.** `Verdict: N finding(s)` after the findings, and `Verdict: 0 finding(s)` for a
clean pass. The specwriter cannot tell a budget stop from a clean pass, so a reply whose last line is not
the Verdict line is treated as incomplete, not as approval.
'''

CRITIC_AFTER = '''# Spec critic contract

`crew-specwriter` appends this file to the dispatch prompt of each spec critic. The critic's own file sets
its lens; this file sets evidence, budget and output.

## Evidence

Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.

Verify the spec's claims against the codebase, and flag a claim you could not verify instead of
assuming it.

## Output

Group findings by severity (**Critical**, **Important**, **Consider**), omitting an empty level. At most 5
findings across all levels.

**End with one outcome line.** `Verdict: N finding(s)` after the findings, and `Verdict: 0 finding(s)` for a
clean pass. The specwriter cannot tell a budget stop from a clean pass, so a reply whose last line is not
the Verdict line is treated as incomplete, not as approval.
'''

case(id="lookups-critic-verdict", lens="prompt-quality",
     source="task 2D916668, review 20261127143927, prompt-quality finding 3",
     summary="Lookup guidance moves into one shared reference, `lookups.md`; the spec critic contract, which "
             "`crew-specwriter` appends to every critic dispatch, gains the one-line pointer to it.",
     defect="lookups.md puts the `code search unreachable` line \"at the end\" when the agent's file names no "
            "place, and the critic contract names none: a critic that follows it ends after its `Verdict:` line, "
            "so the specwriter treats a complete critique as incomplete.",
     files=[(".cursor/agents/references/lookups.md", None, LOOKUPS),
            (".cursor/agents/references/critic-contract.md", CRITIC_BEFORE, CRITIC_AFTER)],
     locations=[(".cursor/agents/references/lookups.md", "without such a place, put it at the end"),
                (".cursor/agents/references/critic-contract.md", "Lookups: follow"),
                (".cursor/agents/references/critic-contract.md", "**End with one outcome line.**")])

# ---------------------------------------------------------------- specwriter-adversarial (hand-seeded specs)

SPEC_FORCE = '''# Spec: close any stale task as done

## Type: feature
## Branch: feat/close-stale
## Status
DRAFTING

## Summary
Stale tasks clutter `crew ls`: specs that were drafted and never approved, approved work that was
dropped, and tasks implemented with no PR. Today `crew-task.py mark-done --force` only works from
IMPLEMENTING. Let the owner close any of them as done, from the CLI and from the TUI.

Gate 1 (`mark-approved`) is the owner's approval of a spec; only an APPROVED spec may be implemented,
and a DONE task with a PR is read as shipped, approved work. ABANDONED is a side state only the owner
sets.

## Acceptance criteria
- [ ] `mark-done --force --pr-url <value>` closes a task in any state but DONE as DONE. The value is
      logged in PROGRESS.md as the reason; a GitHub PR URL is also added to the task's PR list.
- [ ] The TUI offers "close as done" on every row that is not DONE, with a note prompt.
- [ ] A forced close ends an open BLOCKED line.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_lifecycle.py`

## Tasks
- [ ] Task 1: relax the state check in `.agent/tools/task/task_gates.py` `mark_done` under `--force`.
- [ ] Task 2: add the close move to `tui/tui_model.py` `moves`.
- [ ] Task 3: add rows to `evals/tools/test_lifecycle.py` and `evals/tools/test_tui_model.py`.
'''

case(id="spec-force-any-state", lens="specwriter-adversarial", kind="spec", hand_seeded=True,
     source="hand-seeded from task 285059E1 (its review's findings 1 and 2), reduced to a spec",
     summary="A spec for closing stale tasks as done from the CLI and the TUI.",
     defect="\"Any state but DONE\" lets `--force` with a real PR URL close a DRAFTING or APPROVED spec as shipped "
            "work that skipped Gate 1, and turns the owner's ABANDONED into DONE; no criterion restricts the "
            "states or the value.",
     spec=SPEC_FORCE,
     locations=[("SPEC.md", "closes a task in any state but DONE as DONE")],
     refs=["any state but DONE", "criterion 1", "AC 1", "AC1"])

SPEC_TIMEOUT = '''# Spec: tests cannot hang unnoticed

## Type: chore
## Branch: fix/test-timeout
## Status
DRAFTING

## Summary
A hung test ran for 23 minutes before anyone noticed; `evals/test.sh` has no per-test timeout. The suite
holds fast unit rows and a few end-to-end rows: the install and upgrade tests run the real `install.sh`
against a temporary HOME and allow themselves up to 300 s with their own `subprocess` timeouts, since a
cold CI runner is slow.

## Acceptance criteria
- [ ] `evals/test.sh` runs pytest with `pytest-timeout` (pinned like `pytest-xdist`) and a per-test
      timeout of 60 s for every test.
- [ ] A deliberately sleeping fixture fails within the timeout with the test's name in the output.

## Tests
### Unit
- **Command**: `bash evals/test.sh -n auto`

## Tasks
- [ ] Task 1: pin `pytest-timeout` and pass `--timeout 60` in `evals/test.sh`.
- [ ] Task 2: add the sleeping fixture to `evals/tools/test_hang_guards.py`.
'''

case(id="spec-timeout-cuts-install", lens="specwriter-adversarial", kind="spec", hand_seeded=True,
     source="hand-seeded from task 1D001C12 (review 20261127163032, adversarial finding on evals/test.sh)",
     summary="A spec that adds a per-test timeout to the test runner.",
     defect="A blanket 60 s per-test limit kills the install and upgrade tests the summary says need up to 300 s, "
            "so the suite fails on a slow runner; the criteria name no exemption or per-test override.",
     spec=SPEC_TIMEOUT,
     locations=[("SPEC.md", "timeout of 60 s for every test")],
     refs=["60 s", "criterion 1", "AC 1", "AC1"])

SPEC_TASKS_DIR = '''# Spec: crew agents write task files without prompting

## Type: chore
## Branch: fix/task-dir-permissions
## Status
DRAFTING

## Summary
Background builders run with no one to answer a permission prompt, and every write under
`~/.agent/tasks` (PROGRESS.md, REPORT.md, checkbox ticks in SPEC.md) prompts today, so builders stall.

The task directory also holds what the gates trust: the `## Status` line of SPEC.md (Gate 1 is the
owner moving it to APPROVED through `crew-task.py mark-approved`), `.task-id` (which task owns the
spec) and the review evidence files under `review/` (`*.expect` nonces, saved replies).

## Acceptance criteria
- [ ] Install adds `Edit(~/.agent/tasks/**)` and `Write(~/.agent/tasks/**)` to the allow list and
      `~/.agent/tasks` to `additionalDirectories`, and removes the old ask rule for task SPEC.md files.
- [ ] A background builder ticks a SPEC.md checkbox and appends to PROGRESS.md with no prompt.
- [ ] Uninstall removes exactly the entries install added.

## Tests
### Integration
- **Command**: `bash .claude/hooks/fixtures/install.sh`

## Tasks
- [ ] Task 1: add the allow rules and the directory in `.claude/merge_claude_settings.py`.
- [ ] Task 2: add fixture rows to `.claude/hooks/fixtures/install.sh`.
'''

case(id="spec-tasks-dir-unguarded", lens="specwriter-adversarial", kind="spec", hand_seeded=True,
     source="hand-seeded from task 82FCCD58 (review 20261127141048, adversarial findings 1 and 4), reduced to a spec",
     summary="A spec that lets background agents write task files without a permission prompt.",
     defect="Allowing every write under the task directory and dropping the SPEC.md ask rule leaves nothing that "
            "stops an agent from editing the `## Status` line to APPROVED (skipping Gate 1) or rewriting "
            "`.task-id` and review evidence; no criterion keeps those guarded.",
     spec=SPEC_TASKS_DIR,
     locations=[("SPEC.md", "Install adds `Edit(~/.agent/tasks/**)`")],
     refs=["criterion 1", "AC 1", "AC1", "allow list", "allow rule"])

# ---------------------------------------------------------------- specwriter-scope (hand-seeded specs)

SPEC_WIDE = '''# Spec: notify when a background job goes idle

## Type: feature
## Branch: feat/idle-notify
## Status
DRAFTING

## Summary
The owner misses background jobs that finish or wait for input. Show a desktop notification when a job
goes idle, at most once a minute, with an off switch.

## Acceptance criteria
- [ ] An idle job shows one notification naming the job; a second within 60 s shows nothing.
- [ ] `EL_CAPITAN_NOTIFY=0` turns it off.
- [ ] The hook never blocks the session: it exits 0 on every path.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_hook_cases.py`

## Tasks
- [ ] Task 1: add the rate-limit stamp helper to `.claude/hooks/lib/hook.sh`.
- [ ] Task 2: write `.claude/hooks/notify-idle.sh`, register it in `.claude/settings.json` and
      `.cursor/hooks.template.json`, add its install entry to `.claude/merge_claude_settings.py`, document it in
      `docs/hooks.md` and `README.md`, and add its rows to `evals/tools/hook_cases.py`.
- [ ] Task 3: add the off switch to `docs/hooks.md`.
'''

case(id="spec-task-too-wide", lens="specwriter-scope", kind="spec", hand_seeded=True,
     source="hand-seeded, modelled on task 82FCCD58's notify-idle work",
     summary="A spec for a desktop notification when a background job goes idle.",
     defect="Task 2 touches seven files across the hook, two hook configs, install, two docs and the test rows: "
            "too wide for one builder task with one verify line, and it overlaps Task 3 on docs/hooks.md.",
     spec=SPEC_WIDE,
     locations=[("SPEC.md", "- [ ] Task 2: write `.claude/hooks/notify-idle.sh`")],
     refs=["Task 2", "T2"])

SPEC_ORDER = '''# Spec: record-pr matches tasks by repository slug

## Type: bugfix
## Branch: fix/record-pr-slug
## Status
DRAFTING

## Summary
`record-pr` compares a task's `repo_remote_url` with the PR's repository as raw strings, so an ssh remote
never matches an https URL. Compare normalised `owner/name` slugs instead.

## Acceptance criteria
- [ ] A task with `git@github.com:acme/widgets.git` matches a PR of `https://github.com/acme/widgets`.
- [ ] `.git` suffixes and letter case do not matter.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_lifecycle.py`

## Tasks
- [ ] Task 1: in `.agent/tools/task/task_record_pr.py` `tasks_in`, compare `slug_from_url(r.meta["repo_remote_url"])`
      with each PR repository. Verify: `bash evals/test.sh evals/tools/test_lifecycle.py -k record_pr`
- [ ] Task 2: add rows for ssh, https, `.git` and case to `evals/tools/test_lifecycle.py`.
- [ ] Task 3: add `slug_from_url(url) -> str | None` to `.agent/tools/lib/git.py` (ssh, https, `.git`, case).
'''

case(id="spec-task-order", lens="specwriter-scope", kind="spec", hand_seeded=True,
     source="hand-seeded, modelled on task B0334A9C's remote comparison",
     summary="A spec that makes record-pr compare repositories by normalised slug.",
     defect="Task 1 calls `slug_from_url`, which only Task 3 creates, and runs its verify line before then: the "
            "builder's sequential loop fails Task 1. Task 3 must come first.",
     spec=SPEC_ORDER,
     locations=[("SPEC.md", "- [ ] Task 1: in `.agent/tools/task/task_record_pr.py`"),
                ("SPEC.md", "- [ ] Task 3: add `slug_from_url(url)")],
     refs=["Task 1", "T1", "Task 3", "T3"])

SPEC_VERIFY = '''# Spec: open the PR from crew-task

## Type: feature
## Branch: feat/open-pr
## Status
DRAFTING

## Summary
Opening a PR is four manual steps. Add `crew-task.py open-pr <TASK_DIR>`: push the branch and open a draft
PR with `gh`, then record it on the task.

## Acceptance criteria
- [ ] `open-pr` pushes the task's branch and opens a draft PR against the base branch.
- [ ] The PR URL is appended to the task's PR list.
- [ ] Re-running it on a task whose PR is open prints the existing URL and opens nothing.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_open_pr.py`

## Tasks
- [ ] Task 1: add `.agent/tools/task/task_open_pr.py` and the `open-pr` subcommand in `crew-task.py`.
- [ ] Task 2: add `evals/tools/test_open_pr.py` with rows for the happy path and the re-run.
- [ ] Task 3: check it end to end. Verify: run `crew-task.py open-pr` on a scratch task in this repository,
      confirm the draft PR appears on github.com, then close it by hand.
'''

case(id="spec-verify-not-runnable", lens="specwriter-scope", kind="spec", hand_seeded=True,
     source="hand-seeded, modelled on task 1D001C12's ship command",
     summary="A spec that adds a command to push and open a draft PR for a task.",
     defect="Task 3's verify pushes to the real repository, opens a real PR on github.com and needs a manual "
            "close: the builder cannot run it hermetically, it has external side effects, and it is not a "
            "command with a pass or fail.",
     spec=SPEC_VERIFY,
     locations=[("SPEC.md", "- [ ] Task 3: check it end to end.")],
     refs=["Task 3", "T3"])


# ---------------------------------------------------------------- keywords
# Matched against the finding's prose with code spans and fences removed, so each group names the defect in words
# a reviewer writes outside backticks. No group may hold a word that fits any finding (`score.GENERIC_TERMS`);
# a spec case adds a second group naming the specific thing, since its location is only a task or criterion.

KEYWORDS = {
    "status-guard-cr-heading": [["carriage return*", "CR", "CRLF", "lone CR"],
                                ["heading*", "awk", "reader*", "parser", "parses", "regex*", "re-implement*"]],
    "status-guard-second-section": [["blank line*", "empty line*", "non-blank", "second", "duplicate*",
                                     "more than one", "multiple", "two Status"], ["heading*", "section*"]],
    "status-guard-lone-cr": [["universal newline*", "lone CR", "lone carriage", "carriage return*", "bare CR"],
                             ["newline*", "raw", "read_text", "reader*"]],
    "status-guard-path-case": [["case-insensitive*", "case insensitive*", "lowercase", "lower-case", "lower case",
                                "realpath", "normali*", "APFS", "symlink*", "canonical path*", "dot-dot",
                                "double slash"]],
    "force-before-approval": [["approv*", "gate 1", "drafting", "unapproved"]],
    "record-pr-duplicate": [["duplicate*", "second task", "new task", "minimal task", "another task",
                             "extra task", "two tasks"]],
    "doctor-plugin-prefix": [["prefix*"],
                             ["underscore*", "ambiguous*", "another plugin", "other plugin", "wrong plugin",
                              "collision*", "collide*", "different plugin"]],
    "lint-budget-allowlist": [["new persona", "new agent", "new reviewer", "new critic", "added persona",
                               "adds a persona", "remember*", "forget*", "forgot*", "exempt*", "opt-in", "opt in",
                               "hand-maintained", "hardcoded", "hard-coded", "allowlist"]],
    "test-pins-prose": [["prose", "wording", "sentence*", "reflow*", "exact text", "exact string", "whitespace",
                         "indentation", "line break*", "line wrap*", "rewrap*"]],
    "install-prune-user-folders": [["empty"],
                                   ["user*", "by hand", "unrelated", "not pruned", "never created",
                                    "did not create", "didn't create", "install never owned", "not install's"]],
    "record-pr-wrong-folder": [["cwd", "working directory", "current directory", "session*", "another repo*",
                                "other repo*", "different repo*", "wrong folder", "wrong directory", "wrong repo*",
                                "recorded worktree"]],
    "ship-rederives-target": [["recorded", "task's repo*", "gate 2", "source of truth", "re-deriv*", "rederiv*",
                               "deriv*"], ["remote*", "upstream", "base", "target*"]],
    "tui-close-abandoned": [["abandon*"]],
    "ship-closed-pr-counts": [["closed", "merged"]],
    "doctor-none-is-a-note": [["note*"], ["warn*", "primary", "silent*", "exit code", "exits 0", "never told",
                                          "not told", "hidden", "hides", "downgrad*"]],
    "lookups-docs-scope": [["every product", "all products", "any product", "scope*", "widen*", "every project",
                            "every repo*", "opt-in", "opt in", "librar*", "third-party", "no page", "not cover*",
                            "doesn't cover", "does not cover", "other vendor*", "one vendor", "unrelated"]],
    "lookups-pointer-too-late": [["cannot locate", "can't locate", "trigger*", "fires", "too late",
                                  "after a failed", "after failing", "never fire*", "never appl*", "never read*",
                                  "never open*", "already found", "gets a hit"], ["index*"]],
    "lookups-critic-verdict": [["verdict"], ["last line", "final line", "at the end", "ends", "end of", "after the",
                                             "last"]],
    "spec-force-any-state": [["approv*", "gate 1", "drafting", "abandon*", "unapproved"],
                             ["force*", "close as done", "any state"]],
    "spec-timeout-cuts-install": [["install*", "upgrade*", "300", "end-to-end", "slow*", "long-running",
                                   "legitimate*"], ["timeout*", "time limit", "60 s", "60s", "60-second"]],
    "spec-tasks-dir-unguarded": [["Status line", "Status value", "approv*", "gate 1", "task-id", "expect file*",
                                  "evidence"], ["allow*", "ask rule", "no prompt", "without a prompt"]],
    "spec-task-too-wide": [["seven", "7 files", "too many", "wide*", "split*", "too large", "too big", "granular*",
                            "many files"], ["Task 2", "notify-idle*"]],
    "spec-task-order": [["order*", "depend*", "reorder*", "doesn't exist", "does not exist", "undefined", "sequen*",
                         "only Task 3", "created in Task 3", "added in Task 3", "move Task 3"],
                        ["slug_from_url", "helper"]],
    "spec-verify-not-runnable": [["network", "github.com", "real PR", "real repo*", "manual*", "by hand",
                                  "side effect*", "hermetic*", "stub*", "cannot run", "can't run", "not runnable",
                                  "credential*", "auth*"], ["verif*", "end to end", "end-to-end", "Task 3"]],
}


# ---------------------------------------------------------------- writer

def git_diff(path: str, before: str | None, after: str) -> str:
    """One file's diff in git's shape, so the persona reads what a real review sends."""
    old =[] if before is None else before.splitlines(keepends=True)
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
        if kind == "diff":
            diff = "".join(git_diff(p, b, a) for p, b, a in c["files"])
            (directory / "change.diff").write_text(diff, encoding="utf-8")
            texts.update({p: a for p, _, a in c["files"]})
        else:
            (directory / "spec.md").write_text(c["spec"], encoding="utf-8")
            texts["SPEC.md"] = c["spec"]
        locations = [{"file": f, "line": line_of(texts[f], needle, c["id"])} for f, needle in c["locations"]]
        record = {"id": c["id"], "lens": c["lens"], "kind": kind, "hand_seeded": c.get("hand_seeded", False),
                  "source": c["source"], "summary": c["summary"], "defect": c["defect"],
                  "locations": locations, "refs": c.get("refs", []), "keywords": KEYWORDS[c["id"]],
                  "context": c.get("context") or {},
                  "after": {p: a for p, _, a in c.get("files", [])}}
        (directory / "case.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(CASES)} cases written to {out}")


if __name__ == "__main__":
    main()
