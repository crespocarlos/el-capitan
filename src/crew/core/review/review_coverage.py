"""What a review covered: persona selection and coverage, the package rules, and the persist gates.

Coverage: each dispatched persona produced output. A `<persona>.in.md` carries no builder sections of
the spec (Product Flow excepted), no generated-file hunks, and (before dispatch) its lens questions. Persist
checks persona evidence; `--strict` adds the diff gates (layer map, hunk references, package rules). An absent
input is skipped. The probe gate: an unsettled self or changes finding needs the probe reply or a skip line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from crew.core.review.review_layers import check_coverage, check_hunk_refs, hunk_ids, layer_coverage
from crew.core.review.review_render import read_record
from crew.core.review.review_vocabulary import (
    ASSESSMENT_WORDS,
    CODE_MODES,
    PROBE,
    QUESTIONS_HEADING,
    QUESTIONS_MAX,
    QUESTIONS_MIN,
    QUESTIONS_STAMP,
    assessment_of,
    canonical_personas,
    persona_outcome,
    selected,
)
from crew.core.review.review_workspace import MANIFEST_FILE
from crew.lib.files import read_json_object
from crew.lib.output import bounded_json

HUNKS_FILE = "hunks.json"
LAYERS_FILE = "layers.json"

# Implementation steps in a spec: Product Flow checks them against the diff; to every other lens they are cost.
SPEC_BUILDER_SECTION = re.compile(r"^## (Tasks|Hints)\b")
SPEC_FULL_PERSONAS = frozenset({"product-flow"})
# A copied task line is long (a shorter one could match the diff by accident), and one such line can recur in
# guidance or memory, so two are the proof the builder sections were copied.
SPEC_LINE_MIN = 40
SPEC_COPIED_LINES = 2
# reviewer-reads.md's heading: a hand-built spec or idea package without it has no tool budget or lookups pointer.
CONTRACT_READS_HEADING = "## Finding things in the codebase"


def check_persona_coverage(review_dir: Path, personas: list[str]) -> None:
    """A review where no persona actually ran proves nothing about the change."""
    outcomes = {persona: persona_outcome(review_dir / f"{persona}.out.md") for persona in canonical_personas(personas, split_commas=False)}
    # `unknown` counts as usable only when the artifact actually carries review content;
    # persona_outcome already returns `unknown` for an empty file.
    unusable = {"failed", "skipped", "truncated", "summarized", "missing", "unknown"}
    if all(outcome in unusable for outcome in outcomes.values()):
        raise ValueError("every dispatched persona failed, was skipped, was summarized, or produced no output; there is no review to persist")
    # A placeholder artifact must not ride along behind one real persona: each declared
    # persona ends as `ok` or an explicit failure word. `unknown` means the file carries no
    # verdict, no labeled finding, and no declared failure.
    summarized = sorted(name for name, outcome in outcomes.items() if outcome == "summarized")
    if summarized:
        raise ValueError(
            f"{', '.join(summarized)} holds an orchestrator summary, not the persona's response; write the raw response as it returned, never a condensed digest"
        )
    stubs = sorted(name for name, outcome in outcomes.items() if outcome in {"unknown", "missing"})
    if stubs:
        raise ValueError(
            f"{', '.join(stubs)} produced no output or a placeholder; write the real response or declare `status: failed|skipped|truncated` before persisting"
        )


def package_violations(review_dir: Path, personas: list[str], mode: str, spec_path: Path | None, hunks_path: Path | None) -> tuple[list[str], dict]:
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
        builder_lines = {
            line.strip()
            for line in spec_sections(spec_path.read_text(encoding="utf-8"))[1]
            if len(line.strip()) >= SPEC_LINE_MIN and not line.startswith("## ")
        }
    else:
        report["skipped"]["spec"] = "no SPEC.md"
    generated: set[str] = set()
    if hunks_path and hunks_path.is_file():
        # Only a filename match is collapsed into package.diff; older hunks.json lacks `byName`.
        generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"] if entry.get("byName", entry.get("generated"))}
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
                errors.append(
                    f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); build its spec with `crew-review-findings.py spec-context`"
                )
        current = ""
        for line in lines:
            if line.startswith("diff --git "):
                # git quotes a header whose path has spaces or non-ASCII characters.
                current = next((path for path in generated if line.endswith((f" b/{path}", f' "b/{path}"'))), "")
            elif current and line.startswith("@@"):
                errors.append(f"{package.name} embeds hunks of generated file {current}; embed package.diff instead of diff.patch")
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
    """The lenses a change requires, each with the reason it was selected (`review_vocabulary.selected`)."""
    required = selected(args.mode, args.paths, args.contract, args.compat)
    print(bounded_json({"required": sorted(required), "reasons": required}, args.max_chars, what="selected personas"))
    return 0


def spec_context(args: argparse.Namespace) -> int:
    """Print the part of SPEC.md one persona's package carries."""
    persona = canonical_personas([args.persona], split_commas=False)[0]
    sys.stdout.write(spec_for(persona, args.spec.read_text(encoding="utf-8")))
    return 0


