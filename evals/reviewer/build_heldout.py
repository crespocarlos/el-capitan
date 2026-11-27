"""Held-out reviewer-eval cases: writes case.json plus change.diff or spec.md, in the format of build_cases.py.

Usage: python3 build_heldout.py <out dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from build_cases import git_diff, line_of  # beside this file, so on sys.path when it runs as a script

CASES: list[dict] = []


def case(**kw: object) -> None:
    CASES.append(kw)


# ---------------------------------------------------------------- code-quality

FINDINGS_HEAD = r'''"""`review-findings.py`: the gate `persist --strict` runs over consolidated findings (excerpt)."""
from __future__ import annotations

import re

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
MAX_FINDINGS = 12
MAX_NITS = 4
EMITTED = {"patch", "decide"}
EVIDENCE_LOCATION = re.compile(r"^[^:\s][^:]*:\d+(?:@[0-9a-f]{7,40})?$")


def check_strict(findings: list[dict], files: list[str] | None = None) -> None:
    emitted = [f for f in findings if f.get("disposition") in EMITTED]
    for f in emitted:
        evidence = f.get("evidence")
        if f["label"] in {"blocking", "attention"} and not (
            f.get("verified") is True
            and isinstance(evidence, str)
            and EVIDENCE_LOCATION.fullmatch(evidence)
        ):
            raise ValueError(
                f"unverified {f['label']} finding {f['title']!r}: set verified=true with evidence as path:line "
                "(or path:line@headSHA), "
                "or downgrade to 'needs more info'"
            )
'''

FINDINGS_TAIL = r'''            location = evidence.split("@", 1)[0].rsplit(":", 1)[0]
            matches = [name for name in files
                       if name == location or name.endswith("/" + location) or location.endswith("/" + name)]
            if not matches:
                raise ValueError(
                    f"finding {f['title']!r} cites {location}, which is not in the reviewed file set"
                )
    nits = [f for f in emitted if f["label"] == "nit"]
    findings_only = len(emitted) - len(nits)
    # Counted separately: a nit must never consume a severity slot, so the two budgets do not
    # trade against each other.
    if findings_only > MAX_FINDINGS:
        raise ValueError(
            f"{findings_only} emitted non-nit findings exceed the cap of {MAX_FINDINGS}; "
            "drop the lowest severity or route pre-existing findings to 'defer'"
        )
    if len(nits) > MAX_NITS:
        raise ValueError(
            f"{len(nits)} emitted nits exceed the cap of {MAX_NITS}; keep the ones with a stated cost "
            "and drop the rest, so polish cannot occupy a severity slot"
        )
'''

FINDINGS_BEFORE = FINDINGS_HEAD + r'''        if files:
            # Shape is not enough: evidence must point at something under review, or a
            # finding about an untouched file is reported as verified.
''' + FINDINGS_TAIL

FINDINGS_AFTER = FINDINGS_HEAD + r'''        if files and isinstance(evidence, str) and evidence:
            # Shape is not enough: evidence must point at something under review, or a
            # finding about an untouched file is reported as verified. A finding with no
            # evidence is allowed here — `blocking`/`attention` were already required to have
            # it above, and a nit may stay unanchored, so there is nothing to check.
''' + FINDINGS_TAIL

case(id="findings-evidence-type-skips-gate", lens="code-quality",
     source="task C5D81C7C, review 20261118141118, code-quality finding 1",
     summary="A nit may stay unanchored, but `persist --strict --files` crashed with an AttributeError on a nit "
             "that has no `evidence`. The reviewed-file gate in `check_strict` now runs only when the finding "
             "carries evidence.",
     defect="The fix folds the type check into the skip condition: a nit whose `evidence` is not a string "
            "(`true`, `{}`, a list) skips the reviewed-file gate and persists as clean with exit 0. A nit's "
            "evidence type is validated nowhere else; it should be checked once, so a malformed value fails "
            "instead of passing, and the gate should then test only presence.",
     files=[(".agent/tools/review-findings.py", FINDINGS_BEFORE, FINDINGS_AFTER)],
     locations=[(".agent/tools/review-findings.py", "if files and isinstance(evidence, str) and evidence:")])

LINT_STYLE = r'''"""The writing standard for prompt files: rules, agents, skills and their references (excerpt).

Prose is read with frontmatter and fenced code masked (inline code too): capitals used as emphasis
are reported, so a rule gives its reason in one sentence instead of shouting. Code is exempt, since
a command or a constant is spelled the way the tool spells it.
"""
from __future__ import annotations

import re
from pathlib import Path

from lint_files import line_no, rel

Findings = list[tuple[str, int, str, str]]
PROMPT_GLOBS = ("rules/*.mdc", ".cursor/agents/**/*.md", ".cursor/skills/**/*.md", ".claude/CLAUDE.md",
                "AGENTS.md", ".agent/tools/AGENTS.md")
SHOUTING = re.compile(
    r"\b(?:MUST|NEVER|ALWAYS|NOT(?! VERIFIED)|ONLY|DO|DON'T|NO|CRITICAL|IMPORTANT|MANDATORY|REQUIRED"
    r"|STOP|ALL|ANY|EVERY|EXACTLY|IMMEDIATELY)\b|(?i:\bmandatory\b|\bno exceptions\b|\bprotocol violation\b)")
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def prompt_files(root: Path) -> list[Path]:
    found = {path for pattern in PROMPT_GLOBS for path in root.glob(pattern) if path.is_file()}
    return sorted(path for path in found if "fixtures" not in path.parts)


def blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def mask(text: str, inline: bool = True) -> str:
    """Frontmatter and fenced code (and inline code when `inline`) as spaces; offsets and lines stay put."""
    text = FRONTMATTER.sub(blank, text)
    text = re.sub(r"^(\s*)(```|~~~).*?^\s*\2[^\n]*$", blank, text, flags=re.S | re.M)
    return re.sub(r"`[^`\n]+`", blank, text) if inline else text


def lint_style(root: Path) -> Findings:
    """The no-shouting rule over every prompt file's prose."""
    found: Findings = []
    for path in prompt_files(root):
        name, text = rel(root, path), path.read_text(encoding="utf-8", errors="replace")
        prose = mask(text)
        found += [(name, line_no(prose, m.start()), "no-shouting",
                   f"`{m.group(0)}` is emphasis; give the reason in one sentence") for m in SHOUTING.finditer(prose)]
    return found
