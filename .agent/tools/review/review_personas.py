#!/usr/bin/env python3
"""Persona concerns: output classification, selection, coverage, packages, and spec context.

Split out of `review-findings.py`. Everything here answers a question about reviewers rather
than about findings: which lenses to dispatch, whether each one actually produced output, and
what a persona package must contain. Depends on `findings.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from review_findings import (
    CODE_MODES,
    PERSONA_STATUSES,
    SELECT_RULES,
    canonical_personas,
    read_json_object,
)


def persona_outcome(path: Path) -> str:
    """Classify a persona artifact: ok, failed, skipped, truncated, summarized, missing, unknown.

    Only the leading block is read, so a persona quoting `status: failed` from the
    finding it reviews cannot flip a good run. The documented success signal is a
    verdict line or a complete labeled finding; an empty artifact is `unknown`, not
    `ok`, because the failure this guards against is a persona that died silently.
    Only `failed|skipped|truncated` are read from a `status:` line. Any other word
    (`dispatched`, `done`, `complete`) is not a success claim, so it falls through to the
    content check and a placeholder without a verdict stays `unknown`.

    `summarized` is an orchestrator's condensed digest written in place of the persona's
    response. It is a separate outcome from `unknown` because the artifact does contain
    findings, but nothing in it is attributable to the persona or re-verifiable later, so
    persistence refuses it and names the real cause instead of "no output".
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "missing"
    if not text.strip():
        return "unknown"
    # An orchestrator summary is not the persona's response, whatever it says. Checked before the
    # status line so `status: ok (condensed) …` cannot pass as a completed persona.
    if SUMMARY_ARTIFACT.search(text[:SUMMARY_HEADER_CHARS]):
        return "summarized"
    declared = re.match(r"\s*(?:#+[^\n]*\n+\s*)?status:\s*(\w+)", text)
    if declared:
        word = declared.group(1).lower()
        # Failure words are authoritative; any other word (`dispatched`, `done`) is
        # not a success claim, so fall through to the content check below.
        if word in PERSONA_STATUSES:
            return word
    return "ok" if has_review_content(text) else "unknown"


# Reviewer personas do not all number their findings: three document an unnumbered
# `**path — line N** — title` body closed by `Fix/Response:`, and explorer returns `##` sections.
EXPLORER_SECTIONS = (
    "## Similar patterns",
    "## Potential duplicates",
    "## Conflicting implementations",
    "## Prior art",
    "## Canonical approach",
    "## Cross-file consistency",
)
VERDICT_NO_FINDINGS = re.compile(r"^### Verdict:\s*no findings\s*$", re.M | re.I)
# A severity label plus a location anchor, in either order: label first, inside leading bold, after a
# bullet, or after the anchor. All carry the same content, and rejecting one aborts the review; the
# anchor must still be a real `path:line`, so a bare label or a marker alone never matches.
_SEVERITY = r"(?:blocking|attention|concern|nit|needs more info)"
_ANCHOR = r"(?:`?[^`\n\s]+`?\s*:\s*\d+|—\s*line\s*\d+)"
# Optional list bullet, number, or bare ordinal: personas use `-`, `*`, `1.`, `1)`, and `2 ` alike.
_BULLET = r"(?:[-*+]\s+)?(?:\d+[.)]?\s*)?"
LABELED_FINDING = re.compile(
    # label first: `1. [blocking] … path.ts:42`, `- **[attention]** … path.ts:42`
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[" + _SEVERITY + r"\][^\n]*?" + _ANCHOR
    # anchor first: `` 1. `path.ts:42` — [blocking] … ``
    + r"|^[ \t]*" + _BULLET + r"(?:\*\*)?`?[^`\n\s\[\]]+`?\s*:\s*\d+[^\n]*?\[" + _SEVERITY + r"\]",
    re.M | re.I,
)
# Findings whose anchor sits on an `Anchor: path:line` line rather than the label's own line.
LABEL_LINE = re.compile(
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[(" + _SEVERITY + r")\]([^\n]*)", re.M | re.I
)
ANCHOR_ANYWHERE = re.compile(_ANCHOR, re.I)
FIX_RESPONSE_FINDING = re.compile(
    # Three documented spellings of the fix field: `Fix:`, `Fix/Response:`, and `Suggested fix:`.
    # Rejecting any one of them refused real reviews as placeholders.
    r"(?ms)^\*\*.+?\*\*\s+—\s+\S.*?^(?:Suggested fix|Fix/Response|Fix):\s+\S"
)
EXPLORER_FINDING = re.compile(
    r"(?m)^(?:" + "|".join(re.escape(section) for section in EXPLORER_SECTIONS) + r")\s*$\n\s*-\s+\S"
)
# An orchestrator's own digest written in place of a persona's response. The protocol forbids it and
# it cannot be verified or re-graded later, so it is refused rather than accepted as output. The
# marker must read as an announcement — bare, bracketed, in a heading, or on a `status:` line — so a
# persona reviewing a prompt that merely contains the word is unaffected.
SUMMARY_ARTIFACT = re.compile(
    r"\A\s*(?:#{1,6}[^\n]*)?\s*[(\[]?\s*(?:condensed|summari[sz]ed)\b"
    r"|^[ \t]*(?:#{1,6}[ \t]*)?[(\[]\s*(?:condensed|summari[sz]ed)\b"
    r"|^[ \t]*status:.*\b(?:condensed|summari[sz]ed)\b",
    re.I | re.M,
)
SUMMARY_HEADER_CHARS = 300
# How far past a label line its evidence may sit, so neither a stray anchor far below can rescue a
# marker-only block nor a long finding lose its own `Anchor:` line.
ANCHOR_WINDOW = 2000
# A spec or idea review has one artifact under review, so its findings anchor by quoting the sentence
# they attack rather than by a `path:line` into a diff.
QUOTED_EVIDENCE = re.compile(r"[\"“][^\"”\n]{20,}[\"”]")
# A spec review cites the one artifact under review, so a finding may anchor to a bare line number or
# range. The number is still required, and described content must follow it, or `[nit] 611` would pass.
SPEC_FINDING = re.compile(
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[" + _SEVERITY + r"\][\s*:—–-]*"
    r"\(?\s*\d[\d,\s–-]*\)?[\d,\s–\-:()]*\**\s*[A-Za-z\"“][^\n]{40,}",
    re.M | re.I,
)


