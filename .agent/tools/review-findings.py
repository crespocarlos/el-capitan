#!/usr/bin/env python3
"""Normalize review findings, persist review reports, and append outcome records.

Input finding JSON requires title and label; file, line, persona, evidence,
disposition, reason, and memory_ids are optional. `normalize` canonicalizes
persona names, fingerprints file|label-category|normalized-title with SHA-1,
and deduplicates exact fingerprints. `persist` writes the consolidated report
to the review directory and to the task-level REVIEW.md (self, changes, pr) or
REVIEW.<mode>.md (spec, idea) so code verdicts that crew-commit and
crew-address-review read are never overwritten, and appends deferred findings to DEFERRED.md.
`outcome` appends an immutable JSONL record whose `persona` is a list of
canonical names. `coverage` fails when a hunk id is unassigned, assigned twice, or
unknown to the hunk index; `validate-map` applies that rule plus the review-map contract
to a whole `review.json`, and `persist --strict` runs `coverage` whenever `layers.json`
sits next to `hunks.json`. `persist` requires `--review-dir` to be `<task>/review/<ts>`.
`select` prints the reviewer personas a review must dispatch. `persist` always
enforces persona coverage: a dispatched persona must have a real `.in.md` and
`.out.md`, and no artifact may be empty, a placeholder, or an orchestrator
summary in place of the persona's response. `normalize --strict` rejects emitted blocking/attention
findings without `verified` and `evidence`, more than MAX_FINDINGS emitted
findings, and more than MAX_NITS emitted nits (so polish cannot occupy a
severity slot). `--strict` adds the hunk-coverage and evidence-path gates, which
need a clean diff to check. `--personas` is separate from `--strict` so a PR
review can skip the diff gates while still proving every persona ran.
`--files` is an evidence allowlist, not a diff check: it records what was reviewed and
gates evidence paths against it. It is deliberately not compared with `git diff`, because
`persist` runs in three modes with no single base ref. Tree identity is `--head`, which
`crew-ls.py --mark-done` requires to be an ancestor of HEAD. In PR mode the head is the
GitHub SHA, which the local checkout never fetches, so `--head` is recorded without a
local existence check; it still belongs in every PR review. A PR review also gets a
warning when it persists into a task dir that has a SPEC.md, because a PR is not a task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
# Severity says how bad; `kind` says what sort of defect, and the two are independent. A security
# hole and a doc inaccuracy can both be `[attention]`, and a reader triaging a report needs to tell
# them apart without parsing prose. Kept separate from `fingerprint`: identity is "this defect in
# this file", so re-classifying a finding must not turn it into a second finding.
KINDS = {"security", "correctness", "reliability", "documentation", "testing", "other"}
OUTCOMES = {"fixed", "rejected", "deferred", "skipped"}
PERSONAS = {"adversarial", "architecture", "code-quality", "product-flow", "prompt-quality", "explorer"}
LEGACY_PERSONAS = {"fresh-eyes"}  # removed persona; kept so old review dirs still normalize
# Closed vocabulary for a leading `status:` line in `<persona>.out.md`. Only these three
# failure words are authoritative; anything else (`dispatched`, `done`) falls through to
# the content check, so a placeholder cannot claim a persona completed.
PERSONA_STATUSES = {"failed", "skipped", "truncated"}
CODE_MODES = {"self", "changes", "pr"}


def mode_arg(value: str) -> str:
    """Normalize a mode before the choices check, so `--mode PR` is accepted.

    The protocol names the mode `PR` while the CLI enumerates lowercase values, which made a
    correct review fail on an argparse error before any persona was dispatched. Accept the
    documented casing and the `auto`/`auto-loop` modifiers instead of failing the run.
    """
    normalized = value.strip().lower()
    for modifier in (" auto-loop", " auto", "-auto-loop", "-auto"):
        normalized = normalized.replace(modifier, "")
    return normalized


# Tiered output cap, counted separately so polish cannot evict severity. A flat cap of 7 counted a
# nit as equal to a blocking finding: measured over 65 persisted reviews it bound on 42% of runs, and
# one review emitted three nits while dropping an [attention] finding. Non-nit volume never exceeded
# 11 in that sample, and emitted nits never exceeded 4, so 12 + 4 binds on none of the 65 recorded
# reviews: a ceiling against runaway output that does not truncate real findings. Total output is at
# most 16.
MAX_FINDINGS = 12
MAX_NITS = 4
EMITTED = {"patch", "decide"}
EVIDENCE_LOCATION = re.compile(r"^[^:\s][^:]*:\d+(?:@[0-9a-f]{7,40})?$")
SELECT_RULES = {
    "prompt-quality": re.compile(r"(^|/)(agents|skills|evals)/|\.mdc$"),
    "architecture": re.compile(r"router|orchestrator|install|dispatch|tools\.json|(^|/)\.claude/"),
}
DISPOSITIONS = {"patch", "decide", "defer", "dropped", "merged"}


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def canonical_personas(value: object, *, split_commas: bool = True) -> list[str]:
    if not split_commas and isinstance(value, str) and "," in value:
        raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
    raw = value if isinstance(value, list) else str(value or "").split(",")
    result = []
    for item in raw:
        name = re.sub(r"\s+", "-", str(item).strip().lower()).removeprefix("reviewer-")
        if not split_commas and "," in str(item):
            raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
        if not name:
            continue
        if name not in PERSONAS | LEGACY_PERSONAS:
            raise ValueError(f"unknown persona: {item!r} (expected one of {sorted(PERSONAS)})")
        if name not in result:
            result.append(name)
    return result


def atomic_write(path: Path, text: str) -> None:
    """Write via a sibling temp file so an interrupted run cannot truncate REVIEW.md."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".review-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint(finding: dict) -> str:
    material = "|".join(
        [
            str(finding.get("file", "")).strip(),
            str(finding.get("label", "")).strip().lower(),
            normalized_title(str(finding["title"])),
        ]
    )
    return hashlib.sha1(material.encode()).hexdigest()