# An unindented list item: a nested bullet under a question is part of that question.
QUESTION_LINE = re.compile(r"^(?:\d+[.)]|[-*+])[ \t]+\S")


def questions_stamped(review_dir: Path) -> bool:
    """True when the assembler that wrote these packages records the questions rule in `manifest.json`."""
    try:
        record = json.loads((review_dir / MANIFEST_FILE).read_text(encoding="utf-8")).get("personas") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(record, dict) and record.get(QUESTIONS_STAMP) is True


def question_violations(review_dir: Path, personas: list[str], report: dict) -> list[str]:
    """Each stamped package carries `QUESTIONS_HEADING` (the last one counts, since a pasted prompt may quote it)
    with `QUESTIONS_MIN` to `QUESTIONS_MAX` unindented list items under it.

    Only a directory the current assembler stamped is held to it; an older one (a resume included) passes with a
    note under `skipped`. Pre-dispatch only: `persist` does not repeat it.
    """
    if not questions_stamped(review_dir):
        report["skipped"]["questions"] = "packages not stamped by the assembler's questions rule; not checked"
        return []
    errors = []
    for persona in canonical_personas(personas, split_commas=False):
        package = review_dir / f"{persona}.in.md"
        if not package.is_file():
            continue
        text = package.read_text(encoding="utf-8", errors="replace")
        lines = [line.rstrip() for line in text.splitlines()]
        if QUESTIONS_HEADING not in lines:
            errors.append(
                f"{package.name} has no `{QUESTIONS_HEADING}` section; write {QUESTIONS_MIN} to {QUESTIONS_MAX} questions for this lens from the diff and the spec's risks (assemble.json `questions`)"
            )
            continue
        body = lines[len(lines) - lines[::-1].index(QUESTIONS_HEADING) :]
        end = next((index for index, line in enumerate(body) if line.startswith(("#", "---"))), len(body))
        count = sum(bool(QUESTION_LINE.match(line)) for line in body[:end])
        if not QUESTIONS_MIN <= count <= QUESTIONS_MAX:
            errors.append(f"{package.name} asks {count} question(s) under `{QUESTIONS_HEADING}`; write {QUESTIONS_MIN} to {QUESTIONS_MAX}, one list item each")
    return errors


