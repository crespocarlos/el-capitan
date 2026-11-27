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
from pathlib import Path

import pytest
from cli_runner import load
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
LINT_PATH = TOOLS / "maintenance" / "crew-lint.py"
LINT = load(LINT_PATH)
import lint_prompts as LINT_PROMPTS  # noqa: E402
from lint_prompts import (  # noqa: E402
    AGENT_CLASSES,
    MCP_PLACEHOLDER,
    PROBE_AGENT_TOOLS,
    READONLY_AGENT_TOOLS,
    RESOLVER_AGENT_TOOLS,
    parse_frontmatter,
)
from lint_references import lint_handoff  # noqa: E402
from lint_writing import lint_local_state_tracked  # noqa: E402

# (case, rule, file under .agent/tools, text appended to it: a new file starts empty)
SEEDED = (
    ("git-argv", "direct-git", "task/task_seeded_git.py", "ARGV = [\"git\", \"status\"]\n"),
    ("long-module", "module-size", "task/task_seeded_long.py", "X = 1\n" * 401),
    ("long-tui-module", "module-size", "../../tui/tui_seeded_long.py", "X = 1\n" * 401),
    ("long-tui-docstring", "docstring-length", "../../tui/tui_seeded_doc.py", '"""One.\n\n2\n3\n4\n5\n6\n7\n"""\n'),
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
           "mcp_servers": {"sourcerer": ["sourcerer_code_search", "sourcerer_code_grep"]},
           "native_tools": ["Bash", "Edit", "Glob", "Grep", "Read", "Write"]}
READONLY = f"readonly: true\ntools: Read, Grep, Glob{MCP_PLACEHOLDER}\n"


def agent(name: str, frontmatter: str, body: str = "Body.\n") -> tuple[str, str]:
    return f".cursor/agents/{name}.md", f"---\nname: {name}\ndescription: \"Fixture agent.\"\n{frontmatter}---\n{body}"


def classed(name: str, tools: str | None, readonly: bool) -> tuple[str, str]:
    return agent(name, ("readonly: true\n" if readonly else "") + (f"tools: {tools}\n" if tools is not None else ""))


# (agent, its class's native list or None to inherit, readonly: true expected, a tool outside the class): the exact
# line passes; a missing placeholder, a dropped tool and an extra tool fail; an inheriting agent fails any line.
CLASSES = (("lens-a", READONLY_AGENT_TOOLS, True, "Bash"), ("crew-pr-resolver", RESOLVER_AGENT_TOOLS, True, "Write"),
           ("reviewer-probe", PROBE_AGENT_TOOLS, False, "Edit"), ("crew-builder", None, False, "Read"))
CLASS_FIXTURES = tuple(row for name, native, readonly, extra in CLASSES for row in ((
    (f"{name}: its exact line", dict([classed(name, ", ".join(native) + MCP_PLACEHOLDER, readonly)]), {}),
    (f"{name}: no placeholder", dict([classed(name, ", ".join(native), readonly)]), {"agents-inherit-tools": 1}),
    (f"{name}: a tool dropped", dict([classed(name, ", ".join(native[1:]) + MCP_PLACEHOLDER, readonly)]), {"agents-inherit-tools": 1}),
    (f"{name}: an extra tool", dict([classed(name, ", ".join((*native, extra)) + MCP_PLACEHOLDER, readonly)]),
     {"agents-inherit-tools": 1}),
) if native else (
    (f"{name}: inherits with no line", dict([classed(name, None, readonly)]), {}),
    (f"{name}: any tools: line", dict([classed(name, extra, readonly)]), {"agents-inherit-tools": 1}),
)))


SKILL = ".cursor/skills/{}/SKILL.md"
RULE, RULE_HEAD = "rules/fixture.mdc", "---\ndescription: \"Fixture rule\"\nalwaysApply: false\n---\n"
PASSAGE = "The reviewer reads every changed file once and records the anchor it used for each finding.\n"
POINTER = ("Lookups: follow `~/.cursor/agents/references/lookups.md` before you search for code whose file you do not "
           "already know, or rely on a product or API fact.")