def read_findings(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        raise ValueError("finding input must be a JSON list or an object with a findings list")
    result = []
    for index, finding in enumerate(data, 1):
        if not isinstance(finding, dict) or not isinstance(finding.get("title"), str):
            raise ValueError(f"finding {index} requires a string title")
        label = str(finding.get("label", "")).lower()
        if label not in LABELS:
            raise ValueError(f"finding {index} has invalid label: {label!r}")
        disposition = finding.get("disposition")
        if disposition is not None and disposition not in DISPOSITIONS:
            raise ValueError(f"finding {index} has invalid disposition: {disposition!r}")
        normalized = {**finding, "label": label}
        # Optional: every review recorded before this field existed has no `kind`, and refusing those
        # would make the tool unable to re-read its own history. A typo is a different matter — an
        # unknown value is rejected so the vocabulary cannot drift one spelling at a time.
        if "kind" in finding:
            kind = str(finding["kind"]).strip().lower()
            if kind not in KINDS:
                raise ValueError(
                    f"finding {index} has invalid kind: {finding['kind']!r} "
                    f"(expected one of {', '.join(sorted(KINDS))})"
                )
            normalized["kind"] = kind
        if "persona" in finding or "personas" in finding:
            normalized.pop("personas", None)
            normalized["persona"] = canonical_personas(finding.get("persona", finding.get("personas")))
        result.append({**normalized, "fingerprint": fingerprint(normalized)})
    return result


def check_findings(findings: list[dict]) -> None:
    """Per-finding rules that need no changed-file list.

    Split out from `check_strict` because `persist` used to reach every per-finding rule only when
    `--files` carried at least one path, and a spec or idea review has no path list to pass. The
    result was a `verified: true` finding with no validation sentence persisting successfully in
    exactly the modes that pass no files, while both `TOOLS.md` and the consolidation protocol said
    the sentence was required.
    """
    for f in findings:
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
        if evidence is not None and not isinstance(evidence, str):
            # A type error is a caller bug, not an absent location: fail loudly rather than let the
            # file gate below skip a malformed value as though the finding had cited nothing.
            raise ValueError(
                f"finding {f['title']!r}: evidence must be a string path:line, got {type(evidence).__name__}"
            )
        if f.get("verified") is True:
            # `verified: true` asserts a second read happened. Without its conclusion recorded, the
            # next reader has only a boolean and an anchor and cannot tell why the check passed —
            # which is the reasoning the consolidator used to discard.
            validation = f.get("validation")
            if not isinstance(validation, str) or not validation.strip():
                raise ValueError(
                    f"finding {f['title']!r} is verified but records no validation sentence; "
                    "state what the verification read and concluded"
                )


def check_strict(findings: list[dict], files: list[str] | None = None) -> None:
    emitted = [f for f in findings if f.get("disposition") in EMITTED]
    check_findings(emitted)
    for f in emitted:
        evidence = f.get("evidence")
        if files and evidence:
            # Shape is not enough: evidence must point at something under review, or a
            # finding about an untouched file is reported as verified. A finding with no
            # evidence is allowed here — `blocking`/`attention` were already required to have
            # it above, and a nit may stay unanchored, so there is nothing to check.
            location = evidence.split("@", 1)[0].rsplit(":", 1)[0]
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


def normalize(args: argparse.Namespace) -> int:
    findings = read_findings(args.input)
    if args.strict and args.hunks:
        # Validate every candidate before deduplication: otherwise a duplicate's malformed
        # attribution is silently discarded, or its valid hunk never reaches the coverage report.
        check_hunk_refs(findings, hunk_ids(args.hunks))
    kept, duplicates = {}, []
    for finding in findings:
        existing = kept.get(finding["fingerprint"])
        if existing:
            for persona in finding.get("persona", []):
                if persona not in existing.setdefault("persona", []):
                    existing["persona"].append(persona)
            if isinstance(existing.get("hunks", []), list) and isinstance(finding.get("hunks", []), list):
                existing["hunks"] = list(dict.fromkeys(existing.get("hunks", []) + finding.get("hunks", [])))
            duplicates.append(
                {"fingerprint": finding["fingerprint"], "duplicate_of": existing["title"], "title": finding["title"]}
            )
        else:
            kept[finding["fingerprint"]] = finding
    if args.strict:
        check_strict(list(kept.values()), args.files)
    payload = {"findings": list(kept.values()), "duplicates": duplicates}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


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


# Reviewer personas do not all number their findings. `reviewer-code-quality`,
# `reviewer-product-flow`, and `reviewer-prompt-quality` document an unnumbered
# `**path — line N** — title` body closed by `Fix/Response:`, and `reviewer-explorer`
# returns a fixed set of `##` sections. A classifier that accepts only numbered findings
# would report every real response from those personas as no output and refuse the review.
EXPLORER_SECTIONS = (
    "## Similar patterns",
    "## Potential duplicates",
    "## Conflicting implementations",
    "## Prior art",
    "## Canonical approach",
    "## Cross-file consistency",
)
VERDICT_NO_FINDINGS = re.compile(r"^### Verdict:\s*no findings\s*$", re.M | re.I)
# A severity label plus a location anchor, in either order. Personas write the label at the start of
# the line (the mandated shape), inside leading bold, after a list bullet, or after the anchor as
# "`path:line` — [label] …"; all of these carry the same content, and rejecting one aborts the whole
# review at persist time. The anchor must still be a real path:line, so a bare label or a marker
# alone never matches.
_SEVERITY = r"(?:blocking|attention|concern|nit|needs more info)"
_ANCHOR = r"(?:`?[^`\n\s]+`?\s*:\s*\d+|—\s*line\s*\d+)"
# Optional list bullet, number, or bare ordinal. Personas use `-`, `*`, `1.`, `1)`, and `2 ` (no
# punctuation) interchangeably, and nine real review outputs were scored as no output purely for not
# using `1.`.
_BULLET = r"(?:[-*+]\s+)?(?:\d+[.)]?\s*)?"
LABELED_FINDING = re.compile(
    # label first: `1. [blocking] … path.ts:42`, `- **[attention]** … path.ts:42`
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[" + _SEVERITY + r"\][^\n]*?" + _ANCHOR
    # anchor first: `` 1. `path.ts:42` — [blocking] … ``
    + r"|^[ \t]*" + _BULLET + r"(?:\*\*)?`?[^`\n\s\[\]]+`?\s*:\s*\d+[^\n]*?\[" + _SEVERITY + r"\]",
    re.M | re.I,
)
# Findings whose anchor sits outside the label's line, so a line-local pattern cannot see them: a
# label followed by an `Anchor: path:line` line. Both shapes were scored as "no output" in real runs,
# and the artifact was then refused as a placeholder.
LABEL_LINE = re.compile(
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[(" + _SEVERITY + r")\]([^\n]*)", re.M | re.I
)
ANCHOR_ANYWHERE = re.compile(_ANCHOR, re.I)
FIX_RESPONSE_FINDING = re.compile(
    # The fix field has three documented spellings: `Fix:` is the consolidator's contract,
    # `Fix/Response:` is what code-quality and prompt-quality print, and `Suggested fix:` is what
    # adversarial and architecture printed until 2026-11-18. All three mark a documented finding, so
    # rejecting one refused real reviews as placeholders.
    r"(?ms)^\*\*.+?\*\*\s+—\s+\S.*?^(?:Suggested fix|Fix/Response|Fix):\s+\S"
)
EXPLORER_FINDING = re.compile(
    r"(?m)^(?:" + "|".join(re.escape(section) for section in EXPLORER_SECTIONS) + r")\s*$\n\s*-\s+\S"
)
# An orchestrator's own summary of a persona, written in place of the persona's response. The
# protocol forbids it ("never substitute a stub"), and it cannot be verified or re-graded later, so
# it is refused rather than accepted as output. 57 of 220 recorded artifacts were such digests, and
# they announced themselves in the opening 300 characters under five wordings: `(condensed)`,
# `# … (condensed relay)`, `Condensed record of …`, `status: complete (condensed; …)`, and
# `status: ok (condensed)`. The marker must read as an announcement — bare at the start, in
# parentheses/brackets, in a heading, or on a `status:` line — so a persona reviewing a prompt that
# happens to contain the word is unaffected.
SUMMARY_ARTIFACT = re.compile(
    r"\A\s*(?:#{1,6}[^\n]*)?\s*[(\[]?\s*(?:condensed|summari[sz]ed)\b"
    r"|^[ \t]*(?:#{1,6}[ \t]*)?[(\[]\s*(?:condensed|summari[sz]ed)\b"
    r"|^[ \t]*status:.*\b(?:condensed|summari[sz]ed)\b",
    re.I | re.M,
)
SUMMARY_HEADER_CHARS = 300
# How far past a label line its evidence may sit. Bounded at the next label when that is closer, and
# widened to this when a single long finding runs further, so neither a stray anchor far below can
# rescue a marker-only block nor a long finding lose its own `Anchor:` line.
ANCHOR_WINDOW = 2000
# A spec or idea review has one artifact under review, so its findings anchor by quoting the
# sentence they attack rather than by a path:line into a diff. Four real spec reviews were scored as
# "no output" for this alone.
QUOTED_EVIDENCE = re.compile(r"[\"“][^\"”\n]{20,}[\"”]")
# A spec or idea review cites the one artifact under review, so a finding may anchor to a bare line
# number or range instead of a path. Requiring a path there would reject a correct spec review, but
# the line number is still required: without it a long unanchored label line would pass as a finding.
# What separates a finding from a marker is described content past the number, so `[nit] 611` stays
# out while `2 [blocking] 611 (570-571): unscoped example contradicts the rule` is accepted.
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


def heading_lines(text: str) -> set[str]:
    """The level-3 heading lines of a report, ignoring fenced blocks.

    A finding may quote a heading verbatim (the contract requires quoting, not paraphrasing), and a
    sub-heading such as `#### Files reviewed` is a different section. Only an exact level-3 heading
    outside a fence means the caller wrote the generated section themselves.
    """
    headings: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("### "):
            headings.add(line.rstrip())
    return headings


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


def read_json_object(path: Path, key: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path} has no {key!r} list")
    return payload


SEVERITIES = {"high", "medium", "low", "nit"}
MAX_LAYERS = 8


def hunk_ids(path: Path) -> list[str]:
    entries = read_json_object(path, "hunks")["hunks"]
    if not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"{path}: every hunk must be an object")
    known = [entry.get("id") for entry in entries]
    if not all(isinstance(hunk_id, str) and hunk_id for hunk_id in known):
        raise ValueError(f"{path}: every hunk needs a string id")
    duplicated = sorted({hunk_id for hunk_id in known if known.count(hunk_id) > 1})
    if duplicated:
        raise ValueError(f"{path}: duplicate hunk ids: {', '.join(duplicated)}")
    return known


