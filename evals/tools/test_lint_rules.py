#!/usr/bin/env python3
"""crew-lint's rules, each made to fire on a seeded violation and stay quiet on its fix.

That the real tree reports nothing is CI's own `crew-lint.py --budget` step. One temp copy of `.agent/tools` carries every seeded Python and
removed-form violation at once, each in its own file, and must report each rule at its path; small
fixture roots hold one agent, rule, catalog or handoff shape each. Every reported rule is registered
and `--list-rules` prints them all. Lint runs in this process. Generic Python style is Ruff's.
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cli_runner import load
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
LINT_PATH = TOOLS / "maintenance" / "crew-lint.py"
LINT = load(LINT_PATH)
from lint_prompts import READONLY_AGENT_DENY  # noqa: E402
from lint_references import lint_handoff  # noqa: E402
from lint_writing import lint_local_state_tracked  # noqa: E402

FAILED: list[str] = []
# (case, rule, file under .agent/tools, text appended to it: a new file starts empty)
SEEDED = (
    ("git-argv", "direct-git", "task/task_seeded_git.py", "ARGV = [\"git\", \"status\"]\n"),
    ("long-module", "module-size", "task/task_seeded_long.py", "X = 1\n" * 401),
    ("second-atomic-write", "single-owner", "task/task_seeded_atomic.py", "def atomic_write() -> None:\n    pass\n"),
    ("systemexit-message", "no-systemexit-str", "task/task_seeded_exit.py", "raise SystemExit(f'bad: {1}')\n"),
    ("task-imports-review", "package-direction", "task/task_seeded_import.py", "import review_pr_reads\n"),
    ("lib-imports-task", "package-direction", "lib/seeded.py", "def later() -> None:\n    from task_progress import read_text\n"),
    ("memory-imports-maintenance", "package-direction", "memory/memory_seeded.py", "from lint_files import rel\n"),
    ("second-read-json", "single-owner", "review/review_seeded_json.py", "def read_json_object() -> None:\n    pass\n"),
    ("progress-append", "single-owner", "task/task_seeded_progress.py", "from pathlib import Path\n\nPath('t', 'PROGRESS.md').open('a').write('x')\n"),
    ("slug-regex", "single-owner", "task/task_seeded_slug.py", "import re\n\nSLUG = re.compile(r'[:/]([^/:]+)/([^/]+?)(?:\\.git)?$')\n"),
    ("removed-verify-form", "removed-command-form", "task/task_seeded_verify.py", "USAGE = 'crew-progress.py verify --repo .'\n"),
    ("removed-mark-flag", "removed-command-form", "TOOLS.md", "\nRun `crew-ls.py --mark-done \"$TASK_DIR\"`.\n"),
    ("removed-wrapped-form", "removed-command-form", "TOOLS.md", "\napplied by `crew-ls.py --reconcile\n--apply`.\n"),
    ("removed-flag-form", "removed-command-form", "TOOLS.md", "\nRun `crew-verify.py --wait out.json --since 1`.\n"),
    ("removed-form-in-eval-task", "removed-command-form", "../../evals/tasks.json", '{"d": "run `crew-ls.py --mark-done x`"}\n'),
    ("removed-form-in-workflow", "removed-command-form", "../../.github/workflows/seeded.yml", "run: python3 .agent/tools/task/crew-next.py --stages\n"),
    ("long-docstring", "docstring-length", "task/task_seeded_doc.py", '"""One.\n\n2\n3\n4\n5\n6\n7\n"""\n'),
    ("narrated-comment", "no-incident-narration", "task/task_seeded_story.py", "X = 1  # this used to crash\n"),
    ("measured-docstring", "no-incident-narration", "review/review_seeded_story.py", '"""A reader: measured over 9 runs, 3 of 9 failed."""\n'),
    ("bootstrap-drift", "bootstrap-identical", "task/task_bootstrap.py", "EXTRA = 1\n"),
    ("sibling-run", "no-sibling-subprocess", "task/task_seeded_sibling.py", "import subprocess\n\nsubprocess.run(['python3', 'crew-ls.py'])\n"),
    ("sibling-path", "no-sibling-subprocess", "review/review_seeded_sibling.py",
     "import subprocess\nfrom pathlib import Path\n\nTOOL = Path(__file__).with_name('crew-pr-actions.py')\nsubprocess.run([TOOL, 'pr'])\n"),
)
CATALOG = {"schema_version": 1, "tools": [], "scripts": [], "modules": [], "assets": [],
           "mcp_servers": {"sourcerer": ["sourcerer_code_search", "sourcerer_code_grep"]}, "native_tools": ["Glob", "Grep", "Read"]}
DENY_ALL = f"readonly: true\ndisallowedTools: {', '.join(READONLY_AGENT_DENY)}\n"


def agent(name: str, frontmatter: str, body: str = "Body.\n") -> tuple[str, str]:
    return f".cursor/agents/{name}.md", f"---\nname: {name}\ndescription: \"Fixture agent.\"\n{frontmatter}---\n{body}"


def missing_one(index: int) -> tuple[str, str]:
    rest = ", ".join(item for item in READONLY_AGENT_DENY if item != READONLY_AGENT_DENY[index])
    return agent(f"reviewer-missing-{index}", f"readonly: true\ndisallowedTools: {rest}\n")


# (case, files, {rule: findings expected}): a rule absent from the map must not fire at all.
FIXTURES = (
    ("declared native ids only", dict([agent("reviewer-a", DENY_ALL + "tools: Read, Grep, Glob\n")]), {}),
    ("an MCP id granted in tools:", dict([agent("reviewer-a", DENY_ALL + "tools: Read, mcp__sourcerer__sourcerer_code_search\n")]), {"mcp-grant-policy": 1}),
    ("an undeclared MCP server", dict([agent("reviewer-a", DENY_ALL + "tools: Read, mcp__elastic-docs__search_docs\n")]),
     {"mcp-tool-unknown": 1, "mcp-grant-policy": 1}),
    ("an undeclared tool on a declared server", dict([agent("reviewer-a", DENY_ALL + "tools: Read, mcp__sourcerer__bogus\n")]),
     {"mcp-tool-unknown": 1, "mcp-grant-policy": 1}),
    ("an undeclared native tool id", dict([agent("reviewer-a", DENY_ALL + "tools: Read, SemanticSearch\n")]), {"tool-id-unknown": 1}),
    ("an MCP id in agent prose is not a grant", dict([agent("reviewer-a", DENY_ALL + "tools: Read\n", "Use mcp__sourcerer__sourcerer_code_search.\n")]), {}),
    ("an unknown MCP id in rule prose", {"rules/fixture.mdc": "---\ndescription: \"Fixture rule\"\nalwaysApply: false\n---\nUse mcp__retired-server__old_tool.\n"},
     {"mcp-tool-unknown": 1}),
    ("a malformed mcp_servers catalog", {".agent/tools/tools.json": json.dumps({**CATALOG, "mcp_servers": "sourcerer"})}, {"invalid-tool-catalog": 1}),
    ("a catalog with no native_tools list", {".agent/tools/tools.json": json.dumps({k: v for k, v in CATALOG.items() if k != "native_tools"})},
     {"invalid-tool-catalog": 1}),
    ("a read-only agent without the flag", dict([agent("reviewer-a", "tools: Read\n")]), {"missing-readonly": 1}),
    ("readonly: false is not a declaration", dict([agent("reviewer-a", "readonly: false\n")]), {"missing-readonly": 1}),
    ("the resolver analysis must declare readonly", dict([agent("crew-pr-resolver", "tools: Read\n")]), {"missing-readonly": 1}),
    ("a worker that declares readonly", dict([agent("crew-builder", "readonly: true\n")]), {"unexpected-readonly": 1}),
    ("exempt writers and orchestrators write freely", dict([agent("crew-builder", ""), agent("crew-reviewer", ""), agent("crew-specwriter", "")]), {}),
    ("an inheriting read-only agent missing any deny entry, or all of them",
     dict([agent("reviewer-open", "readonly: true\n"), agent("reviewer-denied", DENY_ALL), *map(missing_one, range(len(READONLY_AGENT_DENY)))]),
     {"inherited-tools-can-write": len(READONLY_AGENT_DENY) + 1}),
    ("a broken frontmatter is its own finding, not a missing flag",
     {".cursor/agents/reviewer-broken.md": "---\nname: reviewer-broken\ndescription: \"Fixture agent.\"\nBody.\n"}, {"invalid-agent-frontmatter": 1}),
    ("an unprefixed command", {".agent/tools/task/task-progress.py": "#!/usr/bin/env python3\n", ".agent/tools/tools.json": json.dumps({**CATALOG, "tools": [
        {"name": "task-progress.py", "dir": "task", "kind": "command", "category": "task", "owner": "crew-orchestrator", "help": "argparse", "smoke": "--help"}]})},
     {"command-name": 1}),
    ("removed forms in both hook registries and three removed paths",
     {".claude/settings.json": '{"hooks": {"SessionEnd": [{"command": "bash ~/.claude/hooks/session-event.sh end"}]}}\n',
      ".cursor/hooks.template.json": '{"hooks": {"stop": [{"command": "crew-prune.py --tasks-dir x"}]}}\n',
      ".agent/tools/TOOLS.md": "Run `bash .claude/hooks/fixtures/run.sh` and `python3 evals/tools/test_hooks_contract.py`.\n"},
     {"removed-command-form": 4}),
    ("a removed flag after another command is not the command's", {".agent/tools/TOOLS.md": "Run crew-verify.py and git log --since 1d.\n"}, {}),
)
FIXTURE_RULES = {"mcp-grant-policy", "mcp-tool-unknown", "tool-id-unknown", "missing-readonly", "unexpected-readonly",
                 "inherited-tools-can-write", "invalid-agent-frontmatter", "invalid-tool-catalog", "command-name", "removed-command-form"}
ROUTER = ("# Router\n\n| Trigger | Crew member |\n|---|---|\n| `crew review` | crew-reviewer |\n| `crew commit` | crew-commit |\n"
          "| `crew implement` | crew-builder |\n| `crew check` | crew-check |\n| `crew review address` | crew-address-review skill |\n")
SKILL = ".cursor/skills/{}/SKILL.md"
NEXT = "Prose.\n\n> Next: run `crew {}` to continue.\n"
# (case, files, the handoff rule that must fire, or None for none at all)
HANDOFFS = (
    ("a conforming trailer", {SKILL.format("crew-commit"): NEXT.format("commit")}, None),
    ("two trailers", {SKILL.format("crew-commit"): "> Next: run `crew commit` to continue.\n\nMore.\n\n> Next: run `crew review` to continue.\n"},
     "handoff-multiple-trailers"),
    ("a trailer that is not last", {SKILL.format("crew-commit"): "> Next: run `crew commit` to continue.\n\n## Later\n\nMore prose.\n"},
     "handoff-trailer-not-last"),
    ("quoted per-outcome lines", {SKILL.format("crew-check"): "- If PASS: print `> Next: run \\`crew review\\` to continue.`\n"
                                  + "".join(f"- Branch {i}: `> Next: run \\`crew review\\` to verify.`\n" for i in range(4))}, None),
    ("a bare Next: in a trailerless file", {".cursor/agents/reviewer-adversarial.md": "## Method\n\n1. Read.\n2. Next: check the error paths.\n"},
     "handoff-stray-next"),
    ("the PR paste exception", {SKILL.format("crew-review"): "Prose.\n\n> Next: paste the bodies from `comments.md` onto PR #12; nothing was posted.\n"}, None),
    ("a non-crew next step", {SKILL.format("crew-commit"): "Prose.\n\n> Next: ask the user what they think.\n"}, "handoff-no-command"),
    ("trailerless files and a fenced example", {SKILL.format("crew-log"): "Print this:\n\n```text\n> Next: run `crew commit` to continue.\n```\n",
                                                ".cursor/agents/reviewer-architecture.md": "## Method\n\nJudge the boundaries.\n"}, None),
    ("a reason beside the command", {".cursor/agents/crew-reviewer/references/output-formats.md":
                                     "- A self-review ends with `Next: run \\`crew commit\\` to continue.`\n"}, None),
    ("an indented second handoff", {SKILL.format("crew-implement"): "3. Tell the user:\n   > Next: run `crew review` to verify.\n\n" + NEXT.format("commit")},
     "handoff-multiple-trailers"),
    ("a stray Next: beside a trailer", {SKILL.format("crew-log"): "Print: Next: run `crew commit` to continue.\n\n" + NEXT.format("commit")},
     "handoff-stray-next"),
) + tuple((f"an unrouted verb in {path}", {path: NEXT.format("nowhere")}, "handoff-unrouted-command")
          for path in (".cursor/agents/crew-specwriter.md", ".cursor/agents/crew-reviewer/references/auto-apply.md",
                       ".cursor/agents/references/dispatch.md", ".cursor/skills/crew-x/references/detail.md", SKILL.format("crew-commit")))


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def seeded(base: Path, registered: set[str]) -> None:
    """Every seed in one copy of the tool tree: each must be reported by its rule, at its file."""
    root = base / "seeded"
    shutil.copytree(TOOLS, root / ".agent" / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "rules").mkdir()
    expected = collections.Counter()
    for _, rule, target, text in SEEDED:
        path = (root / ".agent" / "tools" / target).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((path.read_text() if path.exists() else "") + text)
        expected[(rule, path.relative_to(root.resolve()).as_posix())] += 1
    found = LINT.lint(root.resolve(), False)
    for case, rule, target, _ in SEEDED:
        rel = (root / ".agent" / "tools" / target).resolve().relative_to(root.resolve()).as_posix()
        at = [item for item in found if item[2] == rule and (item[0] == rel or rel in item[3])]
        check(f"seeded {case} reports {rule} at its file", len(at) >= expected[(rule, rel)] or (rule == "bootstrap-identical" and any(item[2] == rule for item in found)),
              [item for item in found if item[2] == rule])
    unknown = {item[2] for item in found} - registered
    check("every reported rule is registered", not unknown, unknown)


def fixtures(base: Path, registered: set[str]) -> None:
    for index, (case, files, expected) in enumerate(FIXTURES):
        root = write(base / f"fixture-{index}", {".agent/tools/tools.json": json.dumps(CATALOG), **files})
        (root / "rules").mkdir(exist_ok=True)
        counts = collections.Counter(rule for _, _, rule, _ in LINT.lint(root, False))
        wrong = {rule: counts[rule] for rule in FIXTURE_RULES if counts[rule] != expected.get(rule, 0)}
        check(f"{case}: {expected or 'no finding'}", not wrong and FIXTURE_RULES <= registered, dict(counts))
    for index, (case, files, rule) in enumerate(HANDOFFS):
        root = write(base / f"handoff-{index}", {"rules/crew-router.mdc": ROUTER, **files})
        rules = [found[2] for found in lint_handoff(root, root / "rules" / "crew-router.mdc")]
        check(f"handoff, {case}: {rule or 'no finding'}", rule in rules if rule else rules == [], rules)
    located = lint_handoff(write(base / "located", {"rules/crew-router.mdc": ROUTER, SKILL.format("crew-commit"): NEXT.format("frobnicate")}),
                           base / "located" / "rules" / "crew-router.mdc")
    write(base / "fixture-0", dict([agent("reviewer-a", "tools: Read\n")]))
    printed = cli(LINT_PATH, "--root", str(base / "fixture-0"))
    check("the text report prints `path:line: rule: message` and exits 1",
          printed.returncode == 1 and ".cursor/agents/reviewer-a.md:1: missing-readonly: " in printed.stdout, printed.stdout)
    check("an unrouted verb is reported at its file and line, naming the verb",
          [(p, line, rule) for p, line, rule, _ in located] == [(SKILL.format("crew-commit"), 3, "handoff-unrouted-command")]
          and "crew frobnicate" in located[0][3], located)


def tracked_state(base: Path) -> None:
    """Per-run state under `.agent/` is reported when tracked; tools and templates are not."""
    scratch = write(base / "state", {".agent/tools/keep.py": "x\n", ".agent/_SPEC_TEMPLATE.md": "t\n", ".agent/tasks/abc/SPEC.md": "leaked\n",
                                     ".agent/reviews/note.md": "leaked\n"})
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}
    subprocess.run(["git", "init", "-q", str(scratch)], check=True, env=env)
    subprocess.run(["git", "-C", str(scratch), "add", "-f", ".agent"], check=True, env=env)
    found = sorted(path for path, _, kind, _ in lint_local_state_tracked(scratch) if kind == "tracked-local-state")
    check("tracked task and review state is reported, tools and templates are not",
          [p.split(".agent/")[-1].split("/")[0] for p in found] == ["reviews", "tasks"], found)
    subprocess.run(["git", "-C", str(scratch), "rm", "-r", "--cached", "-q", ".agent/tasks", ".agent/reviews"], check=True, env=env)
    check("untracked state passes", lint_local_state_tracked(scratch) == [])


def main() -> int:
    listing = cli(LINT_PATH, "--list-rules")
    registered = {line.split()[0] for line in listing.stdout.splitlines() if line.strip()}
    check("--list-rules exits 0 and lists every seeded rule", listing.returncode == 0 and {rule for _, rule, _, _ in SEEDED} <= registered,
          {rule for _, rule, _, _ in SEEDED} - registered)
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        seeded(base, registered)
        fixtures(base, registered)
        tracked_state(base)
    print("lint-rules: fail" if FAILED else "lint-rules: pass")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