# (case, files, {rule: findings expected}): a rule absent from the map must not fire at all.
FIXTURES = (
    ("a wrong native id", dict([agent("lens-a", f"readonly: true\ntools: Read, Grap, Glob{MCP_PLACEHOLDER}\n")]),
     {"agents-inherit-tools": 1, "tool-id-unknown": 1}),
    ("a deny list beside the allowlist", dict([agent("lens-a", READONLY + "disallowedTools: Write\n")]), {"agents-inherit-tools": 1}),
    ("a named MCP id in a tools: line", dict([agent("lens-a", "readonly: true\ntools: Read, mcp__elastic-docs__search_docs\n")]),
     {"mcp-tool-unknown": 1, "agents-inherit-tools": 1}),
    ("an undeclared tool on a declared server", dict([agent("lens-a", READONLY, "Use mcp__sourcerer__bogus.\n")]), {"mcp-tool-unknown": 1}),
    ("a declared MCP id in agent prose", dict([agent("lens-a", READONLY, "Use mcp__sourcerer__sourcerer_code_search.\n")]), {}),
    ("an unknown MCP id in rule prose", {"rules/fixture.mdc": "---\ndescription: \"Fixture rule\"\nalwaysApply: false\n---\nUse mcp__retired-server__old_tool.\n"},
     {"mcp-tool-unknown": 1}),
    ("a malformed mcp_servers catalog", {".agent/tools/tools.json": json.dumps({**CATALOG, "mcp_servers": "sourcerer"})}, {"invalid-tool-catalog": 1}),
    ("a catalog with no native_tools list", {".agent/tools/tools.json": json.dumps({k: v for k, v in CATALOG.items() if k != "native_tools"})},
     {"invalid-tool-catalog": 1}),
    ("a read-only agent without the flag", dict([agent("lens-a", READONLY.replace("readonly: true\n", ""))]), {"missing-readonly": 1}),
    ("readonly: false is not a declaration", dict([agent("lens-a", READONLY.replace("true", "false"))]), {"missing-readonly": 1}),
    ("the resolver analysis must declare readonly",
     dict([classed("crew-pr-resolver", ", ".join(RESOLVER_AGENT_TOOLS) + MCP_PLACEHOLDER, False)]), {"missing-readonly": 1}),
    ("a worker that declares readonly", dict([agent("crew-builder", "readonly: true\n")]), {"unexpected-readonly": 1}),
    ("the builder and the orchestrators inherit", dict([agent("crew-builder", ""), agent("crew-reviewer", ""), agent("crew-specwriter", "")]), {}),
    ("a read-only agent with no tools: line inherits everything", dict([agent("lens-open", "readonly: true\n")]), {"agents-inherit-tools": 1}),
    *CLASS_FIXTURES,
    # A persona's turn limit leaves two turns past its tool budget, which its text states once.
    ("a persona budget with room for the reply", dict([agent("reviewer-adversarial", READONLY + "maxTurns: 12\ntool_budget: 10\n",
                                                           "Stop calling tools at 10 and write the review.\n")]), {}),
    ("a persona budget that leaves the reply one turn", dict([agent("reviewer-adversarial", READONLY + "maxTurns: 11\ntool_budget: 10\n",
                                                                   "Stop calling tools at 10 and write the review.\n")]),
     {"persona-turn-budget": 1}),
    ("a persona with no tool_budget", dict([agent("specwriter-scope", READONLY + "maxTurns: 10\n")]), {"persona-turn-budget": 1}),
    ("a new persona with no tool_budget", dict([agent("reviewer-security", READONLY + "maxTurns: 10\n")]), {"persona-turn-budget": 1}),
    ("an exempt explorer needs none", dict([agent("reviewer-explorer", READONLY + "maxTurns: 16\n")]), {}),
    ("a budget the text does not state", dict([agent("reviewer-code-quality", READONLY + "maxTurns: 10\ntool_budget: 8\n",
                                                    "Stop calling tools at 6 and write the review.\n")]), {"persona-turn-budget": 1}),
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
    ("narration in a prompt; a participle 'used to' is not", {RULE: RULE_HEAD + "This used to crash. The token used to sign requests lives in the vault.\n"},
     {"no-incident-narration": 1}),
    ("a nested fence closes only at its own length", {RULE: RULE_HEAD + "````\n```lang\nThis used to crash.\n````\n\nThis used to crash.\n"},
     {"no-incident-narration": 1}),
    ("a four-backtick code span opens no fence", {RULE: RULE_HEAD + "```` ```suggestion ```` is a block.\n\nThis used to crash.\n\n```bash\nx=1\n```\n"},
     {"no-incident-narration": 1}),
    ("a 12-word passage in two prompt files; the spec templates share by design",
     {SKILL.format("a"): PASSAGE, SKILL.format("b"): PASSAGE, ".cursor/skills/spec-writing/references/spec-template.md": PASSAGE,
      ".cursor/skills/spec-writing/references/bug-spec-template.md": PASSAGE},
     {"duplicate-passages": 5}),
    ("the lookups pointer sentence is shared by design",
     {SKILL.format(n): POINTER + "\n" for n in "ab"}, {}),
    ("text after the pointer sentence is still scanned",
     {SKILL.format(n): POINTER + " " + PASSAGE for n in "ab"}, {"duplicate-passages": 1}),
    ("a glossary missing a term",
     {".agent/tools/AGENTS.md": "## Glossary\n\n| Term | Meaning |\n| --- | --- |\n"
      + "".join(f"| {term} | x |\n" for term in ("persona", "worker", "gate"))}, {"glossary-terms": 1}),
    ("Elastic ids outside the opt-in heading and the Kibana-scoped skills; 5601 only as a port",
     {SKILL.format("a"): "Check the ES|QL query. PR #5601 at foo.ts:5601; serve on localhost:5601.\n\n## Docs (opt-in: Elastic)\n\n"
      "Check the ES|QL query.\n\n## Next\n\nUse @kbn/i18n.\n",
      SKILL.format("crew-e2e"): "Deploy Kibana on 5601.\n"}, {"vendor-tools-scoped": 3}),
    ("a placeholder used before it is defined",
     {SKILL.format("a"): "Inputs: `$QUX` is the task, `${QUUX}` the review.\n\nRun `x $FOO $QUX $QUUX`.\n\n`BAR` is the input: `x $BAR`.\n\n"
      "```bash\nBAZ=1\nx \"$BAZ\" \"$HOME\"\nsource task-env.sh\nx \"$TASK_DIR\"\n```\n"},
     {"undefined-placeholder": 1}),
    ("a journal write or draft import outside the closing confirmation, the resolver and the memory commands",
     {SKILL.format("a"): "Then save a journal entry: `crew-mem.py journal\nadd --title x`.\n", ".claude/hooks/stop.sh": "crew-mem.py import-inbox \"$f\"\n",
      ".cursor/skills/crew-open-pr/references/closing-confirmation.md": "Run `crew-mem.py journal add`.\n",
      ".cursor/agents/crew-pr-resolver/references/acting-on-threads.md": "Run `crew-mem.py journal add`.\n",
      SKILL.format("crew-log"): "Run `crew-mem.py import-inbox --all`.\n"}, {"one-closing-confirmation": 2}),
    # A loop that reads a subprocess pipe leaves on its read variable's end of file, or spins once the pipe closes.
    ("a pipe read loop with no exit, and a readline loop",
     {"evals/tools/test_loop.py": "import os\nwhile True:\n    chunk = os.read(child.stdout.fileno(), 9)\n    drawn += chunk\n"
      "while 'ready' not in line:\n    line = proc.stdout.readline()\n"}, {"pipe-read-eof": 2}),
    ("a pipe read loop that leaves on another name",
     {"tui/loop.py": "import os\nwhile True:\n    chunk = os.read(child.stdout.fileno(), 9)\n    if not ready:\n        break\n"},
     {"pipe-read-eof": 1}),
    ("pipe read loops that stop at end of file, and a loop that reads no pipe",
     {"evals/tools/test_loop.py": "import os\nwhile n < 2:\n    chunk = os.read(child.stdout.fileno(), 9)\n    if not chunk:\n"
      "        break\nwhile True:\n    line = proc.stderr.readline()\n    if line == '':\n        return\nwhile x:\n    x = f.read()\n"},
     {}),
)
FIXTURE_RULES = {"mcp-tool-unknown", "tool-id-unknown", "missing-readonly", "unexpected-readonly", "persona-turn-budget", "pipe-read-eof",
                 "agents-inherit-tools", "invalid-agent-frontmatter", "invalid-tool-catalog", "command-name", "removed-command-form",
                 "no-incident-narration", "duplicate-passages", "glossary-terms",
                 "vendor-tools-scoped", "undefined-placeholder", "one-closing-confirmation"}