def check_layers(known: list[str], layers: object) -> tuple[list[str], list[str]]:
    """Every hunk id lands in exactly one layer, and no layer invents an id.

    A hunk nobody was asked to read is a coverage hole that no amount of persona output
    reveals, so this is an error rather than a warning.
    """
    if not isinstance(layers, list) or not layers:
        return ["layers must be a non-empty array of layer objects"], []
    errors: list[str] = []
    warnings: list[str] = []
    known_set, seen, layer_ids = set(known), {}, set()
    for index, layer in enumerate(layers, 1):
        where = f"layers[{index}]"
        if not isinstance(layer, dict):
            errors.append(f"{where} is not an object")
            continue
        layer_id = layer.get("id")
        if not isinstance(layer_id, str) or not layer_id.strip():
            errors.append(f"{where}.id is missing")
        elif layer_id in layer_ids:
            errors.append(f"{where}.id {layer_id!r} is duplicated")
        else:
            layer_ids.add(layer_id)
        if not isinstance(layer.get("explainer"), str) or not layer["explainer"].strip():
            errors.append(f"{where}.explainer is missing")
        if not isinstance(layer.get("reviewFocus"), str) or not layer["reviewFocus"].strip():
            errors.append(f"{where}.reviewFocus is missing")
        assigned = layer.get("hunks")
        if not isinstance(assigned, list) or not assigned:
            errors.append(f"{where}.hunks must be a non-empty list of hunk ids")
            continue
        for hunk_id in assigned:
            if not isinstance(hunk_id, str):
                errors.append(f"{where}.hunks has a non-string id {hunk_id!r}")
            elif hunk_id not in known_set:
                errors.append(f"{where} references unknown hunk {hunk_id!r}")
            elif hunk_id in seen:
                errors.append(
                    f"hunk {hunk_id} is in both {seen[hunk_id]} and {where}; "
                    "each hunk belongs to exactly one layer"
                )
            else:
                seen[hunk_id] = where
        notes = layer.get("hunkNotes", {})
        if not isinstance(notes, dict):
            errors.append(f"{where}.hunkNotes must be an object keyed by hunk id")
            notes = {}
        for note_id in notes:
            if note_id not in assigned:
                errors.append(f"{where}.hunkNotes has a note for {note_id}, which is not in its hunks")
    missing = [hunk_id for hunk_id in known if hunk_id not in seen]
    if missing:
        errors.append(f"{len(missing)} hunk(s) in no layer: {', '.join(missing)}")
    if len(layers) > MAX_LAYERS:
        errors.append(f"{len(layers)} layers exceeds the maximum of {MAX_LAYERS}")
    return errors, warnings


