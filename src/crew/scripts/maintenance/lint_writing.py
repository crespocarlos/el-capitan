"""Rules over what the repository says: removed command forms, docstrings, narration, pipeline prose.

`removed-command-form`, `docstring-length` (at most 6 lines), `no-incident-narration`
(`narration` takes any text, so prompts are held to it too); a `task-log --step` call with an event label,
a shell rewrite of a tracked file, a hook without a settings entry in both harnesses, tracked `.agent` state.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

from crew.lib.git import run_git
from crew.scripts.maintenance.lint_files import line_no, rel

Finding = tuple[str, int, str, str]
# Forms removed from the command surface, each with its replacement (None: removed outright).
# Words may wrap onto the next line, as they do in hard-wrapped prose. Up to three of the command's own
# arguments may come first: an option (with its value), a quoted word, a `$VAR`, a `<placeholder>` or a path.
# A bare word is none of these, so in `crew-verify.py and git log --since` the flag is not the command's.
_VALUE = r"(?:\"[^\"]*\"|'[^']*'|[^\s;|&`'\"]+)"
_ARG = r"(?:--?[\w-]+(?:=\S+|\s+(?!-)" + _VALUE + r")?|\"[^\"]*\"|'[^']*'|\$\{?\w+\}?|<[\w-]+>|[\w~$-]*[/.][^\s;|&`]*)"
_ARGS = r"(?:\s+" + _ARG + r"){0,3}?\s+"
REMOVED_FORMS = (
    (re.compile(r"crew-progress(?:\.py)?\s+(?:verify|report-check)\b"), "crew-verify.py"),
    (re.compile(r"crew-progress(?:\.py)?\s+(?:lock|blocked|worktree)\b"), "crew-task.py"),
    (re.compile(r"crew-ls(?:\.py)?" + _ARGS + r"--(?:mark-approved|mark-implementing|mark-done|normalize-status|apply)\b"), "crew-task.py"),
    (re.compile(r"crew-ls(?:\.py)?" + _ARGS + r"--tsv\b"), "`crew-ls.py --json`"),
    (re.compile(r"crew-assemble-packages(?:\.py)?" + _ARGS + r"--config\b"), "`<review-dir>/assemble.json`"),
    (re.compile(r"crew-mem(?:\.py)?\s+context\b" + _ARGS + r"--(?:budget-tokens|min-score)\b"), None),
    (re.compile(r"crew-verify(?:\.py)?" + _ARGS + r"--since\b"), "`crew-verify.py --wait <file>`"),
    (re.compile(r"crew-mem(?:\.py)?\s+(?:reindex|ingest|archive|stats|doctor)\b|\bcrew memory doctor\b"), None),
    (re.compile(r"crew-next(?:\.py)?\b|crew-review-stats(?:\.py)?\b|\bcrew review-stats\b"), None),
    (re.compile(r"\bcrew[ -](?:test|cleanup|diagnose|debug|recall|quick|explain)\b|\bcrew inbox\b"), None),
    (re.compile(r"\btester-explorer\b|\bsession-event\.sh\b"), None),
    (re.compile(r"crew-review-findings(?:\.py)?\s+validate-map\b|`validate-map`"), "`crew-review-findings.py coverage`"),
    (re.compile(r"evals/prompts/|evals/reviewer/(?:run|replay|mutate)\.py|evals/reviewer/fixtures\.json"), None),
    (re.compile(r"crew-prune(?:\.py)?\b|\bprune_callers(?:\.py)?\b|\bcrew prune\b"), "`crew-lint.py --dead-code`"),
    (re.compile(r"\bcrew remember\b"), "`crew memory add`"),
    (re.compile(r"\.claude/hooks/fixtures/run\.sh\b|\btest_hooks_contract\.py\b"), "`evals/tools/test_hook_cases.py`"),
)
MAX_MODULE_DOCSTRING_LINES = 6
# Phrases that narrate what code or a run once did, rather than state what holds now. A present
# state of something outside the code ("a ref that no longer exists") is not narration, and neither
# is a participle with an object ("the token used to sign requests").
NARRATION = re.compile(
    r"(?i)(?<!\bis )(?<!\bare )(?<!\bbe )(?<!\bwas )\bused to\b(?! \w+ (?:the|an?|its|their|each|every|\w+s)\b)"
    r"|\b(?:this|it|that|we|they) used to\b"
    r"|\bno longer\b(?! (?:exists?|matches|covers|denies))"
    r"|\b(?:how|in|from) an earlier (?:run|version)\b"
    r"|\bmeasured\b[^.\n]{0,40}?\b\d+ of \d+\b|\b\d+ of \d+ (?:measured|recorded)\b"
    r"|\bthe (?:defect|bug|incident|mistake) (?:this|behind|that)\b|\bwas the (?:defect|bug|mistake)\b"
    r"|\bfor days\b|\bonce shipped\b"
)
SCANNED = (
    "rules/*.mdc",
    ".cursor/**/*.md",
    ".claude/**/*.sh",
    ".claude/**/*.md",
    "src/crew/**/*.py",
    "src/crew/**/*.md",
    "src/crew/**/*.json",
    "README.md",
    "AGENTS.md",
    "install.sh",
    "docs/*.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "evals/tasks.json",
    "evals/*.md",
    ".github/workflows/*.yml",
    ".claude/settings.json",
    ".claude/hooks/contract.json",
)


def scanned_files(root: Path) -> list[Path]:
    """Prompts, hooks, docs, tool sources and eval task text; tests are left out: they assert the forms fail."""
    found = {path for pattern in SCANNED for path in root.glob(pattern) if path.is_file()}
    return sorted(path for path in found if "fixtures" not in path.parts)


def lint_removed_forms(root: Path) -> list[Finding]:
    """A removed command form named anywhere a person or prompt would copy it from."""
    found: list[Finding] = []
    for path in scanned_files(root):
        name = rel(root, path)
        if name.endswith("maintenance/lint_writing.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern, replacement in REMOVED_FORMS:
            found.extend(
                (
                    name,
                    line_no(text, match.start()),
                    "removed-command-form",
                    f"`{' '.join(match.group(0).split())}` no longer exists" + (f"; use {replacement}" if replacement else ""),
                )
                for match in pattern.finditer(text)
            )
    return found


def narration(name: str, text: str, first_line: int = 1) -> list[Finding]:
    """`no-incident-narration` findings for any text: a docstring, a comment, a whole prompt file."""
    return [
        (
            name,
            first_line + text.count("\n", 0, match.start()),
            "no-incident-narration",
            f"`{match.group(0)}` narrates history; state the contract that holds now",
        )
        for match in NARRATION.finditer(text)
    ]


def prose(source: str, tree: ast.Module) -> list[tuple[int, str]]:
    """`(line, text)` of every docstring and comment in one module."""
    found = [
        (node.body[0].lineno, node.body[0].value.value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ]
    try:
        found += [(token.start[0], token.string) for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT]
    except (tokenize.TokenError, IndentationError):
        pass
    return found


def lint_tool_prose(root: Path) -> list[Finding]:
    """Module docstrings at most `MAX_MODULE_DOCSTRING_LINES` lines; no narration in docstrings or comments."""
    found: list[Finding] = []
    for path in sorted((root / "src/crew").rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "lint_writing.py":
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        name = rel(root, path)
        docstring = ast.get_docstring(tree, clean=False) or ""
        lines = len(docstring.strip("\n").splitlines())
        if lines > MAX_MODULE_DOCSTRING_LINES:
            found.append((name, 1, "docstring-length", f"module docstring is {lines} lines (>{MAX_MODULE_DOCSTRING_LINES}); state the contract"))
        for line, text in prose(source, tree):
            found.extend(narration(name, text, line))
    return found


PROGRESS_CALL = re.compile(r"task-log\s+\"?\$TASK_DIR\"?\s+--step\s+\"([^\"]*)\"")
SHELL_EDITS = (
    (re.compile(r"(?<!`)\bsed\s+-[a-zA-Z]*i"), "sed -i rewrites a file in place; use the edit tool"),
    (re.compile(r"(?<!`)\bperl\s+-[a-zA-Z]*i"), "perl -i rewrites a file in place; use the edit tool"),
    (re.compile(r"str\.replace\(.*\)\.write_text|\.write_text\(.*\.replace\("), "replace-then-write as an edit; use the edit tool"),
)
Findings = list[tuple[str, int, str, str]]


def lint_progress_transitions(root: Path, paths: list[Path]) -> Findings:
    """A `task-log --step` call must pass a state transition, not an event label: `--step` writes a
    `TRANSITION:` line, so "commit: abc123" would not be one. Events belong in `--metric`."""
    findings: Findings = []
    for path in paths:
        text = path.read_text(errors="replace")
        for match in PROGRESS_CALL.finditer(text):
            value = match.group(1)
            if "→" not in value and "->" not in value:
                findings.append(
                    (
                        rel(root, path),
                        line_no(text, match.start()),
                        "progress-not-a-transition",
                        f'"{value}" has no state transition; use --step for FROM → TO and --metric for events',
                    )
                )
    return findings


def lint_edit_discipline(root: Path, paths: list[Path]) -> Findings:
    """Flag guidance that tells an agent to rewrite a tracked file from a shell command.

    `python3 - <<'PY'` for a scratch artifact is fine. A script, `sed -i`, or `perl -i` aimed at
    editing repository prose or code is not: it bypasses the edit log and review diffs, and a moved
    anchor silently no-ops instead of failing. A rule that documents the prohibition names those
    commands in backticks, which the lookbehind excludes; a real instruction is prose and is caught.
    """
    findings: Findings = []
    for path in paths:
        if path.suffix not in {".md", ".mdc"}:
            continue
        text = path.read_text(errors="replace")
        for line_index, line in enumerate(text.splitlines()):
            for pattern, message in SHELL_EDITS:
                for _ in pattern.finditer(line):
                    findings.append((rel(root, path), line_index + 1, "shell-file-edit", message))
    return findings


def lint_local_state_tracked(root: Path) -> Findings:
    """No per-run state under `.agent/` may be tracked by git.

    Task specs, review scratch, and journals are written by crew commands into `.agent/`, and two of
    them were committed by an earlier `git add -A` and later swept away by another. `.gitignore` owns
    the rule; this check makes a regression a lint failure instead of a silent commit.
    """
    inside = run_git(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    if inside.returncode != 0:
        return []
    listed = run_git(root, ["ls-files", ".agent"], check=False)
    if listed.returncode != 0:
        return []
    allowed = {"src/crew", ".agent/_SPEC_TEMPLATE.md", ".agent/_BUG_SPEC_TEMPLATE.md", ".agent/_MEMORY_TEMPLATE.md", ".agent/_JOURNAL_TEMPLATE.md"}
    findings: Findings = []
    for line in listed.stdout.splitlines():
        if not line.startswith(".agent/") or line in allowed or line.startswith("src/crew/"):
            continue
        findings.append(
            (line, 1, "tracked-local-state", "per-run state under .agent/ is being version-controlled; add it to .gitignore and run git rm --cached")
        )
    return findings


# What only a harness adapter may know: its payload keys, native event names and registration or answer fields. Each
# is a word no harness-free code needs; `harness/` holds them (crew.harness), tests and docs describe them.
HARNESS_WORDS = re.compile(
    r"\b(cursor_version|hook_event_name|tool_input|tool_response|hookSpecificOutput|additionalContext|followup_message|"
    r"failClosed|loop_limit|agent_transcript_path|last_assistant_message|stop_hook_active|CURSOR_TRANSCRIPT_PATH|"
    r"beforeShellExecution|afterShellExecution|subagentStop|SubagentStop|PreToolUse|PostToolUse|UserPromptSubmit)\b"
)
HARNESS_CODE = ("src/crew/**/*.py", ".claude/**/*.sh", ".claude/*.py", ".claude/hooks/lib/*.py", "install.sh")


def lint_harness_knowledge(root: Path) -> Findings:
    """Harness payload and registration words appear only in `src/crew/harness/`; every other code file reads the
    normalised event and calls an adapter."""
    found: Findings = []
    for pattern in HARNESS_CODE:
        for path in sorted(root.glob(pattern)):
            name = rel(root, path)
            if "harness" in path.relative_to(root).parts or "fixtures" in path.parts or name == "src/crew/scripts/maintenance/lint_writing.py":
                continue
            text = path.read_text(errors="replace")
            found += [
                (name, line_no(text, hit.start()), "harness-knowledge", f"{hit.group(0)} is harness knowledge: read it in crew.harness")
                for hit in HARNESS_WORDS.finditer(text)
            ]
    return sorted(set(found))


def lint_hook_registration(root: Path) -> Findings:
    """Every hook script is a rule in `.claude/hooks/contract.json`, or no harness runs it; every rule sets a `timeout`.

    `guard/` is walked too, while `lib/` holds sourced files, which the contract never names.
    """
    contract = root / ".claude/hooks/contract.json"
    if not contract.exists():
        return []
    rules = json.loads(contract.read_text(encoding="utf-8"))["rules"]
    findings: Findings = [
        (rel(root, contract), 1, "hook-timeout", f"rule {rule.get('name')} has no timeout (the harness default is 600 s)")
        for rule in rules
        if not rule.get("timeout")
    ]
    named = {rule.get("run") for rule in rules}
    for hook in sorted([*(root / ".claude/hooks").glob("*.sh"), *(root / ".claude/hooks/guard").glob("*.sh")]):
        if str(hook.relative_to(root / ".claude/hooks")) not in named:
            findings.append((rel(root, hook), 1, "unregistered-hook", "hook is not a rule in .claude/hooks/contract.json"))
    return findings
