"""What a review covered: persona selection and coverage, the package rules, and the persist gates.

Coverage: each dispatched persona produced output. A `<persona>.in.md` carries no builder sections of
the spec (Product Flow excepted) and no generated-file hunks. Persist always checks persona evidence;
`--strict` adds the diff gates (layer map, hunk references, package rules). An absent input is skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from review_layers import check_coverage, check_hunk_refs, hunk_ids, layer_coverage
from review_vocabulary import (
    ASSESSMENT_WORDS,
    CODE_MODES,
    SELECT_RULES,
    assessment_of,
    canonical_personas,
    persona_outcome,
)

from lib.files import read_json_object
from lib.output import bounded_json

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


def select(args: argparse.Namespace) -> int:
    """The lenses a change requires, each with the reason it was selected."""
    required = {}
    if args.mode in CODE_MODES:
        required["code-quality"] = "code review"
        required["adversarial"] = "code review"
        for persona, pattern in SELECT_RULES.items():
            hits = [path for path in args.paths if pattern.search(path)]
            if hits:
                required[persona] = f"paths: {', '.join(hits[:3])}"
        if args.compat:
            required.setdefault("architecture", "--compat")
    else:
        # Specs and ideas have no diff to review, so the lenses are fixed rather than
        # derived from paths; otherwise the selection is empty and nothing is dispatched.
        required["product-flow"] = "plan coherence"
        required["adversarial"] = "plan failure modes"
        required.setdefault("architecture", "plan boundaries and compatibility")
    if args.contract:
        required["product-flow"] = "--contract"
    payload = {"required": sorted(required), "reasons": required}
    print(bounded_json(payload, args.max_chars, what="selected personas"))
    return 0


def spec_context(args: argparse.Namespace) -> int:
    """Print the part of SPEC.md one persona's package carries."""
    persona = canonical_personas([args.persona], split_commas=False)[0]
    sys.stdout.write(spec_for(persona, args.spec.read_text(encoding="utf-8")))
    return 0


def check_packages(args: argparse.Namespace) -> int:
    """Check written `<persona>.in.md` packages before dispatch."""
    review_dir = args.review_dir.resolve()
    if review_dir.parent.name != "review" and not args.spec:
        raise ValueError(
            f"--review-dir must be <task>/review/<timestamp> (got {review_dir}); "
            "pass --spec when the directory is laid out differently"
        )
    spec = args.spec or review_dir.parent.parent / "SPEC.md"
    violations, report = package_violations(review_dir, args.personas, args.mode, spec,
                                            review_dir / HUNKS_FILE)
    if not report["read"]:
        violations.append(f"no <persona>.in.md found in {review_dir} for {', '.join(args.personas)}")
    for violation in violations:
        print(f"review-findings: {violation}", file=sys.stderr)
    if not violations:
        print(json.dumps({"ok": True, "packages": len(report["read"]), "skipped": report["skipped"]}))
    return 1 if violations else 0


ASSESSMENT_REQUEST = "## Assessment of the change"
# The clause after the word is what makes the assessment worth reading; a bare `approve` is refused.
ASSESSMENT_CLAUSE_MIN = 20


def check_personas_present(args: argparse.Namespace) -> None:
    """Require a persona list and both artifacts for each, then prove each one produced output."""
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
    check_persona_coverage(args.review_dir, args.personas)


def check_assessments(review_dir: Path, personas: list[str]) -> dict:
    """Require an assessment from every persona that ran and whose package asked for one.

    Only packages carrying `ASSESSMENT_REQUEST` are gated. The section is in the shared contract, so
    a packaged run has it and a directory written before the rule existed does not: gating on the
    package rather than on the persona keeps archived reviews persistable exactly as they were, and a
    missing line in a package that asked for one is a real gap.

    A persona that declared a failure (`status: failed|skipped|truncated`) is reported under
    `unavailable` rather than gated: the documented recovery keeps it in `--personas` and names it in
    the report, so demanding a judgement from a run that never finished turns recovery into an error.

    Returns `{"assessed": {persona: (word, clause)}, "skipped": {persona: reason},
    "unavailable": {persona: outcome}}`, so the renderer consumes the parsed verdicts instead of
    re-reading every reply.
    """
    assessed: dict[str, tuple[str, str]] = {}
    skipped: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    for persona in canonical_personas(personas, split_commas=False):
        package = review_dir / f"{persona}.in.md"
        if not package.is_file():
            continue
        outcome = persona_outcome(review_dir / f"{persona}.out.md")
        if outcome != "ok":
            unavailable[persona] = outcome
            continue
        if ASSESSMENT_REQUEST not in package.read_text(encoding="utf-8", errors="replace"):
            skipped[persona] = "package does not request an assessment"
            continue
        found = assessment_of(
            (review_dir / f"{persona}.out.md").read_text(encoding="utf-8", errors="replace"))
        if found is None:
            raise ValueError(
                f"{persona} wrote no `Assessment:` line with one of "
                f"{', '.join(ASSESSMENT_WORDS)}, and its package asks for one; a review that judges "
                "only the lines misses whether the change is the right one"
            )
        if len(found[1]) < ASSESSMENT_CLAUSE_MIN:
            raise ValueError(
                f"{persona} stated `Assessment: {found[0]}` with a {len(found[1])}-character clause; "
                f"the clause is what a reader acts on, so it needs at least {ASSESSMENT_CLAUSE_MIN} "
                "characters of evidence"
            )
        assessed[persona] = found
    return {"assessed": assessed, "skipped": skipped, "unavailable": unavailable}


def strict_gates(args: argparse.Namespace, owner: Path, findings: list[dict]) -> tuple[str, str]:
    """Under `--strict`, enforce the layer, hunk, and package gates.

    Returns the coverage section to append and the coverage gap to report. A layer map is what
    proves the personas were pointed at the whole diff, so a hunk nobody was asked to read is a
    silent hole rather than a style point.
    """
    layers_path = args.review_dir / LAYERS_FILE
    hunks_path = args.review_dir / HUNKS_FILE
    coverage_section = coverage_gap = ""
    if layers_path.is_file():
        if not hunks_path.is_file():
            raise ValueError(
                f"{layers_path} has no sibling {HUNKS_FILE}; a layer map without a hunk index cannot be checked"
            )
        check_coverage(hunks_path, layers_path)
        coverage_section = layer_coverage(read_json_object(layers_path, "layers")["layers"], findings)
    elif hunks_path.is_file():
        coverage_gap = (
            f"{HUNKS_FILE} has no {LAYERS_FILE}: hunk coverage was not enforced, so no layer of "
            "this diff is proven to have been read"
        )
    if hunks_path.is_file():
        check_hunk_refs(findings, hunk_ids(hunks_path))
    # Directories written before package.diff existed hold diff.patch and the full spec, so the
    # package rules only apply to a review that was packaged under them.
    if (args.review_dir / "package.diff").is_file():
        violations, _ = package_violations(args.review_dir, args.personas, args.mode,
                                           owner / "SPEC.md", hunks_path)
        if violations:
            raise ValueError("; ".join(violations))
    return coverage_section, coverage_gap