def check_coverage(hunks_path: Path, layers_path: Path) -> dict:
    """Every hunk id lands in exactly one layer, and no layer invents an id.

    Shared with `validate-map`, so a map that validates for `crew explain` cannot then be
    rejected by the persist gate.
    """
    known = hunk_ids(hunks_path)
    layers = read_json_object(layers_path, "layers")["layers"]
    errors, _ = check_layers(known, layers)
    if errors:
        raise ValueError("; ".join(errors))
    return {"hunks": len(known), "layers": len(layers)}


def check_hunk_refs(findings: list[dict], known: list[str]) -> None:
    """Emitted findings name the hunks whose change causes them, and only real ones.

    A blocking or attention finding that no hunk caused is about code the change did not
    touch, which consolidation routes to `defer`; a nit may stay unanchored.
    """
    known_set = set(known)
    for f in findings:
        if f.get("disposition") not in EMITTED:
            continue
        refs = f.get("hunks", [])
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError(f"finding {f['title']!r}: hunks must be a list of hunk ids")
        unknown = [ref for ref in refs if ref not in known_set]
        if unknown:
            raise ValueError(f"finding {f['title']!r} cites unknown hunk(s): {', '.join(unknown)}")
        if f["label"] in {"blocking", "attention"} and not refs:
            raise ValueError(
                f"{f['label']} finding {f['title']!r} cites no hunk; name the hunk(s) whose change "
                "causes it, or route it to defer"
            )