ROUTER = ("# Router\n\n| Trigger | Crew member |\n|---|---|\n| `crew review` | crew-reviewer |\n| `crew commit` | crew-commit |\n"
          "| `crew implement` | crew-builder |\n| `crew check` | crew-check |\n| `crew review address` | crew-address-review skill |\n")
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
    assert condition, f"{name}: {detail}"


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def registered() -> set[str]:
    listing = cli(LINT_PATH, "--list-rules")
    rules = {line.split()[0] for line in listing.stdout.splitlines() if line.strip()}
    check("--list-rules exits 0 and lists every seeded and fixture rule",
          listing.returncode == 0 and {rule for _, rule, _, _ in SEEDED} | FIXTURE_RULES <= rules, listing.stdout)
    return rules


def test_seeded_violations_are_reported_at_their_files(tmp: Path, registered: set[str]) -> None:
    """Every seed in one copy of the tool tree: each must be reported by its rule, at its file."""
    root = tmp / "seeded"
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


@pytest.mark.parametrize("case,files,expected", FIXTURES, ids=[case for case, _, _ in FIXTURES])
def test_fixture(case: str, files: dict[str, str], expected: dict[str, int], tmp: Path) -> None:
    root = write(tmp, {".agent/tools/tools.json": json.dumps(CATALOG), **files})
    (root / "rules").mkdir(exist_ok=True)
    counts = collections.Counter(rule for _, _, rule, _ in LINT.lint(root, False))
    assert {rule: counts[rule] for rule in FIXTURE_RULES} == {rule: expected.get(rule, 0) for rule in FIXTURE_RULES}, dict(counts)