def check_packages(args: argparse.Namespace) -> int:
    """Check written `<persona>.in.md` packages before dispatch."""
    review_dir = args.review_dir.resolve()
    if review_dir.parent.name != "review" and not args.spec:
        raise ValueError(f"--review-dir must be <task>/review/<timestamp> (got {review_dir}); pass --spec when the directory is laid out differently")
    spec = args.spec or review_dir.parent.parent / "SPEC.md"
    violations, report = package_violations(review_dir, args.personas, args.mode, spec, review_dir / HUNKS_FILE)
    violations += question_violations(review_dir, args.personas, report)
    violations += [
        f"{name} has no `{CONTRACT_READS_HEADING}` section: append reviewer-reads.md to reviewer-contract.md"
        for name in report["read"]
        if args.mode not in CODE_MODES and CONTRACT_READS_HEADING not in (review_dir / name).read_text(encoding="utf-8", errors="replace").splitlines()
    ]
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
        raise ValueError("--personas is required: a persisted review must name the personas that produced it")
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
        found = assessment_of((review_dir / f"{persona}.out.md").read_text(encoding="utf-8", errors="replace"))
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
            raise ValueError(f"{layers_path} has no sibling {HUNKS_FILE}; a layer map without a hunk index cannot be checked")
        check_coverage(hunks_path, layers_path)
        coverage_section = layer_coverage(read_json_object(layers_path, "layers")["layers"], findings)
    elif hunks_path.is_file():
        coverage_gap = f"{HUNKS_FILE} has no {LAYERS_FILE}: hunk coverage was not enforced, so no layer of this diff is proven to have been read"
    if hunks_path.is_file():
        check_hunk_refs(findings, hunk_ids(hunks_path))
    # Directories written before package.diff existed hold diff.patch and the full spec, so the
    # package rules only apply to a review that was packaged under them.
    if (args.review_dir / "package.diff").is_file():
        violations, _ = package_violations(args.review_dir, args.personas, args.mode, owner / "SPEC.md", hunks_path)
        if violations:
            raise ValueError("; ".join(violations))
    return coverage_section, coverage_gap


PROBE_RECORD = f"{PROBE}.out.md"
# Only "the probe cannot run here" excuses a missing probe; any other reason is the gate being skipped.
PROBE_SKIP_REASONS = ("no-runtime", "no-network", "pr-only", "external-service")
PROBE_SKIPPED = re.compile(r"^[ \t>*-]*probe: skipped\b[ \t]*(?P<rest>.*)$", re.MULTILINE | re.IGNORECASE)
PROBE_SKIP_VALID = re.compile(r"(?:" + "|".join(PROBE_SKIP_REASONS) + r"):[ \t]*\S", re.IGNORECASE)
SAVE_PROBE = "`crew-review-findings.py save-out --review-dir <dir> --persona probe --harness <name>`"


def probe_saved(review_dir: Path) -> str:
    """'' when `probe.out.md` is a non-empty reply matching its save-out record, else what is wrong."""
    reply = review_dir / PROBE_RECORD
    if not reply.is_file() or not reply.read_bytes().strip():
        return "missing"
    record = read_record(review_dir, PROBE)
    if record is None or hashlib.sha256(reply.read_bytes()).hexdigest() != record["sha256"]:
        return f"{PROBE_RECORD} has no matching provenance record; save the reply with {SAVE_PROBE}"
    return ""


def check_probe(review_dir: Path, report: str, findings: list, mode: str) -> None:
    """A self or changes review emitting an unsettled finding (`[needs more info]`, score 1-2) shows its
    probe: the reply saved by `save-out --persona probe`, or a `probe: skipped <reason>: <detail>` line
    whose reason says the probe cannot run here, with every unsettled finding left `[needs more info]`.
    PR mode never probes."""
    if mode not in ("self", "changes"):
        return
    unsettled = [f for f in findings if f.is_emitted() and (f.label == "needs more info" or (isinstance(f.confidence, int) and f.confidence <= 2))]
    saved = probe_saved(review_dir) if unsettled else ""
    if not saved:
        return
    skips = [match.group("rest") for match in PROBE_SKIPPED.finditer(report)]
    if not skips and saved != "missing":
        raise ValueError(saved)
    reasons = f"`probe: skipped <reason>: <detail>`, reason one of {', '.join(PROBE_SKIP_REASONS)}"
    if not skips:
        raise ValueError(
            f"unsettled finding(s) {', '.join(repr(f.title) for f in unsettled)} need the reviewer-probe run: save its reply with {SAVE_PROBE}, or, when the probe cannot run here, state {reasons}"
        )
    invalid = [rest for rest in skips if not PROBE_SKIP_VALID.match(rest)]
    if invalid:
        raise ValueError(f"`probe: skipped {invalid[0]}` is not a reason the probe cannot run; write {reasons}, or run the probe")
    settled = [f.title for f in unsettled if f.label != "needs more info"]
    if settled:
        raise ValueError(f"a skipped probe settles nothing: label {', '.join(map(repr, settled))} `[needs more info]`")