def layer_coverage(layers: list[dict], findings: list[dict]) -> str:
    emitted = [f for f in findings if f.get("disposition") in EMITTED]
    lines = ["### Coverage by layer"]
    for layer in layers:
        assigned = set(layer["hunks"])
        hits = [f for f in emitted if assigned & set(f.get("hunks", []))]
        result = "; ".join(f"[{f['label']}] {f['title']}" for f in hits) or "no findings"
        lines.append(f"- {layer.get('title') or layer['id']} ({', '.join(layer['hunks'])}): {result}")
    unmapped = [f for f in emitted if not f.get("hunks")]
    if unmapped:
        lines.append("- outside the map: " + "; ".join(f"[{f['label']}] {f['title']}" for f in unmapped))
    return "\n".join(lines) + "\n"


def coverage(args: argparse.Namespace) -> int:
    print(json.dumps(check_coverage(args.hunks, args.layers), sort_keys=True))
    return 0


def validate_map(args: argparse.Namespace) -> int:
    """Check a whole review map (summary, layers, concerns) against the hunk index.

    The contract `crew explain` writes and `crew review` reads, in one place, so a map
    that renders also passes the persist coverage gate.
    """
    review = read_json_object(args.review, "layers")
    known = hunk_ids(args.hunks)
    errors, warnings = check_layers(known, review["layers"])
    if not isinstance(review.get("summary"), str) or not review["summary"].strip():
        errors.append("summary must be a non-empty markdown string")
    if "context" in review and not isinstance(review["context"], str):
        errors.append("context must be a markdown string")
    if review.get("risk") is not None and review["risk"] not in ("low", "medium", "high"):
        errors.append("risk must be low, medium, or high")
    for index, concern in enumerate(review.get("concerns") or [], 1):
        where = f"concerns[{index}]"
        if not isinstance(concern, dict):
            errors.append(f"{where} is not an object")
            continue
        if not isinstance(concern.get("severity"), str) or concern["severity"] not in SEVERITIES:
            errors.append(f"{where}.severity must be one of {', '.join(sorted(SEVERITIES))}")
        for field in ("title", "detail"):
            if not isinstance(concern.get(field), str) or not concern[field].strip():
                errors.append(f"{where}.{field} is missing")
        if concern.get("hunk") is not None and (
                not isinstance(concern["hunk"], str) or concern["hunk"] not in known):
            errors.append(f"{where}.hunk {concern['hunk']!r} is not a hunk in the index")
    for index, reference in enumerate(review.get("references") or [], 1):
        where = f"references[{index}]"
        if not isinstance(reference, dict) or not isinstance(reference.get("title"), str):
            errors.append(f"{where}.title is missing")
        elif not reference.get("url") and not reference.get("path"):
            warnings.append(f"{where} has neither url nor path")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"review-findings: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "hunks": len(known),
                      "layers": len(review["layers"]), "warnings": len(warnings)},
                     sort_keys=True))
    return 0