@pytest.mark.parametrize("path", sorted((ROOT / ".cursor" / "agents").glob("*.md")), ids=lambda path: path.stem)
def test_agent_carries_its_class_list(path: Path) -> None:
    """Every shipped agent carries exactly its class's native tools plus the MCP placeholder, or inherits with no line."""
    frontmatter, _, error = parse_frontmatter(path.read_text())
    assert not error, error
    fields = {key.strip(): value.strip() for key, value in (line.split(":", 1) for line in frontmatter.splitlines() if ":" in line)}
    native = AGENT_CLASSES.get(path.stem, (True, READONLY_AGENT_TOOLS))[1]
    wanted = ", ".join(native) + MCP_PLACEHOLDER if native else None
    assert fields.get("tools") == wanted and "disallowedTools" not in fields, (sorted(fields), fields.get("tools"))


@pytest.mark.parametrize("case,files,rule", HANDOFFS, ids=[case for case, _, _ in HANDOFFS])
def test_handoff(case: str, files: dict[str, str], rule: str | None, tmp: Path) -> None:
    root = write(tmp, {"rules/crew-router.mdc": ROUTER, **files})
    rules = [found[2] for found in lint_handoff(root, root / "rules" / "crew-router.mdc")]
    assert rule in rules if rule else rules == [], rules


def test_findings_are_located(tmp: Path) -> None:
    located = lint_handoff(write(tmp / "located", {"rules/crew-router.mdc": ROUTER, SKILL.format("crew-commit"): NEXT.format("frobnicate")}),
                           tmp / "located" / "rules" / "crew-router.mdc")
    write(tmp / "fixture-0", {".agent/tools/tools.json": json.dumps(CATALOG), **dict([agent("lens-a", "tools: Read\n")])})
    (tmp / "fixture-0" / "rules").mkdir()
    printed = cli(LINT_PATH, "--root", str(tmp / "fixture-0"))
    check("the text report prints `path:line: rule: message` and exits 1",
          printed.returncode == 1 and ".cursor/agents/lens-a.md:1: missing-readonly: " in printed.stdout, printed.stdout)
    check("an unrouted verb is reported at its file and line, naming the verb",
          [(p, line, rule) for p, line, rule, _ in located] == [(SKILL.format("crew-commit"), 3, "handoff-unrouted-command")]
          and "crew frobnicate" in located[0][3], located)