'''

case(id="lint-fence-mask-length", lens="code-quality",
     source="task 0995426A, review 20261127032459, code-quality finding 1",
     summary="crew-lint gains a writing-standard module for prompt files. Its first rule reports capitals used as "
             "emphasis in prose; frontmatter, fenced code blocks and inline code are masked first so commands "
             "and constants are not flagged.",
     defect="The fence mask captures only the first three backticks (`\\2` is ``` even when the opener is four), and "
            "the closer accepts any trailing text: a four-backtick fence that shows a nested ```lang block closes "
            "at the inner opener, after which the mask is inverted for the rest of the file (prose hidden, code "
            "linted). The closer must be the same character, at least as long, with nothing but whitespace after.",
     files=[(".agent/tools/maintenance/lint_style.py", None, LINT_STYLE)],
     locations=[(".agent/tools/maintenance/lint_style.py", 'text = re.sub(r"^(\\s*)(```|~~~)')])


# ---------------------------------------------------------------- architecture

PERSIST_HEAD = r'''"""`review-findings.py`: persist a review directory, and the gates `--strict` adds (excerpt).

`persist` writes REVIEW.md from the inputs already in the review directory (`<persona>.in.md`,
`<persona>.out.md`, `hunks.json`, the findings), so it can be re-run on the same directory after a
partial failure and produces the same report.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

HUNKS_FILE = "hunks.json"
CODE_MODES = frozenset({"self", "changes", "pr"})
'''

PERSIST_SPEC_HELPERS = r'''
# Implementation steps in a spec. Product Flow checks them against the diff; every other lens
# judges the change against the summary and acceptance criteria, so these sections are pure cost
# in its package (18 KB of a measured 156 KB package, sent to every persona).
SPEC_BUILDER_SECTION = re.compile(r"^## (Tasks|Hints)\b")
SPEC_FULL_PERSONAS = frozenset({"product-flow"})
# A copied task line is long; a shorter line could match the diff by accident.
SPEC_LINE_MIN = 40


def spec_sections(spec: str) -> tuple[list[str], list[str]]:
    """Split a spec into the lines every persona gets and the builder-section lines it does not."""
    kept: list[str] = []
    builder: list[str] = []
    in_fence = in_builder = False
    for line in spec.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            in_builder = bool(SPEC_BUILDER_SECTION.match(line))
        (builder if in_builder else kept).append(line)
    return kept, builder


def package_violations(review_dir: Path, personas: list[str], mode: str,
                       spec_path: Path | None, hunks_path: Path | None) -> list[str]:
    """Packaging rules a persona package must meet before it is worth dispatching."""
    errors: list[str] = []
    builder_lines: set[str] = set()
    if mode in CODE_MODES and spec_path and spec_path.is_file():
        builder_lines = {line.strip() for line in spec_sections(spec_path.read_text(encoding="utf-8"))[1]
                         if len(line.strip()) >= SPEC_LINE_MIN and not line.startswith("## ")}
    generated: set[str] = set()
    if hunks_path and hunks_path.is_file():
        generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"]
                     if entry.get("generated")}
    for persona in canonical_personas(personas, split_commas=False):
        package = review_dir / f"{persona}.in.md"
        if not package.is_file():
            continue
        lines = package.read_text(encoding="utf-8", errors="replace").splitlines()
        if persona not in SPEC_FULL_PERSONAS and builder_lines:
            copied = builder_lines.intersection(line.strip() for line in lines)
            if len(copied) >= 2:
                errors.append(f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); "
                              "build its spec with `review-findings.py spec-context`")
        current = ""
        for line in lines:
            if line.startswith("diff --git "):
                current = next((path for path in generated if line.endswith(f" b/{path}")), "")
            elif current and line.startswith("@@"):
                errors.append(f"{package.name} embeds hunks of generated file {current}; "
                              "embed package.diff instead of diff.patch")
                current = ""
    return errors
'''

PERSIST_BODY_START = r'''

def persist(args: argparse.Namespace) -> int:
    owner = args.review_dir.parent.parent
    findings = read_findings(args.findings) if args.findings else []
    # Persona evidence is not a strict-only gate: every call names the personas that produced the
    # review. --strict only adds the diff gates (hunk coverage, evidence paths) that need a clean
    # tree to check.
    if not args.personas:
        raise ValueError(
            "--personas is required: a persisted review must name the personas that produced it"
        )
    missing = [
        f"{persona}.{kind}.md"
        for persona in canonical_personas(args.personas, split_commas=False)
        for kind in ("in", "out")
        if not (args.review_dir / f"{persona}.{kind}.md").is_file()
    ]
    if missing:
        raise ValueError(f"missing persona artifacts in {args.review_dir}: {', '.join(missing)}")
    hunks_path = args.review_dir / HUNKS_FILE
    if args.strict:
        if hunks_path.is_file():
            check_hunk_refs(findings, hunk_ids(hunks_path))
'''

PERSIST_CHECK = r'''        violations = package_violations(args.review_dir, args.personas, args.mode,
                                        owner / "SPEC.md", hunks_path)
        if violations:
            raise ValueError("; ".join(violations))
'''

PERSIST_BODY_END = r'''    report = args.report.read_text()
    write_review(args.review_dir, report, findings)
    return 0
'''

PERSIST_BEFORE = PERSIST_HEAD + PERSIST_BODY_START + PERSIST_BODY_END
PERSIST_AFTER = PERSIST_HEAD + PERSIST_SPEC_HELPERS + PERSIST_BODY_START + PERSIST_CHECK + PERSIST_BODY_END

case(id="persist-strict-old-review-dirs", lens="architecture",
     source="task C5D81C7C, review 20261118150640, architecture finding 2",
     summary="Persona packages get smaller: the orchestrator now embeds `package.diff` (generated files collapsed) "
             "instead of `diff.patch`, and every lens but product-flow gets the spec without its Tasks and Hints. "
             "`package_violations` checks the written `<persona>.in.md` files, and `persist --strict` runs it so "
             "a package that broke the rules cannot reach REVIEW.md.",
     defect="`persist --strict` now applies a packaging rule to the `<persona>.in.md` files already on disk. Every "
            "review directory written before this change embedded `diff.patch` and the full spec, so re-persisting "
            "one (the documented re-run after a partial failure) fails on packaging unrelated to its findings, "
            "after the review cost is spent. The check belongs at dispatch, or only where `package.diff` exists.",
     files=[(".agent/tools/review-findings.py", PERSIST_BEFORE, PERSIST_AFTER)],
     locations=[(".agent/tools/review-findings.py", "violations = package_violations(args.review_dir")])

LS_DATA_HEAD_BEFORE = r'''"""What `crew ls` shows: the `landed` read of a DONE task's PR (excerpt).

`landed` comes from the PR record, not branch ancestry, through the read half of `crew-pr-actions.py`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

import task_bootstrap  # noqa: F401

PR_ACTIONS = Path(__file__).resolve().parents[1] / "review" / "crew-pr-actions.py"
PR_URL = re.compile(r"PR opened: (https?://[^/\s]+/([^/\s]+/[^/\s]+)/pull/(\d+))")
Reader = Callable[[list[str]], "tuple[int, str]"]


def read_pr_actions(arguments: list[str]) -> tuple[int, str]:
    """Run one read of `crew-pr-actions.py`; a missing gh or a timeout is a failed read."""
    try:
        done = subprocess.run([sys.executable, str(PR_ACTIONS), *arguments], capture_output=True,
                              text=True, timeout=45)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout
'''

LS_DATA_HEAD_AFTER = r'''"""What `crew ls` shows: the `landed` read of a DONE task's PR (excerpt).

`landed` comes from the PR record, not branch ancestry, through the read half of `crew-pr-actions.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Callable

import task_bootstrap  # noqa: F401

from lib.git import gh

PR_URL = re.compile(r"PR opened: (https?://[^/\s]+/([^/\s]+/[^/\s]+)/pull/(\d+))")
Reader = Callable[[list[str]], "tuple[int, str]"]


def read_pr_actions(arguments: list[str]) -> tuple[int, str]:
    """One `crew-pr-actions.py` read (`view` or `repo` argv), in process; a missing gh or a timeout fails.

    The review package is imported here, not at module load, so a listing that reads no PR never loads it.
    """
    from review_pr_reads import add_read_parser, read_argv

    parser = argparse.ArgumentParser(add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("view", "repo"):
        add_read_parser(commands, command)
    try:
        args = parser.parse_args(arguments)
        done = gh(*read_argv(args.command, args), timeout=45)
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
    return done.returncode, done.stdout
'''

LS_DATA_TAIL = r'''

def record_of(arguments: list[str], read: Reader) -> dict | None:
    """The JSON record a read printed, or None when the read failed or printed no object."""
    code, text = read(arguments)
    if code:
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None
'''

RECORDS_BEFORE = r'''"""Review records: deferred and dropped findings beside the report, and the review's cost line (excerpt)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import review_bootstrap  # noqa: F401

from review_models import Finding
from review_vocabulary import PERSONAS, canonical_personas

# The one writer of a METRIC line, resolved through this file's real path: installed modules are
# symlinked from `~/.agent/bin` into the repository, so `resolve()` reaches the sibling package.
METRIC = Path(__file__).resolve().parent.parent / "task" / "crew-metric.py"


def record_cost(owner: Path | None, review_dir: Path, mapped: bool) -> str:
    """Append the cost line through `crew-metric.py`; "" when the run has no task directory.

    `crew-metric.py` stays the only writer of a METRIC line, but a hyphenated command cannot be
    imported, so the line reaches it as a subprocess argument. Nothing here may fail a review that
    already persisted, so both a non-zero exit and a failed spawn are reported and swallowed.
    """
    if owner is None or not owner.is_dir():
        return ""
    personas = [persona for persona in canonical_personas(PERSONAS, split_commas=False) if persona != "explorer"]
    if not personas:
        return ""
    payload = cost_line(review_dir, personas, mapped)
    progress = owner / "PROGRESS.md"
    if progress.is_file() and f"METRIC: review run={review_dir.name} " in progress.read_text(
            encoding="utf-8", errors="replace"):
        return payload
    try:
        result = subprocess.run([sys.executable, str(METRIC), str(owner), payload],
                                capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"warning: cost metric not recorded: {error}", file=sys.stderr)
        return payload
    if result.returncode != 0:
        print(f"warning: cost metric not recorded: {result.stderr.strip()}", file=sys.stderr)
    return payload
'''  # noqa: E501

RECORDS_AFTER = r'''"""Review records: deferred and dropped findings beside the report, and the review's cost line (excerpt)."""
from __future__ import annotations

import sys
from pathlib import Path

import review_bootstrap  # noqa: F401

from review_models import Finding
from review_vocabulary import PERSONAS, canonical_personas
from task_progress import append_metric, has_metric


def record_cost(owner: Path | None, review_dir: Path, mapped: bool) -> str:
    """Append the cost line through `task_progress.append_metric`; "" when the run has no task directory.

    `append_metric` is the one METRIC writer (`crew-metric.py` calls it too). Nothing here may fail a
    review that already persisted, so a rejected payload or a failed write is reported and swallowed.
    """
    if owner is None or not owner.is_dir():
        return ""
    personas = [persona for persona in canonical_personas(PERSONAS, split_commas=False) if persona != "explorer"]
    if not personas:
        return ""
    payload = cost_line(review_dir, personas, mapped)
    if has_metric(owner, f"review run={review_dir.name} "):
        return payload
    try:
        append_metric(owner, payload)
    except (OSError, ValueError) as error:
        print(f"warning: cost metric not recorded: {error}", file=sys.stderr)
    return payload