def persist(args: argparse.Namespace) -> int:
    args.review_dir = args.review_dir.resolve()
    if args.review_dir.parent.name != "review":
        raise ValueError(f"--review-dir must be <task>/review/<timestamp>, got {args.review_dir}")
    owner = args.review_dir.parent.parent
    if args.mode == "pr" and not args.head.strip():
        raise ValueError("--mode pr requires --head with the reviewed GitHub SHA")
    if args.mode == "pr" and (owner / "SPEC.md").is_file():
        raise ValueError(
            "PR reviews must persist outside task state; use /tmp/crew-review-<repo>/review/<timestamp>"
        )
    findings = read_findings(args.findings) if args.findings else []
    coverage_section = ""
    # Persona evidence is not a strict-only gate. A report persisted without proof that each
    # dispatched persona ran is indistinguishable from a full review, and 18 recorded reviews
    # reached REVIEW.md that way while a persona had produced nothing. Requiring --personas at
    # every call makes the coverage check unconditional; --strict only adds the diff gates
    # (hunk coverage, evidence paths) that need a clean tree to check.
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
    layers_path = args.review_dir / LAYERS_FILE
    hunks_path = args.review_dir / HUNKS_FILE
    coverage_gap = ""
    if args.strict:
        # A layer map is what proves the personas were pointed at the whole diff: a hunk
        # nobody was asked to read is a silent coverage hole. Strict only, so a plain
        # persist never fails on a stray map.
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
    report = args.report.read_text()
    # Two sections are generated from the inputs below, so a report carrying its own copy would
    # render the same table twice — once verbatim in the body, once at the end — and a reader
    # cannot tell which is authoritative when they disagree. Refuse rather than strip: the
    # generated copy is derived from --findings and --files, so the hand-written one is always
    # wrong and its removal should be the caller's visible decision.
    #
    # Match a real level-3 heading only. A finding that quotes the heading — the contract requires
    # verbatim quoting — or a deeper `#### Files reviewed` is not a duplicate section, and the
    # substring test that preceded this rejected both.
    generated = [heading for heading in GENERATED_SECTIONS if heading in heading_lines(report)]
    if generated:
        raise ValueError(
            f"{args.report} already contains {', '.join(generated)}, which persist appends; "
            "delete it from the report and let persist write it"
        )
    if coverage_section:
        report = report.rstrip() + "\n\n" + coverage_section
    if coverage_gap:
        # stderr alone is invisible in the persisted artifact: 80 of 83 recorded reviews carried
        # hunks with no map and the report never said so. The gap belongs where the reader is.
        print(f"warning: {coverage_gap}", file=sys.stderr)
        report = report.rstrip() + f"\n\n### Coverage\n- {coverage_gap}\n"
    if args.files:
        report = report.rstrip() + "\n\n### Files reviewed\n" + "".join(f"- `{name}`\n" for name in args.files)
    # Bind the verdict to the tree it approved. `crew commit` moves HEAD past it, so the
    # gate in `crew-ls --mark-done` accepts a reviewed ancestor only; recording the SHA
    # still makes a review of a *different* tree detectable.
    if args.head:
        head = args.head.strip()
        if not re.fullmatch(r"[0-9a-f]{7,40}", head):
            raise ValueError(f"--head must be a commit SHA, got {head!r}")
        # Accept a reviewed ancestor: the documented order commits after review, so an
        # exact-HEAD match would fail every first attempt at --mark-done. Verify the SHA
        # exists here so a wrong-repo SHA is rejected at write time, not at close-out.
        # PR mode is the exception: the reviewed tree is the GitHub head and the local
        # checkout never fetches it, so a local existence check rejects every PR review
        # *after* the persona artifacts are written. Record the identity; do not resolve it.
        if args.mode != "pr":
            exists = subprocess.run(["git", "cat-file", "-e", f"{head}^{{commit}}"],
                                    capture_output=True)
            if exists.returncode:
                raise ValueError(f"--head {head} is not a commit in this repository")
        report = report.rstrip() + f"\n\nReviewed at: {head}\n"
    if args.strict:
        # Per-finding rules always; the path-scoped evidence gate only when a path set exists. A spec
        # or idea review passes no paths, and gating the whole check on `--files` silently skipped
        # the `validation` requirement in exactly those modes.
        check_findings([f for f in findings if f.get("disposition") in EMITTED])
        if args.files:
            check_strict([f for f in findings if f.get("disposition") in EMITTED], args.files)
    rows = [f for f in findings if f.get("disposition") == "defer"]
    args.review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(args.review_dir / "REVIEW.md", report)
    task_report = "REVIEW.md" if args.mode in CODE_MODES else f"REVIEW.{args.mode}.md"
    atomic_write(owner / task_report, report)
    deferred = len(rows)
    if rows:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = owner / "DEFERRED.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        with path.open("a", encoding="utf-8") as handle:
            for f in rows:
                where = f"{f.get('file', '')}:{f.get('line', '')}".strip(":")
                reason = f.get("reason", "pre-existing or out of scope")
                if f"[{f['label']}] {f['title']} — `{where}`" in existing:
                    continue
                handle.write(f"- [{stamp}] [{f['label']}] {f['title']} — `{where}` — {reason}\n")
    print(json.dumps({"review": str(owner / task_report), "deferred": deferred}))
    return 0


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