def test_tracked_state(tmp: Path) -> None:
    """Per-run state under `.agent/` is reported when tracked; tools and templates are not."""
    scratch = write(tmp / "state", {".agent/tools/keep.py": "x\n", ".agent/_SPEC_TEMPLATE.md": "t\n", ".agent/tasks/abc/SPEC.md": "leaked\n",
                                     ".agent/reviews/note.md": "leaked\n"})
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}
    subprocess.run(["git", "init", "-q", str(scratch)], check=True, env=env)
    subprocess.run(["git", "-C", str(scratch), "add", "-f", ".agent"], check=True, env=env)
    found = sorted(path for path, _, kind, _ in lint_local_state_tracked(scratch) if kind == "tracked-local-state")
    check("tracked task and review state is reported, tools and templates are not",
          [p.split(".agent/")[-1].split("/")[0] for p in found] == ["reviews", "tasks"], found)
    subprocess.run(["git", "-C", str(scratch), "rm", "-r", "--cached", "-q", ".agent/tasks", ".agent/reviews"], check=True, env=env)
    check("untracked state passes", lint_local_state_tracked(scratch) == [])


def command_entry(name: str, **extra: object) -> dict:
    return {"name": name, "dir": "task", "kind": "command", "category": "task", "owner": "repository", "help": "argparse", "smoke": "--help", **extra}


DOCS_ROUTER = ("# Router\n\n| Trigger | Crew member |\n|---|---|\n| `crew commit` | crew-commit |\n| `crew doctor` | `~/.agent/bin/crew-doctor.py` |\n"
               "| `crew idp` | crew-idp skill (quarterly, not a stage) |\n")
