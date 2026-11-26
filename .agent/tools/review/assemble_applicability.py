#!/usr/bin/env python3
"""Which personas apply to a diff, as a RECORDED decision rather than a silent omission.

A persona with nothing to read still costs a full package and a reply. Today only Prompt Quality can
be shown not to apply from the diff alone: it applies when a changed path is a prompt, agent, skill,
rule, or a prompt EMBEDDED in code (`**/prompts/*.md`, `*.prompt`), or when the run named prompt files.
The other four read any change, so they are always packaged. `assemble.json` may add reasons:
`"skip_personas": {"<persona>": "<why>"}` (an orchestrator's own selection) and `"selected": [...]`
(the `select` output; a persona listed there is never auto-skipped).

The skips and the per-persona sizes are merged into `manifest.json` under `personas`, which the report
names, so a review that ran three lenses says why it did not run four. `manifest.json` keeps the keys
`prior-review` reads (`root`, `files`); a run with no manifest gets one holding only this record.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from review_manifest import MANIFEST_FILE
from review_parse import header_paths
from review_vocabulary import SELECT_RULES

EMBEDDED_PROMPT = re.compile(r"(^|/)prompts?/[^/]+\.(md|txt|prompt)$|(^|/)[\w.-]*prompts?[\w.-]*\.(md|txt|prompt)$")
SCHEMA_VERSION = 1


def changed_paths(diff: str) -> list[str]:
    """The new-side path of every file in a unified diff, in diff order."""
    paths = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            old, new = header_paths(line)
            paths.append(new or old)
    return [p for p in paths if p]


def applies(persona: str, paths: list[str], config: dict) -> tuple[bool, str]:
    """`(True, "")` when the persona should be packaged, else `(False, <reason>)`."""
    explicit = (config.get("skip_personas") or {}).get(persona)
    if explicit:
        return False, str(explicit)
    if persona in (config.get("selected") or []):
        return True, ""
    if persona == "prompt-quality" and not config.get("prompt_files"):
        pattern = SELECT_RULES["prompt-quality"]
        if not any(pattern.search(p) or EMBEDDED_PROMPT.search(p) for p in paths):
            return False, "no prompt, agent, skill, rule or embedded prompt path in the diff"
    return True, ""


def decide(personas: tuple[str, ...], diff: str, config: dict) -> tuple[list[str], dict[str, str]]:
    """`(personas to package, {skipped persona: reason})`."""
    paths = changed_paths(diff)
    skipped = {}
    for persona in personas:
        ok, reason = applies(persona, paths, config)
        if not ok:
            skipped[persona] = reason
    return [p for p in personas if p not in skipped], skipped


def size_report(sizes: dict[str, int], full: int, skipped: dict[str, str], sliced: dict[str, dict]) -> list[str]:
    """The lines printed after the packages: bytes per persona against the full-diff package size."""
    lines = []
    for persona, size in sizes.items():
        share = f"{round(100 * size / full)}% of the largest" if full else "n/a"
        note = sliced.get(persona)
        lines.append(f"size: {persona:<15} {size:>7} bytes ({share})"
                     + (f"; sliced {note['files']} of {note['of']} files, +{len(note['closure'])} by closure"
                        if note else ""))
    lines += [f"skipped: {persona}: {reason}" for persona, reason in skipped.items()]
    return lines


def record(review_dir: Path, sizes: dict[str, int], skipped: dict[str, str], sliced: dict[str, dict]) -> Path:
    """Merge the decisions and sizes into `manifest.json`, keeping whatever the manifest already holds."""
    target = review_dir / MANIFEST_FILE
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["personas"] = {
        "schema_version": SCHEMA_VERSION, "packaged": sorted(sizes), "bytes": sizes,
        "skipped": [{"persona": p, "reason": r} for p, r in sorted(skipped.items())],
        "sliced": {p: {"files": n["files"], "of": n["of"], "closure": n["closure"]} for p, n in sliced.items()},
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
