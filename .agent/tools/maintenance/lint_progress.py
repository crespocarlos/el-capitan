#!/usr/bin/env python3
"""Pipeline discipline in prose: PROGRESS transitions, edit discipline, and hook registration.

Three failures that no other check sees. A `crew-progress` call carrying an event label writes a
line that is not a transition, and events belong in `crew-metric`. Guidance that tells an agent to
rewrite a tracked file from a shell command bypasses the edit log and defeats review diffs. An
unregistered hook never runs, and the guards fail closed, so a hook file with no settings entry is
a guard that silently stopped guarding.
"""
from __future__ import annotations

import re
from pathlib import Path

from lint_files import line_no, rel

SETTINGS_FILES = (".claude/settings.json", ".cursor/hooks.template.json")
PROGRESS_CALL = re.compile(r"crew-progress\.py\"?\s+\"?\$TASK_DIR\"?\s+\"([^\"]*)\"")
SHELL_EDITS = (
    (re.compile(r"(?<!`)\bsed\s+-[a-zA-Z]*i"), "sed -i rewrites a file in place; use the edit tool"),
    (re.compile(r"(?<!`)\bperl\s+-[a-zA-Z]*i"), "perl -i rewrites a file in place; use the edit tool"),
    (re.compile(r"str\.replace\(.*\)\.write_text|\.write_text\(.*\.replace\("),
     "replace-then-write as an edit; use the edit tool"),
)
Findings = list[tuple[str, int, str, str]]


def lint_progress_transitions(root: Path, paths: list[Path]) -> Findings:
    """A crew-progress call must pass a state transition, not an event label.

    crew-progress.py prefixes `TRANSITION: ` itself, so an event string like "commit: abc123"
    writes a line that is not a transition. Events belong in crew-metric.py, which owns the METRIC
    line.
    """
    findings: Findings = []
    for path in paths:
        text = path.read_text(errors="replace")
        for match in PROGRESS_CALL.finditer(text):
            value = match.group(1)
            if "→" not in value and "->" not in value:
                findings.append((rel(root, path), line_no(text, match.start()),
                                 "progress-not-a-transition",
                                 f'"{value}" has no state transition; use crew-progress for '
                                 'FROM → TO and crew-metric for events'))
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


def lint_hook_registration(root: Path) -> Findings:
    """Every hook script is named in a settings file, or it never runs.

    `guard/` and `lib/` are both walked: a rule that moved into `guard/` is still a hook that must be
    registered, while `lib/` holds sourced files, which a registration never names.
    """
    findings: Findings = []
    referenced = ""
    for config in SETTINGS_FILES:
        if (root / config).exists():
            referenced += (root / config).read_text(errors="replace")
    hooks = sorted((root / ".claude/hooks").glob("*.sh"))
    hooks += sorted((root / ".claude/hooks/guard").glob("*.sh"))
    for hook in hooks:
        if hook.name not in referenced:
            findings.append((rel(root, hook), 1, "unregistered-hook",
                             "hook is not registered in a settings file"))
    return findings
