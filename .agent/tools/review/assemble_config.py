#!/usr/bin/env python3
"""The per-run judgement a package build reads: its config, the mode block, and guidance narrowing.

Per-run decisions stay in `assemble.json` in the review directory, not in code: the repository root,
the mode block, the size gate, the consumer excerpts, the prompt files, and which guidance sections
each lens keeps. A missing key means "no such section", and the mode block falls back to the label
vocabulary and return shape only, because a package with no mode leaves a persona without its legal
labels.

Narrowing is opt-in and never silent. A keep-list that matches no section would drop everything and
still produce a package that looks assembled, so it raises instead, naming the sections that do
exist. Every dropped heading is reported for the same reason: a lens given the wrong sections loses
a rule it needed, and nothing downstream can tell.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MODE = """# Mode

Label vocabulary: `[blocking]`, `[attention]`, `[needs more info]`, `[nit]`, and `[concern]` in place
of `[attention]` in a spec or idea review.

**Return shape:** reply text only. Do not write files and do not summarize into a separate block. A
flat numbered list of findings, each beginning with its severity label and carrying a `path:line`
anchor. If you have no findings, end your reply with the exact line `### Findings: none`.
"""
# The extras that read the local checkout, which a PR review forbids. `prior_review_dir` names a
# local run directory, so a PR package carrying it would hand a persona an earlier review of a
# different tree — and PR reviews have no task-level round to compare against anyway.
INDEX_READING_KEYS = ("consumers", "prompt_files", "prior_review_dir")


def read_json(path: Path, what: str) -> dict:
    """A JSON object from the review directory, failing with a message that names the file.

    A stale or truncated artifact written by an earlier revision would otherwise raise a traceback
    out of the middle of the build, after some packages were built.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SystemExit(f"assemble-packages: cannot read {what} at {path}: {error}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"assemble-packages: {path} is not valid JSON: {error}")
    if not isinstance(payload, dict):
        raise SystemExit(f"assemble-packages: {path} must hold a JSON object")
    return payload


def read_config(review_dir: Path, config: Path | None) -> dict:
    """The run config, or an empty mapping when the directory carries none."""
    path = config or review_dir / "assemble.json"
    if not path.is_file():
        return {}
    return read_json(path, "the run config")


def check_inputs(review_dir: Path, config: dict) -> str:
    """A missing prerequisite or a PR-mode leak, as an error message; "" when the run may proceed.

    A PR review reads only the PR head, and both extras come from the local git index, so a PR
    package carrying them would hand a persona checkout code the mode forbids, unlabelled.
    """
    for required in ("package.diff", "hunks.index.md"):
        if not (review_dir / required).is_file():
            return f"{review_dir} has no {required}; run review-hunks.py first"
    if config.get("mode_kind") == "pr":
        leaked = [key for key in INDEX_READING_KEYS if config.get(key)]
        if leaked:
            return (f"{', '.join(leaked)} read the local git index, which PR mode "
                    "forbids; fetch those excerpts at the PR head and put them in the dispatch prompt")
    return ""


def keep_sections(content: str, keep: list[str], used: set[str]) -> tuple[str, list[str], list[str]]:
    """The kept body, kept headings, and dropped headings for one guidance file.

    A level-2 heading switches inclusion on or off for the lines under it; headings that matched
    a keep prefix are recorded in `used` so an unmatched prefix can be reported by the caller.
    """
    body_lines: list[str] = []
    kept_headings: list[str] = []
    dropped_headings: list[str] = []
    dropping = False
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            matched = [prefix for prefix in keep if heading.startswith(prefix)]
            used.update(matched)
            dropping = not matched
            (dropped_headings if dropping else kept_headings).append(heading)
        if not dropping:
            body_lines.append(line)
    return "\n".join(body_lines).strip(), kept_headings, dropped_headings


def narrow_guidance(persona: str, guidance: dict, config: dict) -> tuple[str, dict]:
    """Repository guidance, optionally narrowed to the sections a lens uses, plus a report.

    Narrowing is opt-in through `guidance_keep` in `assemble.json`, keyed by persona and listing
    level-2 heading prefixes. The text before the first heading is always kept, a persona with no
    entry or `"*"` keeps the whole file, and every dropped heading is reported: a lens given the
    wrong sections silently loses a rule it needed, so a silent cut is the failure mode here.
    """
    keep = (config.get("guidance_keep") or {}).get(persona)
    out: list[str] = []
    report: dict = {"kept": {}, "dropped": {}, "available": [], "unmatched": []}
    used: set[str] = set()
    for path, content in guidance.items():
        available = [line[3:].strip() for line in content.splitlines() if line.startswith("## ")]
        report["available"].extend(available)
        if not keep or "*" in keep:
            out.append(f"## From `{path}`\n\n{content}\n\n")
            report["kept"][path] = "*"
            report["dropped"][path] = []
            continue
        body, kept_headings, dropped_headings = keep_sections(content, keep, used)
        if body:
            out.append(f"## From `{path}`\n\n{body}\n\n")
        report["kept"][path] = kept_headings
        report["dropped"][path] = dropped_headings
    if keep and "*" not in keep:
        report["unmatched"] = [prefix for prefix in keep if prefix not in used]
        if report["unmatched"]:
            # A keep-list naming a section that does not exist drops everything, and the package
            # then looks assembled. Refuse instead: this is the exact silent loss narrowing must
            # not have.
            raise ValueError(
                f"guidance_keep for {persona} names no section in any guidance file: "
                f"{', '.join(report['unmatched'])}. Available: {', '.join(report['available'][:20])}"
            )
    return "".join(out), report


def contract_path() -> Path:
    """The shared contract this repository ships, whether run from the repo or an installed symlink."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".cursor" / "agents" / "references" / "reviewer-contract.md"
        if candidate.is_file():
            return candidate
    return Path.home() / ".cursor" / "agents" / "references" / "reviewer-contract.md"