'''  # noqa: E501

TASK_BOOTSTRAP = r'''"""Make `.agent/tools` and its package directories importable, found from this file's real path.

An entry point runs through a symlink in `~/.agent/bin` from any cwd; Python puts the resolved
script directory first on `sys.path`, so `import <package>_bootstrap` finds this file. Every package
has a byte-identical copy; see "Imports" in `.agent/tools/AGENTS.md`.
Small on purpose: it runs before any other import, so it can depend on nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
PACKAGES = ("task", "review", "memory", "evals", "maintenance")

for _entry in (TOOLS, *(TOOLS / name for name in PACKAGES)):
    if str(_entry) not in sys.path:
        sys.path.insert(1, str(_entry))
'''

TOOLS_MD = r'''# Tools (excerpt)

`crew-mem.py`, `crew-review-findings.py`, `crew-ls.py`, `crew-task-context.py`, `crew-evals-compare.py`,
and `crew-lint.py` are argparse entry points over their modules: each parses the command line and
dispatches, and holds no command logic. Modules import each other by their namespaced name in
dependency order (`memory_paths` → `memory_frontmatter` → `memory_store` → `memory_add`/`memory_search`/
`memory_journal`/`memory_inbox` → `memory_maintenance`; `review_vocabulary` → `review_models` →
`review_findings` → `review_render`/`review_layers` → `review_coverage` → `review_report`; `task_status`
→ `task_progress` → `task_state` → `task_resolve`/`task_gates`/`ls_data` → `task_report`; `evals_query` →
`evals_report` → `evals_diagnose`/`evals_sources`; `lint_files` → `lint_catalog`/`lint_prompts`/
`lint_references`/`lint_writing`/`lint_python`), so a module never imports back
into one that imports it. Every entry point and every module that reaches another package imports its
package's `<package>_bootstrap.py` first, which puts `.agent/tools` (so `lib` imports) and the package
directories on `sys.path`; nothing else touches it (see "Imports" in `AGENTS.md`).
'''

case(id="task-review-import-cycle", lens="architecture",
     source="task 0995426A, review 20261126213054, architecture finding 1",
     summary="Sibling tools stop shelling out to each other. `crew ls` reads a PR through `review_pr_reads` in "
             "process instead of running `crew-pr-actions.py`, and a review records its cost line through "
             "`task_progress.append_metric` instead of running `crew-metric.py`.",
     defect="The two edits make the task and review packages import each other: `task/ls_data.py` now imports "
            "`review_pr_reads` and `review/review_records.py` imports `task_progress`. Every bootstrap puts all "
            "packages on `sys.path`, and the documented dependency order lists only chains inside one package, so "
            "no rule states which package may import which and the next cross import can close a real cycle. "
            "The shared read belongs in `lib`, with the allowed package edges declared and checked.",
     files=[(".agent/tools/task/ls_data.py", LS_DATA_HEAD_BEFORE + LS_DATA_TAIL, LS_DATA_HEAD_AFTER + LS_DATA_TAIL),
            (".agent/tools/review/review_records.py", RECORDS_BEFORE, RECORDS_AFTER)],
     context={".agent/tools/task/task_bootstrap.py": TASK_BOOTSTRAP, ".agent/tools/TOOLS.md": TOOLS_MD},
     locations=[(".agent/tools/task/ls_data.py", "from review_pr_reads import add_read_parser, read_argv"),
                (".agent/tools/review/review_records.py", "from task_progress import append_metric, has_metric")])


# ---------------------------------------------------------------- product-flow

WORKER_TREE = r'''#!/usr/bin/env bash
# A live worker's tree: `git checkout`, `git switch`, `git restore` and `git reset --hard` are denied
# in a working tree whose `.crew-worker.lock` is fresh (younger than 6 hours; see task_lock.py). The
# tree is the hook's cwd, or `git -C <path>`, or a leading `cd <path> &&`. Best effort: it does not
# parse every shell form, and a harness without hooks is protected by nothing but the lock's honesty.
# The builder is exempt: CREW_WORKER_TASK equal to the lock's task= (the hook's environment, or an
# inline `CREW_WORKER_TASK=<id>` prefix, which is all a hook can see of the builder's shell).
set -euo pipefail
HOOK_NAME=worker-tree
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

STALE_SECONDS=21600
GIT='git(([[:space:]]+-{1,2}[^[:space:];&|]+([[:space:]]+[^[:space:];&|]+)?)*)[[:space:]]+'
CHANGES_TREE="${GIT}(checkout|switch|restore|reset[[:space:]]+--hard)([[:space:]]|\$|;|&|\|)"
# Quoted text is data: `git commit -m "git checkout x"` is a message, not a command.
INSPECT=$(printf '%s' "$cmd" | sed -E "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")
grep -Eq -- "$CHANGES_TREE" <<<"$INSPECT" || hook_allow

# An absolute or cwd-relative path, with the quotes the shell would drop.
resolve() { case "$1" in /*) printf '%s' "$1" ;; *) printf '%s/%s' "$2" "$1" ;; esac; }
base=$HOOK_CWD
cd_form='^[[:space:]]*cd[[:space:]]+["'"'"']?([^[:space:]"'"'"';&|]+)["'"'"']?[[:space:]]*&&'
c_form='git[[:space:]]+(-[^[:space:]]+[[:space:]]+)*-C[[:space:]]+["'"'"']?([^[:space:]"'"'"';&|]+)'
if [[ $cmd =~ $cd_form ]]; then base=$(resolve "${BASH_REMATCH[1]}" "$HOOK_CWD"); fi
dir=$base
if [[ $cmd =~ $c_form ]]; then dir=$(resolve "${BASH_REMATCH[2]}" "$base"); fi

root=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || hook_allow
lock="$root/.crew-worker.lock"
[ -f "$lock" ] || hook_allow
started=$(awk -F= '$1=="started"{print $2}' "$lock" 2>/dev/null || true)
task=$(awk -F= '$1=="task"{print $2}' "$lock" 2>/dev/null || true)
case "$started" in '' | *[!0-9]*) hook_allow ;; esac
who=${CREW_WORKER_TASK:-}
inline='(^|[[:space:];&|])CREW_WORKER_TASK=["'"'"']?([^[:space:]"'"'"';&|]*)'
if [[ $cmd =~ $inline ]]; then who=${BASH_REMATCH[2]}; fi
if [ -n "$who" ] && [ "$who" = "$task" ]; then hook_allow; fi
if [ $(( $(date +%s) - started )) -lt "$STALE_SECONDS" ]; then
  hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
fi
hook_allow
'''  # noqa: E501

TASK_LOCK = r'''"""`crew-progress.py lock`: the worker lock a live builder holds on its tree (excerpt).

The lock is the file `<tree root>/.crew-worker.lock`, two `key=value` lines: `task=<id>` and
`started=<epoch seconds>` (plus `started_at=<UTC time>` for people). The guard hook
`.claude/hooks/guard/worker-tree.sh` reads it from bash, which is why the start is an integer:
a lock older than `STALE_SECONDS` is stale and no longer denies anything. The file is excluded
through `.git/info/exclude`, so it never shows in a status or a commit.

    crew-progress.py lock write <tree> --task <id>     dispatch: the orchestrator writes it
    crew-progress.py lock remove <tree>                exit: the builder removes it