def outcome(args: argparse.Namespace) -> int:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "review_dir": str(args.review_dir),
        "fingerprint": args.fingerprint,
        "persona": canonical_personas(args.persona),
        "label": args.label,
        "outcome": args.outcome,
        "reason": args.reason,
        "memory_ids": args.memory_id,
    }
    target = args.review_dir.parent / "outcomes.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("input", type=Path)
    normalize_parser.add_argument("--output", type=Path)
    normalize_parser.add_argument("--strict", action="store_true")
    normalize_parser.add_argument("--hunks", type=Path,
                                  help="hunks.json; with --strict, emitted findings must cite real hunk ids")
    normalize_parser.add_argument("--files", nargs="*", default=[],
                                  help="reviewed paths; strict evidence must point inside this set")
    persist_parser = commands.add_parser("persist")
    persist_parser.add_argument("--review-dir", required=True, type=Path)
    persist_parser.add_argument("--report", required=True, type=Path)
    persist_parser.add_argument("--findings", type=Path)
    persist_parser.add_argument("--mode", type=mode_arg,
                                choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    persist_parser.add_argument("--files", nargs="*", default=[])
    persist_parser.add_argument("--strict", action="store_true")
    persist_parser.add_argument("--personas", nargs="*", default=[])
    persist_parser.add_argument("--head", default="", help="reviewed commit SHA recorded as `Reviewed at:`")
    select_parser = commands.add_parser("select")
    select_parser.add_argument("--mode", required=True, type=mode_arg,
                               choices=sorted(CODE_MODES | {"spec", "idea"}))
    select_parser.add_argument("--paths", nargs="*", default=[])
    select_parser.add_argument("--contract", action="store_true", help="a spec or PR contract supplies acceptance criteria")
    select_parser.add_argument("--compat", action="store_true", help="the change alters behavior of an existing consumer")
    coverage_parser = commands.add_parser("coverage")
    coverage_parser.add_argument("--hunks", required=True, type=Path,
                                 help="hunks.json from review-hunks.py")
    coverage_parser.add_argument("--layers", required=True, type=Path,
                                 help="layers.json written by the reviewer-layers pre-pass")
    validate_parser = commands.add_parser("validate-map")
    validate_parser.add_argument("--review", required=True, type=Path,
                                 help="review.json written by crew explain")
    validate_parser.add_argument("--hunks", required=True, type=Path,
                                 help="hunks.json the map was built from")
    spec_parser = commands.add_parser("spec-context",
                                      help="print the part of SPEC.md one persona's package carries")
    spec_parser.add_argument("--persona", required=True)
    spec_parser.add_argument("spec", type=Path)
    packages_parser = commands.add_parser("check-packages",
                                          help="check written <persona>.in.md packages before dispatch")
    packages_parser.add_argument("--review-dir", required=True, type=Path)
    packages_parser.add_argument("--personas", nargs="+", required=True)
    packages_parser.add_argument("--mode", type=mode_arg,
                                 choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    packages_parser.add_argument("--spec", type=Path, help="defaults to <task>/SPEC.md")
    outcome_parser = commands.add_parser("outcome")
    outcome_parser.add_argument("--review-dir", required=True, type=Path)
    outcome_parser.add_argument("--fingerprint", required=True)
    outcome_parser.add_argument("--persona", required=True)
    outcome_parser.add_argument("--label", required=True, choices=sorted(LABELS))
    outcome_parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    outcome_parser.add_argument("--reason", required=True)
    outcome_parser.add_argument("--memory-id", action="append", default=[])
    args = parser.parse_args()
    handlers = {"normalize": normalize, "persist": persist, "select": select,
                "outcome": outcome, "coverage": coverage, "validate-map": validate_map,
                "spec-context": spec_context, "check-packages": check_packages}
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