def has_findings(text: str) -> bool:
    """True when the artifact carries at least one credited finding.

    Separate from `has_review_content` because the two answer different questions. A verdict line
    says "nothing to report"; a finding says the opposite. A persona can emit both — six anchored
    findings followed by `### Verdict: no findings` was observed in a real PR review — and a
    classifier that treats the verdict token as authoritative discards grounded work. Content wins:
    the verdict line is a signal for an empty review, never a cancellation of findings above it.
    """
    if LABELED_FINDING.search(text) or FIX_RESPONSE_FINDING.search(text):
        return True
    if EXPLORER_FINDING.search(text) or SPEC_FINDING.search(text):
        return True
    labels = list(LABEL_LINE.finditer(text))
    for index, match in enumerate(labels):
        # End the block at the next label, as the artifact's own structure implies, and in any case no
        # earlier than ANCHOR_WINDOW past the label line: a long finding may put its `Anchor:` further
        # down than the next label is far away, and truncating it would refuse a real finding.
        next_label = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        block = text[match.start():max(next_label, match.end() + ANCHOR_WINDOW)]
        if ANCHOR_ANYWHERE.search(block) or QUOTED_EVIDENCE.search(block):
            return True
    return False


def has_review_content(text: str) -> bool:
    """True when the artifact carries a verdict, a finding, or explorer sections.

    Each accepted shape requires content beyond a marker: a complete no-findings verdict, a
    labeled finding with a location, an unnumbered documented finding closed by any of the three
    fix-field spellings, or an explorer section plus an item. A placeholder (`raw response
    captured`, `dispatched: yes`) and marker-only output match none.

    A finding is credited by evidence, not by layout: a `path:line` anchor in the same block, an
    `Anchor:` line, a quoted sentence from the artifact under review, or a bare line number with a
    body. Four real spec reviews and five bullet-style code reviews were refused as placeholders
    because the accepted shape was narrower than the format the persona documents.
    """
    if VERDICT_NO_FINDINGS.search(text):
        return True
    return has_findings(text)


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
    # persona ends as `ok` or an explicit failure word (pipeline.md step 3). `unknown`
    # means the file carries no verdict, no labeled finding, and no declared failure.
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


HUNKS_FILE = "hunks.json"
LAYERS_FILE = "layers.json"
# The two sections `persist` appends. A report must not carry either, or it renders twice.
GENERATED_SECTIONS = ("### Coverage by layer", "### Files reviewed")

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


def spec_for(persona: str, spec: str) -> str:
    if persona in SPEC_FULL_PERSONAS:
        return spec
    kept, builder = spec_sections(spec)
    text = "\n".join(kept).rstrip() + "\n"
    if builder:
        text += "\n_Tasks and Hints omitted: implementation steps are Product Flow's to check._\n"
    return text


# A single qualifying line can recur legitimately in repository guidance or memory, so one match is
# not proof the spec's builder sections were copied; two are.
SPEC_COPIED_LINES = 2


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
                              "build its spec with `review-findings.py spec-context`")
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


def select(args: argparse.Namespace) -> int:
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
    print(json.dumps({"required": sorted(required), "reasons": required}, indent=2, sort_keys=True))
    return 0


def spec_context(args: argparse.Namespace) -> int:
    persona = canonical_personas([args.persona], split_commas=False)[0]
    sys.stdout.write(spec_for(persona, args.spec.read_text(encoding="utf-8")))
    return 0


def check_packages(args: argparse.Namespace) -> int:
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
