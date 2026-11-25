#!/usr/bin/env python3
"""Persona coverage and the package rules: which lenses ran, and what a package must contain.

Coverage asks whether each persona that was dispatched actually produced output, because a review
where nobody ran proves nothing about the change. The package rules ask whether a written
`<persona>.in.md` is worth dispatching: it must not carry the spec's builder sections (Product Flow's
to check, pure cost for every other lens) and must not embed hunks of a generated file. A check whose
input is absent is skipped, and the report says so rather than claiming a clean pass.

The other gate over a persona's reply — did it state a judgement on the change — is the assessment
gate in `review_persist_gates`, which owns the sections `persist` generates as well.
"""
from __future__ import annotations

import re
from pathlib import Path

from review_classify import persona_outcome
from review_models import read_json_object
from review_vocabulary import CODE_MODES, canonical_personas

HUNKS_FILE = "hunks.json"
LAYERS_FILE = "layers.json"

# Implementation steps in a spec. Product Flow checks them against the diff; every other lens
# judges the change against the summary and acceptance criteria, so these sections are pure cost
# in its package (18 KB of a measured 156 KB package, sent to every persona).
SPEC_BUILDER_SECTION = re.compile(r"^## (Tasks|Hints)\b")
SPEC_FULL_PERSONAS = frozenset({"product-flow"})
# A copied task line is long; a shorter line could match the diff by accident.
SPEC_LINE_MIN = 40
# A single qualifying line can recur legitimately in repository guidance or memory, so one match is
# not proof the spec's builder sections were copied; two are.
SPEC_COPIED_LINES = 2


def check_persona_coverage(review_dir: Path, personas: list[str]) -> None:
    """A review where no persona actually ran proves nothing about the change."""
    outcomes = {persona: persona_outcome(review_dir / f"{persona}.out.md")
                for persona in canonical_personas(personas, split_commas=False)}
    # `unknown` counts as usable only when the artifact actually carries review content;
    # persona_outcome already returns `unknown` for an empty file.
    unusable = {"failed", "skipped", "truncated", "summarized", "missing", "unknown"}
    if all(outcome in unusable for outcome in outcomes.values()):
        raise ValueError(
            "every dispatched persona failed, was skipped, was summarized, or produced no output; "
            "there is no review to persist"
        )
    # A placeholder artifact must not ride along behind one real persona: each declared
    # persona ends as `ok` or an explicit failure word. `unknown` means the file carries no
    # verdict, no labeled finding, and no declared failure.
    summarized = sorted(name for name, outcome in outcomes.items() if outcome == "summarized")
    if summarized:
        raise ValueError(
            f"{', '.join(summarized)} holds an orchestrator summary, not the persona's response; "
            "write the raw response as it returned, never a condensed digest"
        )
    stubs = sorted(name for name, outcome in outcomes.items() if outcome in {"unknown", "missing"})
    if stubs:
        raise ValueError(
            f"{', '.join(stubs)} produced no output or a placeholder; write the real response "
            "or declare `status: failed|skipped|truncated` before persisting"
        )


def package_violations(review_dir: Path, personas: list[str], mode: str,
                       spec_path: Path | None, hunks_path: Path | None) -> tuple[list[str], dict]:
    """Packaging rules a persona package must meet before it is worth dispatching.

    Returns the violations and a report of what the check could not do: a check whose input is
    absent is skipped, and the caller must be able to say so rather than report a clean pass.
    """
    errors: list[str] = []
    report: dict = {"read": [], "skipped": {}}
    builder_lines: set[str] = set()
    if mode not in CODE_MODES:
        report["skipped"]["spec"] = f"not applied in {mode} mode"
    elif spec_path and spec_path.is_file():
        builder_lines = {line.strip() for line in spec_sections(spec_path.read_text(encoding="utf-8"))[1]
                         if len(line.strip()) >= SPEC_LINE_MIN and not line.startswith("## ")}
    else:
        report["skipped"]["spec"] = "no SPEC.md"
    generated: set[str] = set()
    if hunks_path and hunks_path.is_file():
        # Only a filename match is collapsed into package.diff; older hunks.json lacks `byName`.
        generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"]
                     if entry.get("byName", entry.get("generated"))}
    else:
        report["skipped"]["hunks"] = "no hunks.json"
    for persona in canonical_personas(personas, split_commas=False):
        package = review_dir / f"{persona}.in.md"
        if not package.is_file():
            continue
        report["read"].append(package.name)
        lines = package.read_text(encoding="utf-8", errors="replace").splitlines()
        if persona not in SPEC_FULL_PERSONAS and builder_lines:
            copied = builder_lines.intersection(line.strip() for line in lines)
            if len(copied) >= SPEC_COPIED_LINES:
                errors.append(f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); "
                              "build its spec with `crew-review-findings.py spec-context`")
        current = ""
        for line in lines:
            if line.startswith("diff --git "):
                # git quotes a header whose path has spaces or non-ASCII characters.
                current = next((path for path in generated
                                if line.endswith((f" b/{path}", f' "b/{path}"'))), "")
            elif current and line.startswith("@@"):
                errors.append(f"{package.name} embeds hunks of generated file {current}; "
                              "embed package.diff instead of diff.patch")
                current = ""
    return errors, report


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


def spec_for(persona: str, spec: str) -> str:
    """The spec a persona's package carries; Product Flow gets all of it, every other lens not."""
    if persona in SPEC_FULL_PERSONAS:
        return spec
    kept, builder = spec_sections(spec)
    text = "\n".join(kept).rstrip() + "\n"
    if builder:
        text += "\n_Tasks and Hints omitted: implementation steps are Product Flow's to check._\n"
    return text