DOCS_README = "".join(f"<!-- generated:{name} (crew-lint.py --write-readme) -->\n<!-- /generated:{name} -->\n" for name in ("commands", "standalone", "counts"))
DOCS_ROOT = {
    "rules/crew-router.mdc": DOCS_ROUTER, "README.md": DOCS_README, "VERSION": "0.1.0\n", ".release-please-manifest.json": '{".": "0.1.0"}\n',
    ".agent/tools/tools.json": json.dumps({**CATALOG, "tools": [command_entry("crew-doctor.py", routes={"crew doctor": "Install health."})]}),
    SKILL.format("crew-commit"): "---\nname: crew-commit\ndescription: \"Commit the staged work. Trigger: 'crew commit'.\"\n---\n",
    SKILL.format("crew-idp"): "---\nname: crew-idp\ndescription: \"Use when review season comes round: draft the review answers. Trigger: 'crew idp'.\"\n---\n",
    "release-please-config.json": '{"bootstrap-sha": "cf843d2", "packages": {}}\n',
    **{name: "x\n" for name in ("CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", ".github/workflows/release-please.yml",
                                ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/bug_report.md")},
}
DOCS_RULES = ("readme-commands-current", "readme-counts-current", "release-files")
# (case, files changed after --write-readme (None deletes), {rule: findings expected})
DOCS = (
    ("fresh blocks and every release file", {}, {}),
    ("a routed row added after the table was written",
     {"rules/crew-router.mdc": DOCS_ROUTER + "| `crew log` | crew-log |\n", SKILL.format("crew-log"): "---\nname: crew-log\ndescription: \"Log it.\"\n---\n"},
     {"readme-commands-current": 1, "readme-counts-current": 1}),
    ("an unrouted skill changes only the counts", {SKILL.format("extra"): "---\nname: extra\ndescription: \"x\"\n---\n"}, {"readme-counts-current": 1}),
    ("a tool row with no routes summary", {".agent/tools/tools.json": json.dumps({**CATALOG, "tools": [command_entry("crew-doctor.py")]})},
     {"readme-commands-current": 2}),
    ("no generated markers", {"README.md": "# Readme\n"}, {"readme-commands-current": 2, "readme-counts-current": 1}),
    ("VERSION differs from the release-please manifest, and a release file is missing", {"VERSION": "0.2.0\n", "SECURITY.md": None}, {"release-files": 2}),
    ("a release-please config with no bootstrap-sha would release the whole history", {"release-please-config.json": '{"packages": {}}\n'},
     {"release-files": 1}),
)


@pytest.mark.parametrize("case,changes,expected", DOCS, ids=[case for case, _, _ in DOCS])
def test_readme_blocks_and_release_files(case: str, changes: dict[str, str | None], expected: dict[str, int], tmp: Path) -> None:
    root = write(tmp, DOCS_ROOT)
    written = cli(LINT_PATH, "--root", str(root), "--write-readme")
    printed = cli(LINT_PATH, "--root", str(root), "--commands").stdout
    readme = (root / "README.md").read_text()
    everyday, standalone = readme.split("generated:standalone", 1)
    check("--write-readme fills the tables `--commands` prints (`crew help`), each row described; a row the router marks "
          "not a stage goes to the standalone block with its qualifier, and a leading `Use when` clause is dropped",
          written.returncode == 0 and "| `crew doctor` | Install health. |" in everyday and "| `crew commit` | Commit the staged work. |" in everyday
          and "crew idp" not in everyday and "| `crew idp` | Quarterly: draft the review answers. |" in standalone
          and "| `crew idp` | Quarterly" in printed and all(line in readme for line in printed.splitlines() if line.startswith("|")),
          (written.stderr, readme, printed))
    stamp = (root / "README.md").stat()
    cli(LINT_PATH, "--root", str(root), "--write-readme")
    check("an unchanged README is not rewritten", (root / "README.md").stat().st_mtime_ns == stamp.st_mtime_ns
          and (root / "README.md").stat().st_ino == stamp.st_ino)
    for name, text in changes.items():
        (root / name).unlink() if text is None else write(root, {name: text})
    counts = collections.Counter(rule for _, _, rule, _ in LINT.lint(root, False))
    assert {rule: counts[rule] for rule in DOCS_RULES} == {rule: expected.get(rule, 0) for rule in DOCS_RULES}, dict(counts)


PRUNE_CATALOG = {**CATALOG, "tools": [command_entry(name) for name in ("crew-called.py", "crew-tested.py", "crew-orphan.py")],
                 "modules": [{"name": "helper_module.py", "dir": "task", "kind": "module", "category": "task", "owner": "repository",
                              "help": "imported", "smoke": "imported"}]}
PRUNE_ROOT = {
    ".agent/tools/tools.json": json.dumps(PRUNE_CATALOG), ".agent/tools/task/helper_module.py": '"""Imported, never invoked."""\n',
    **{f".agent/tools/task/{name}": f'#!/usr/bin/env python3\n"""{name} does a thing."""\n' for name in ("crew-called.py", "crew-tested.py", "crew-orphan.py")},
    "rules/crew-router.mdc": "# Router\n\nThe pipeline runs `~/.agent/bin/crew-called.py`.\n", "install.sh": "#!/usr/bin/env bash\nln -sf a b\n",
    ".agent/tools/TOOLS.md": "`crew-called.py`, `crew-tested.py`, and `crew-orphan.py` are all documented.\n", "README.md": "Run `crew-orphan.py`.\n",
    "evals/tools/test_something.py": '"""A test."""\nTOOL = "crew-tested.py"\n',
}
# (case, files changed, crew-orphan.py's verdict, exit code): a catalog page, README, docstring or comment describes; it does not call.
DEAD_CODE = (
    ("the catalog page and the README are not callers", {}, "uncalled", 1),
    ("an installer reference is a caller", {"install.sh": "#!/usr/bin/env bash\nln -sf crew-orphan.py b\n"}, "called", 0),
    ("a docstring, a comment and a tool-tree doc are not callers",
     {".agent/tools/task/helper_module.py": '"""Wraps crew-orphan.py."""\n# crew-orphan.py is described here\nVALUE = 1\n',
      ".agent/tools/AGENTS.md": "Run `crew-orphan.py` to see.\n"}, "uncalled", 1),
    ("a string in code is a caller", {".agent/tools/task/helper_module.py": 'COMMAND = "crew-orphan.py"\n'}, "called", 0),
)


@pytest.mark.parametrize("case,changes,orphan,code", DEAD_CODE, ids=[case for case, _, _, _ in DEAD_CODE])
def test_dead_code(case: str, changes: dict[str, str], orphan: str, code: int, tmp: Path) -> None:
    root = write(tmp, {**PRUNE_ROOT, **changes})
    result = cli(LINT_PATH, "--root", str(root), "--dead-code", "--json")
    verdicts = {row["name"]: row["verdict"] for row in json.loads(result.stdout or "[]")}
    assert (verdicts, result.returncode) == ({"crew-called.py": "called", "crew-tested.py": "test-only", "crew-orphan.py": orphan}, code), result.stderr


def test_dead_code_table_and_unreadable_catalog(tmp: Path) -> None:
    table = cli(LINT_PATH, "--root", str(write(tmp / "repo", PRUNE_ROOT)), "--dead-code")
    rows = [line for line in table.stdout.splitlines() if line.startswith("crew-")]
    check("the table has one row per command and counts the uncalled", len(rows) == 3 and "1 uncalled" in table.stdout and table.returncode == 1, table.stdout)
    broken = cli(LINT_PATH, "--root", str(tmp), "--dead-code")
    check("an unreadable catalog exits 2", broken.returncode == 2 and "cannot read the catalog" in broken.stderr, broken.stderr)


# (case, files, the budget rules lint_budget reports): a prompt file fails above 90% of 11,500 bytes and the always-on set
# (here AGENTS.md alone, tokens = bytes // 4) above 95% of 5,672 tokens, each before its hard ceiling does.
HEADROOM = (
    ("a prompt file at 90%", {SKILL.format("crew-x"): "x" * 10_350}, []),
    ("a prompt file one byte above 90%", {SKILL.format("crew-x"): "x" * 10_351}, ["prompt-headroom"]),
    ("a prompt file at its ceiling", {".cursor/agents/references/r.md": "x" * 11_500}, ["prompt-headroom"]),
    ("a prompt file above its ceiling", {SKILL.format("crew-x"): "x" * 11_501}, ["prompt-budget"]),
    ("the always-on set at 95%", {"AGENTS.md": "x" * 4 * 5_388}, []),
    ("the always-on set above 95%", {"AGENTS.md": "x" * 4 * 5_389}, ["prompt-headroom"]),
    ("the always-on set above its ceiling", {"AGENTS.md": "x" * 4 * 5_673}, ["budget"]),
)


@pytest.mark.parametrize("case,files,expected", HEADROOM, ids=[case for case, _, _ in HEADROOM])
def test_budget_headroom(case: str, files: dict[str, str], expected: list[str], tmp: Path, registered: set[str]) -> None:
    root = write(tmp, files)
    found = LINT_PROMPTS.lint_budget(root, [], set())
    assert [rule for _, _, rule, _ in found] == expected, found
    assert all(message.startswith("headroom exceeded, fails --budget") for _, _, rule, message in found
               if rule == "prompt-headroom"), found
    assert {rule for _, _, rule, _ in found} <= registered


def test_prompt_byte_delta_counts_added_changed_and_removed_prompt_files_only(tmp: Path) -> None:
    root = write(tmp, {SKILL.format("crew-x"): "x" * 10, ".cursor/agents/references/new.md": "y" * 4, "rules/r.mdc": "z" * 3,
                       "AGENTS.md": "a" * 5, ".cursor/skills/crew-x/tool.py": "p" * 50})
    base = {SKILL.format("crew-x"): 12, "rules/r.mdc": 3, "AGENTS.md": 2, ".cursor/agents/references/gone.md": 7,
            ".cursor/skills/crew-x/tool.py": 1, "README.md": 99}
    assert LINT_PROMPTS.prompt_byte_delta(root, base) == [
        (".cursor/agents/references/gone.md", -7), (".cursor/agents/references/new.md", 4), (SKILL.format("crew-x"), -2), ("AGENTS.md", 3)]


def git_repo(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def test_the_budget_report_prints_the_delta_since_the_merge_base(tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Information for the PR body, on stderr: the merge base's short SHA, the total and one row per changed prompt
    file. A change that reached origin/main after the branch left it is not this branch's growth; no base is one note."""
    root = write(tmp / "repo", {SKILL.format("crew-x"): "x" * 10, "AGENTS.md": "a\n"})
    LINT.delta_report(root)
    check("a root without origin/main says it measured nothing", "not measured" in capsys.readouterr().err)
    git_repo(root, "init", "-q", "-b", "work")
    git_repo(root, "add", "-A")
    git_repo(root, "commit", "-qm", "base")
    fork = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    git_repo(root, "checkout", "-qb", "landed")
    (root / "AGENTS.md").write_text("a" * 40)
    git_repo(root, "commit", "-qam", "landed on main later")
    git_repo(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git_repo(root, "checkout", "-q", "work")
    (root / SKILL.format("crew-x")).write_text("x" * 25)
    LINT.delta_report(root)
    err = capsys.readouterr().err
    check("the delta names the merge base, the total and only this branch's file",
          f"prompt bytes vs merge-base(origin/main, HEAD) {fork[:7]}: +15 (1 files changed)" in err
          and f"+15  {SKILL.format('crew-x')}" in err and "AGENTS.md" not in err, err)
    LINT.delta_report(root, "landed")
    check("--delta-base picks another ref", "merge-base(landed, HEAD)" in capsys.readouterr().err)