"""
from __future__ import annotations

from pathlib import Path

LOCK_NAME = ".crew-worker.lock"
STALE_SECONDS = 6 * 60 * 60


def remove_lock(tree: Path) -> bool:
    """Delete the lock; True when one was there."""
    lock = tree / LOCK_NAME
    existed = lock.is_file()
    lock.unlink(missing_ok=True)
    return existed
'''

case(id="worker-lock-no-recovery", lens="product-flow",
     source="task 86BF5814, review 20261126135530, product-flow finding 5",
     summary="A builder can run in the user's main checkout. The orchestrator writes `.crew-worker.lock` into the "
             "tree at dispatch and the builder removes it as its last step; a new guard hook denies "
             "`checkout`, `switch`, `restore` and `reset --hard` in a tree with a fresh lock (under 6 hours), "
             "except for the builder itself.",
     defect="Only the builder removes the lock. A builder that crashes, runs out of context or is stopped leaves it "
            "behind, and the person's own `git switch` in their checkout is then denied for up to 6 hours. The deny "
            "message says to wait for a builder that no longer exists and never names the way out "
            "(`crew-progress.py lock remove <tree>`).",
     files=[(".claude/hooks/guard/worker-tree.sh", None, WORKER_TREE)],
     context={".agent/tools/task/task_lock.py": TASK_LOCK},
     locations=[(".claude/hooks/guard/worker-tree.sh", 'hook_deny "The builder for task')])

CREW_LS_HEAD = r'''#!/usr/bin/env python3
"""List crew task state (read only) without failing on malformed task metadata (excerpt).
'''

CREW_LS_BEFORE = CREW_LS_HEAD + r'''
Modes: the table, `--md`, `--json`; `--all` adds done specs. Writes: `crew-task.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from ls_data import load_rows
from task_report import print_listing


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crew-ls.py", description=__doc__.splitlines()[0])
    parser.add_argument("--md", action="store_true", help="a markdown table")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable JSON array on stdout, diagnostics on stderr")
    parser.add_argument("--all", action="store_true", help="list done specs too")
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    print_listing(load_rows(args.tasks_dir), args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

CREW_LS_AFTER = CREW_LS_HEAD + r'''
Modes: the table, `--md`, `--json`; `--status` filters; `--all` adds done specs. Writes: `crew-task.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from ls_data import load_rows, select
from task_report import print_listing


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crew-ls.py", description=__doc__.splitlines()[0])
    parser.add_argument("--md", action="store_true", help="a markdown table")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable JSON array on stdout, diagnostics on stderr")
    parser.add_argument("--all", action="store_true", help="list done specs too")
    parser.add_argument("--status", action="append", metavar="STATE",
                        help="only tasks in STATE (repeatable); shows stale IMPLEMENTING tasks unfolded")
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    print_listing(select(load_rows(args.tasks_dir), args.status), args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

LS_SELECT_BEFORE = r'''"""What `crew ls` shows: the task rows, gathered once (excerpt)."""
from __future__ import annotations

from pathlib import Path

from task_state import TaskState, head, load


def load_rows(tasks_dir: Path) -> list[TaskState]:
    """Every task under `tasks_dir`; a malformed one is still a row, so the listing never dies on it."""
    return [load(path) for path in sorted(tasks_dir.iterdir()) if path.is_dir()]
'''

LS_SELECT_AFTER = LS_SELECT_BEFORE + r'''

def select(rows: list[TaskState], states: list[str] | None = None) -> list[TaskState]:
    """The rows whose status is one of `states` (every row when none is given)."""
    wanted = {state.upper() for state in states or []}
    return [r for r in rows if not wanted or head(r) in wanted]
'''

TASK_STATUS_TOKEN = r'''"""Task status: the one reader of a spec's `## Status` (excerpt)."""
from __future__ import annotations

STATES = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD", "DONE")
# A user-only side state: not a transition, but a value the store legitimately holds.
SIDE_STATES = ("ABANDONED",)
ACCEPTED = STATES + SIDE_STATES


class StatusError(ValueError):
    """A status value that is not one of `ACCEPTED`."""


def head(value: str | None) -> str:
    """The first word of a status value, upper case; "" when unset."""
    return ((value or "").split() or [""])[0].upper()


def token(value: str | None) -> str:
    """The contract token of a status value, raising `StatusError` for anything unknown.

    The reader stays lenient — a listing must render a malformed task instead of dying on it — but
    a value that becomes authoritative is checked, so a typo fails where it is written rather than
    silently matching no transition rule.
    """
    candidate = head(value)
    if candidate and candidate not in ACCEPTED:
        raise StatusError(f"status {value.strip()!r} is not one of {', '.join(ACCEPTED)}")
    return candidate
'''

case(id="ls-status-typo-empty", lens="product-flow",
     source="task 0995426A, review 20261127040122, product-flow finding 4",
     summary="`crew ls` gains `--status STATE` (repeatable), so the owner can list only the tasks in one state, "
             "for example `--status implementing` to see every IMPLEMENTING task.",
     defect="A mistyped state (`--status implmenting`) matches no row: the listing prints an empty table, \"0 tasks\", "
            "and exits 0, which reads exactly like \"there are no such tasks\". The value should be checked with "
            "`task_status.token`, which exists so a typo fails where it is written, and rejected with exit 2 naming "
            "the accepted states.",
     files=[(".agent/tools/task/crew-ls.py", CREW_LS_BEFORE, CREW_LS_AFTER),
            (".agent/tools/task/ls_data.py", LS_SELECT_BEFORE, LS_SELECT_AFTER)],
     context={".agent/tools/task/task_status.py": TASK_STATUS_TOKEN},
     locations=[(".agent/tools/task/ls_data.py", "wanted = {state.upper() for state in states or []}"),
                (".agent/tools/task/crew-ls.py", 'parser.add_argument("--status", action="append"')])


# ---------------------------------------------------------------- prompt-quality

SKILL_TOP = r'''---
disable-model-invocation: true
name: crew-address-review
description: "Work through findings from the most recent crew review inline. Trigger: 'crew review address'."
---

# Address Review (excerpt)

## Execution model

**Two modes; Step 1 selects one:**

- **Code mode** (self-review, changes review, PR review): silent file-check → verdict table → apply
  edits. 3 turns.
'''

SKILL_MODES_BEFORE = r'''- **Idea mode** (`## Review: Idea` or `## Review: Spec` in context): no files to edit — findings are
  conceptual. Evaluate inline → present acceptance table → synthesize revised idea if approved. 3
  turns.
'''  # noqa: E501

SKILL_MODES_AFTER = r'''- **Idea mode** (`## Review: Idea` or `## Review: Spec` in context): the artifact is a plan, not code.
  Findings are conceptual: evaluate inline → present acceptance table → synthesize the revision if
  approved. The revision is an edit to the spec file when the artifact is one, and emitted text when
  it is pasted. 3 turns.
'''  # noqa: E501

SKILL_MIDDLE = r'''
Never mix modes. If the review heading contains "Idea" or "Spec" (case-insensitive), use idea mode
throughout.

## When Invoked

### Step 1: Locate findings and detect mode

**Detect mode now, before any other step.** Check the `## Review: <mode>` heading in context
(case-insensitive):
- Contains "idea" or "spec" → **Idea mode**
- Anything else (self, changes, PR, etc.) → **Code mode**

Carry this mode through Steps 2–4 without re-detecting.

Check if a `## Review:` heading is visible in the current session conversation. If yes, use those
findings directly — do not read any file.

### Step 2: Evaluate findings (silent pass)

**Code mode:** For each finding, before preparing any edits:

1. **Read the relevant file** (if a specific file/line is cited) — check the current state of the
   code
2. **Check if already addressed**: if the finding's fix is already present in the working tree,
   classify as **Already Addressed** — no edit needed
3. **Assess validity**: is the finding grounded? Classify as **Apply**, **Adapt**, **Reject** or
   **Defer**, with the reason

**Idea mode:** No files to read. For each finding:

1. **Assess whether the critique holds**: does the reviewer's concern actually apply to the idea as
   stated?
   - If the concern is valid and actionable, classify as **Accept** — note what change to the idea
     it implies
   - If the concern is misplaced or based on a misreading, classify as **Reject** — explain why
   - If the concern is valid but needs the user's input to resolve, classify as **Needs Input**
2. Do not fabricate new direction — only incorporate what the reviewer found plus any clarifications
   the user provides in the next step

Never apply any change during this step. Collect all verdicts first.

### Step 3: Report and ask for approval

Present the verdict table (code mode) or the acceptance table (idea mode), then ask which rows to
apply: `all`, `none`, or row numbers.

### Step 4: Apply

**Code mode:** read each file immediately before editing it, apply the approved fixes, and log each
outcome.
'''

SKILL_IDEA_BEFORE = r'''
**Idea mode:** Do not edit any files. Instead:

1. If the user chose `none`, skip synthesis entirely — go straight to the summary.
2. Collect all accepted/nit items plus any user answers to Needs Input items.
3. Locate the original idea text — it is in the session conversation (the pasted text or the output
   of the prior `crew review idea` turn). If the original idea is not recoverable from context
   (scrolled out or session reset), ask: `"I can't locate the original idea text in context — please
   paste it and I'll produce the revised version."` Then wait.
4. Produce a **revised idea** that incorporates all accepted changes. Match the original structure
   and heading levels. Do not add new sections; do not remove content unless a finding specifically
   called it out.
5. Present the revised idea inline under a heading like `## Revised Idea`.
'''

SKILL_IDEA_AFTER = r'''
**Idea mode with a file target:** the same edit rules apply — read the file immediately before
editing, and apply the revision as real edits to it. Idea mode's "synthesis, not implementation" rule
means it does not touch code the spec describes; it does write the spec.

**Idea mode:** synthesis, not implementation. The artifact is usually pasted text, but a spec review
targets a `SPEC.md` file; in that case the "revised idea" is an edit to that file, not a chat reply.

1. If the user chose `none`, skip synthesis entirely — go straight to the summary.
2. Collect all accepted/nit items plus any user answers to Needs Input items.
3. Locate the original artifact:
   - **Spec review, or any review whose target is a file** (the `## Review:` heading names it, or the
     findings cite `SPEC.md`): read that file. Do not ask the user to paste what is already on disk.
   - **Idea review of pasted text**: it is in the session conversation (the pasted text or the output
     of the prior `crew review idea` turn). If it is not recoverable from context (scrolled out or
     session reset), ask: `"I can't locate the original idea text in context — please paste it and
     I'll produce the revised version."` Then wait.
4. Produce the **revision** that incorporates all accepted changes: for a file target, edit that file
   in place; for pasted text, emit the revised text. Match the original structure and heading levels.
   Do not add new sections; do not remove content unless a finding specifically called it out.
5. Present the result:
   - **File target:** the edit landed in the file; show the changed sections as a diff and name the
     path. Do not also paste the whole file.
   - **Pasted text:** present the revised text inline under a heading like `## Revised Idea`.
'''

SKILL_BEFORE = SKILL_TOP + SKILL_MODES_BEFORE + SKILL_MIDDLE + SKILL_IDEA_BEFORE
SKILL_AFTER = SKILL_TOP + SKILL_MODES_AFTER + SKILL_MIDDLE + SKILL_IDEA_AFTER

case(id="address-idea-no-files-to-read", lens="prompt-quality",
     source=("task C5D81C7C, review 20261118141118, consolidated finding (adversarial and prompt-quality; "
             "code-quality finding 3)"),
     summary="`crew review address` in idea mode used to emit a revised idea as chat text only. A spec review "
             "targets `SPEC.md` on disk, so idea mode now reads that file and applies the accepted revision to it "
             "as real edits, and keeps emitting text for a pasted idea.",
     defect="Step 2 still opens idea mode with \"No files to read\" (and Step 1 says to use visible findings "
            "\"do not read any file\"), unchanged by this edit. An agent that follows the earlier, more emphatic "
            "rule evaluates the findings without opening the spec, and the new \"read that file\" branch in Step 4 "
            "contradicts it; Step 2 must be scoped to pasted text.",
     files=[(".cursor/skills/crew-address-review/SKILL.md", SKILL_BEFORE, SKILL_AFTER)],
     locations=[(".cursor/skills/crew-address-review/SKILL.md", "**Idea mode:** No files to read."),
                (".cursor/skills/crew-address-review/SKILL.md", "findings directly — do not read any file."),
                (".cursor/skills/crew-address-review/SKILL.md", "findings cite `SPEC.md`): read that file.")])

DISPATCH_TOP = r'''# Shared dispatch instructions (excerpt)

Run orchestrators inline. Dispatch personas only from the main session: use Cursor Task or Claude
Agent, preserve inherited model selection, and use the documented fallback only when native dispatch
is unavailable.

'''

DISPATCH_BEFORE_BODY = r'''Reviewer personas may run read-only: Cursor Ask mode, or a Claude Code read-only subagent, where
repository reads and artifact writes are unavailable, and the `claude -p` fallback likewise returns
only stdout. Dispatch prompts must embed the immutable evidence (a path to a diff file is not
evidence) needed for the assigned lens: diff, contract, relevant file excerpts, and explorer
findings. Never rely on a persona writing its own artifact.
'''  # noqa: E501

DISPATCH_AFTER_BODY = r'''Reviewer personas may run read-only: Cursor Ask mode, or a Claude Code read-only subagent, where
artifact writes are unavailable, and the `claude -p` fallback likewise returns only stdout. Dispatch
prompts must carry the immutable evidence needed for the assigned lens: diff, contract, relevant file
excerpts, and explorer findings; deliver it inline, or by path under **Package delivery** below.
Never rely on a persona writing its own artifact.

**Package delivery: inline by default, by path when a package is too large to embed.** Inline means
the package is the dispatch prompt; a path to a diff file on its own is not evidence, because the
persona may have no file access at all. Reading the written `<persona>.in.md` back is a sanctioned
alternative when all three hold:

1. The package was written to `$REVIEW_ROOT` and passed the `check-packages` gate of
   `crew-reviewer`'s dispatch step, so the file read is byte-for-byte the package the protocol checked.
2. The persona can read files — Cursor, or Claude Code with `Read` (a `readonly` subagent still
   reads). A run with no file access, such as the `claude -p` fallback, must embed.
3. The dispatch prompt names the absolute package path, states that this file is the persona's whole
   package and must be read in full before judging, and repeats only the delivery-independent
   instructions: reply text only, no artifact writes, the finding shape, and the mode.

Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB, roughly 160k tokens of duplicate output. A package
delivered by path is still the audit artifact: `<persona>.in.md` and `<persona>.out.md` stay the pair
`persist --strict` requires, and the recorded package remains the one the persona read.
'''  # noqa: E501

DISPATCH_TAIL = r'''
**PR mode:** the package is the only repository evidence a persona may use. Every code excerpt must
identify `path:line@headSHA7` and come from `gh api` at that head. A persona must not use the local
checkout — no file reads, repository search, semantic search, or Explorer output, whatever the
harness names those tools — to verify a PR claim. It may return `[needs more info]` only when it
names the missing PR-head path or excerpt.
'''

case(id="dispatch-size-trigger-unevaluable", lens="prompt-quality",
     source="task C5D81C7C, review 20261119135001, prompt-quality finding 5",
     summary="Large review packages were embedded in every dispatch prompt, so the orchestrator re-emitted hundreds "
             "of KB. The shared dispatch instructions now allow delivering a checked package by path, under three "
             "conditions, when it is too large to embed.",
     defect="The trigger for path delivery is \"when embedding would push the orchestrator's own output past what "
            "the harness accepts\", a bound the reader does not know and nothing supplies; the 640 KB figure is an "
            "anecdote, not a threshold. Two models decide differently: one inlines a package that then gets "
            "truncated, another adds a file read for a small one. It needs a checkable condition (a size in KB, or "
            "inline first and re-dispatch by path on truncation).",
     files=[(".cursor/agents/references/dispatch.md", DISPATCH_TOP + DISPATCH_BEFORE_BODY + DISPATCH_TAIL,
             DISPATCH_TOP + DISPATCH_AFTER_BODY + DISPATCH_TAIL)],
     locations=[(".cursor/agents/references/dispatch.md", "Use it when embedding would push the orchestrator's")])


# ---------------------------------------------------------------- specwriter-adversarial

SPEC_WAIT = '''# Spec: run verification in the background and wait for it

## Type: feature
## Branch: feat/verify-background
## Status
DRAFTING

## Summary
A builder runs `crew-task.py verify` and blocks for the whole run, often several minutes, while it
could be writing the report. Add `--background`, which starts the run and returns at once, and
`--wait <path>`, which blocks until the run is finished and prints its verdict. The report check
(`report-check --gates`) reads the same result file, so the report states the gates that really ran.

The result file is `<TASK_DIR>/gates.json` by default (`--out` overrides it). A task runs verify many
times: after each batch, after a fix, and before the PR.

## Acceptance criteria
- [ ] `verify --background` starts the gates in a child process and exits 0 at once, printing the
      result path.
- [ ] The child writes the result file after each gate: `{"state": "running", "gates": [...]}`, then
      `{"state": "done", "verdict": "pass" | "fail", "gates": [...]}` when the last gate finishes.
- [ ] `verify --wait <path>` polls the file every 2 s until its `state` is `done`, prints one line per
      gate, and exits 0 on pass, 1 on fail, 3 after `--timeout` (default 900 s).
- [ ] `report-check --gates <path>` fails a report that claims a gate the file does not list as passed.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_task_verify.py`
- A background run in a fresh task directory, waited on, returns the child's verdict.

## Tasks
- [ ] Task 1: add `background` and `wait` to `.agent/tools/task/task_verify.py`, and the two flags.
- [ ] Task 2: write the result after each gate in `run_all`.
- [ ] Task 3: add rows to `evals/tools/test_task_verify.py`.
'''

case(id="spec-wait-stale-result", lens="specwriter-adversarial", kind="spec", hand_seeded=True,
     source="hand-seeded from task 86BF5814 (review 20261126135530, adversarial finding 1), reduced to a spec",
     summary="A spec for running verify in the background and waiting on its result file.",
     defect="The result file is reused across runs and the child writes it only after its first gate, so a "
            "`--wait` right after `--background` reads the previous run's `done` file and returns its verdict "
            "at once. No criterion makes `--background` reset or remove the file before launching, or ties the "
            "waited result to this run (a run id or start time), and the only test starts from a fresh directory.",
     spec=SPEC_WAIT,
     locations=[("SPEC.md", "- [ ] `verify --wait <path>` polls the file"),
                ("SPEC.md", "- [ ] The child writes the result file after each gate")],
     refs=["--wait", "criterion 3", "AC 3", "AC3", "criterion 2", "AC 2", "AC2"])

SPEC_GC = '''# Spec: garbage-collect finished tasks

## Type: feature
## Branch: feat/task-gc
## Status
DRAFTING

## Summary
`~/.agent/tasks` grows without bound: a busy month leaves sixty task directories, each with its
SPEC.md, PROGRESS.md, review runs and worktree notes. Add `crew-task.py gc`, which lists the finished
tasks past a retention period and, with `--apply`, deletes them.

A task reaches DONE through `crew-task.py mark-done`, which requires the URL of the PR the task
opened. Whether that PR merged is shown by `crew ls --all` in its `landed` column (`yes`, `no` or
`unknown`), read from GitHub.

## Acceptance criteria
- [ ] `gc` lists every task whose status is DONE and whose last PROGRESS.md line is older than
      `retention_days` (default 30, from `~/.agent/config.json`).
- [ ] `gc --apply` deletes each listed task directory and prints one line per deletion.
- [ ] A task in any other state is never listed, whatever its age.
- [ ] `gc --json` prints the listed paths as a JSON array.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_task_gc.py`

## Tasks
- [ ] Task 1: add `.agent/tools/task/task_gc.py` (select, list, apply) and the `gc` subcommand.
- [ ] Task 2: read `retention_days` from `~/.agent/config.json`, defaulting to 30.
- [ ] Task 3: add `evals/tools/test_task_gc.py` with rows for the age boundary, other states and `--json`.
'''

case(id="spec-gc-deletes-unmerged", lens="specwriter-adversarial", kind="spec", hand_seeded=True,
     source="hand-seeded, modelled on task 558C4091 (DONE means a PR is open) and task 0995426A's gc command",
     summary="A spec that adds a retention command deleting finished task directories.",
     defect="DONE only means a PR was opened, not that it merged: a task whose PR is still in review after 30 days, "
            "or was closed unmerged, is selected and its directory (spec, reviews, progress) deleted for good. "
            "The selection must require `landed: yes` (or skip `no` and `unknown`), or archive instead of delete; "
            "no criterion covers an open or unmerged PR.",
     spec=SPEC_GC,
     locations=[("SPEC.md", "- [ ] `gc` lists every task whose status is DONE"),
                ("SPEC.md", "- [ ] `gc --apply` deletes each listed task directory")],
     refs=["criterion 1", "AC 1", "AC1", "criterion 2", "AC 2", "AC2", "--apply"])


# ---------------------------------------------------------------- specwriter-scope

SPEC_BUNDLED = '''# Spec: smaller persona packages

## Type: feature
## Branch: feat/package-size
## Status
DRAFTING

## Summary
Each persona package embeds `diff.patch` and the whole SPEC.md. One measured five-persona review sent
156 KB per persona, 18 KB of it the spec's Tasks and Hints, and a generated lockfile's hunks. Embed
`package.diff`, where generated files are collapsed to one line, and give every lens but product-flow
the spec without its Tasks and Hints. Check the written packages before dispatch.

## Acceptance criteria
- [ ] Every `<persona>.in.md` embeds `package.diff`; a generated file appears as one summary line.
- [ ] Every package but product-flow's carries the spec without `## Tasks` and `## Hints`.
- [ ] `review-findings.py check-packages` exits 1 naming the package that breaks either rule.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_review_hunks.py evals/reviewer/test_review_findings.py`

## Tasks
- [ ] Task 1: write `package.diff` in `.agent/tools/review-hunks.py` (generated files collapsed).
- [ ] Task 2: add `spec-context` and `check-packages` to `.agent/tools/review-findings.py`.
- [ ] Task 3: have `crew-reviewer.md` build each package from `package.diff` and `spec-context`, and run
      `check-packages` before dispatch.
- [ ] Task 4: rewrite `.cursor/agents/references/reviewer-contract.md`, which every persona reads first:
      turn the "One issue per finding" and "Say whether the defect pre-exists" headings into bullets and
      tighten the wording of the severity section.
- [ ] Task 5: add rows to `evals/tools/test_review_hunks.py` and `evals/reviewer/test_review_findings.py`.
'''

case(id="spec-bundled-contract-rewrite", lens="specwriter-scope", kind="spec", hand_seeded=True,
     source="hand-seeded from task C5D81C7C (review 20261118150640, architecture finding 3), reduced to a spec",
     summary="A spec that shrinks the packages sent to review personas.",
     defect="Task 4 rewrites the shared reviewer contract, which every persona reads, inside a packaging change: "
            "it serves no criterion, changes every lens's behaviour with nothing to measure it, and cannot be "
            "reverted apart from the packaging work. It belongs in its own PR.",
     spec=SPEC_BUNDLED,
     locations=[("SPEC.md", "- [ ] Task 4: rewrite `.cursor/agents/references/reviewer-contract.md`")],
     refs=["Task 4", "T4"])

SPEC_DECISION = '''# Spec: show each task's model cost in the TUI

## Type: feature
## Branch: feat/tui-cost
## Status
DRAFTING

## Summary
The TUI shows each task's state and age but not what it cost. Each stage already records its token
counts as `METRIC: stage=<name> input=<n> output=<n> cache_read=<n>` lines in PROGRESS.md. Add a COST
column that prices those tokens, and a total row.

Open question: which model's prices to use. Builders run on Sonnet and reviews partly on Opus; the
owner has not decided whether the column should price every line at one model's rates or at the
model each stage used.

## Acceptance criteria
- [ ] The task table has a COST column in US dollars, two decimals, right-aligned.
- [ ] A total row sums the column over the rows shown.
- [ ] A task with no METRIC line shows `—`, not `$0.00`.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_tui_model.py`

## Tasks
- [ ] Task 1: parse the METRIC token counts per task in `tui/tui_model.py`.
- [ ] Task 2: ask the owner which pricing they want, then add the price table to `tui/tui_cost.py`
      and price each task with it.
- [ ] Task 3: render the column and the total row in `tui/tui_app.py`.
- [ ] Task 4: add rows to `evals/tools/test_tui_model.py` for a priced task, the total and no METRIC.
'''

case(id="spec-task-needs-owner-decision", lens="specwriter-scope", kind="spec", hand_seeded=True,
     source="hand-seeded, modelled on task 71BB7660's TUI token cost",
     summary="A spec that adds a cost column to the task TUI.",
     defect="Task 2 cannot be built: the builder runs unattended and cannot ask the owner, and the pricing choice "
            "is left as an open question, so the builder either stops or invents a policy the owner never chose. "
            "The decision belongs in the spec before approval, with a criterion that pins it.",
     spec=SPEC_DECISION,
     locations=[("SPEC.md", "- [ ] Task 2: ask the owner which pricing they want")],
     refs=["Task 2", "T2"])


# ---------------------------------------------------------------- keywords

KEYWORDS = {
    "findings-evidence-type-skips-gate": [
        ["non-string", "not a string", "isn't a string", "is not a string", "wrong type", "bool*", "true",
         "dict*", "object", "malformed", "type check*", "type validation", "invalid type", "type of"],
        ["skip*", "silent*", "bypass*", "exit 0", "unchecked", "escap*", "slips", "never checked",
         "never validated", "passes the gate", "persists"]],
    "lint-fence-mask-length": [
        ["four", "4-backtick", "four-backtick", "nested", "fence length", "length", "longer", "info string",
         "info-string", "quadruple", "three backticks", "3 backticks"],
        ["clos*", "terminat*", "ends the fence", "end of the fence", "invert*"]],
    "persist-strict-old-review-dirs": [
        ["existing review*", "old review*", "older review*", "earlier review*", "pre-existing", "previous review*",
         "written before", "legacy", "backward*", "re-persist*", "rerun*", "re-run*", "historical",
         "already on disk", "prior review*", "old director*", "existing director*"],
        ["fail*", "refus*", "reject*", "break*", "raise*", "abort*"]],
    "task-review-import-cycle": [
        ["cycle", "cycles", "cyclic", "circular*", "each other", "mutual*", "both directions", "two-way",
         "bidirectional", "package direction", "dependency direction", "layering", "package edge*",
         "cross-package"]],
    "worker-lock-no-recovery": [
        ["crash*", "dead", "died", "dies", "killed", "orphan*", "left behind", "leftover", "no longer running",
         "no longer exists", "interrupted", "aborted", "never removed", "not removed", "stopped",
         "out of context", "never cleaned", "not cleaned"],
        ["recover*", "remove the lock", "clear the lock", "delete the lock", "lock remove", "unlock*", "6 hours",
         "six hours", "way out", "what to do", "actionable", "next step", "stuck", "trapped", "locked out"]],
    "ls-status-typo-empty": [
        ["typo*", "mistyp*", "misspel*", "unknown state*", "unknown status*", "invalid", "unrecogni*",
         "not a valid", "no such state", "bad value", "wrong state"],
        ["empty", "0 tasks", "zero tasks", "no tasks", "no rows", "exit 0", "exits 0", "silent*",
         "indistinguishable", "looks like"]],
    "address-idea-no-files-to-read": [
        ["contradict*", "conflict*", "forbid*", "ban*", "prohibit*", "unreachable", "dead", "never open*",
         "never read*", "never reach*", "inconsistent", "disagree*"],
        ["Step 2", "Step 1", "no files", "read any file", "reading files", "read files", "read the spec",
         "evaluation step", "silent pass", "earlier step"]],
    "dispatch-size-trigger-unevaluable": [
        ["threshold", "bound", "no number", "no size", "KB", "checkable", "evaluat*", "cannot know",
         "can't know", "does not know", "doesn't know", "unknowable", "observable", "undefined", "vague*",
         "ambiguous", "anecdot*"],
        ["harness*", "trigger*", "condition*", "when to"]],
    "spec-wait-stale-result": [
        ["previous run*", "earlier run*", "old result*", "stale", "last run*", "prior run*", "leftover",
         "old file", "old verdict", "already exists", "reused", "left over", "from before"],
        ["wait*", "background*", "poll*"]],
    "spec-gc-deletes-unmerged": [
        ["merged", "merge", "landed", "unmerged", "still open", "open PR", "closed PR", "never merged",
         "not merged", "in review"],
        ["delet*", "remov*", "garbage", "retention", "lose*", "lost", "archiv*", "irreversib*"]],
    "spec-bundled-contract-rewrite": [
        ["unrelated", "separate PR", "own PR", "another PR", "split*", "bundl*", "out of scope", "scope creep",
         "one concern", "second concern", "different concern", "independent*", "not part of", "separate change"],
        ["contract", "Task 4", "T4"]],
    "spec-task-needs-owner-decision": [
        ["owner", "decision", "decide*", "undecided", "open question", "unresolved", "interactive*", "human",
         "unattended", "TBD", "not decided", "cannot ask", "can't ask"],
        ["Task 2", "T2", "pricing", "price*"]],
}


def main() -> None:
    out = Path(sys.argv[1])
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
