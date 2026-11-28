"""Persisting a review report and gating it against the findings JSON.

`persist` writes the report and the task's REVIEW file, appends deferred findings, enforces the persona
and layer gates, derives the generated sections and records the reviewed commit. With `--findings`, the
model-written numbered list may not drop, re-label or re-score a finding, and the verdict must match.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from crew.lib.files import atomic_write
from crew.lib.git import GitError, rev_parse
from crew.review import review_pr_plan as comments
from crew.review import review_records as records
from crew.review.review_coverage import check_assessments, check_personas_present, check_probe, strict_gates
from crew.review.review_findings import check_findings, check_strict, read_findings, strict_mode
from crew.review.review_models import Finding
from crew.review.review_render import GENERATED_SECTIONS, Trail, assessment_section, capped, footer, heading_lines, with_banner, with_reviewers
from crew.review.review_render import check as check_provenance
from crew.review.review_vocabulary import ANCHOR, CODE_MODES, SEVERITY, verdict, without_fences
from crew.review.review_workspace import record_task_review
from crew.task.task_status import verdict_word

# One numbered finding's opening line: an ordinal, then the bracketed label and its optional score.
# Punctuation after the ordinal and bold around the label are both optional, because `review_vocabulary`
# credits `2 [attention · 4]` and `2. **[attention · 4]**`; the ordinal itself stays required, or a
# prose mention of a label would count as a finding and inflate the count.
ENTRY = re.compile(r"^[ \t]*\d+[.)]?[ \t]*(?:\*\*)?\[(?P<label>" + SEVERITY + r")\]", re.MULTILINE | re.IGNORECASE)
SCORE = re.compile(r"·\s*([1-5])\s*$")
CODE_VERDICTS = {"pass": "PASS", "warn": "WARN", "block": "BLOCK"}
# A spec or idea review scores the plan, so its verdict word differs. `revisit` is the reviewer's word
# for "not ready", which a plan with concerns is: it maps to `BLOCK` or `WARN`, whichever the findings
# derive, because a concern-only review that must claim `proceed` would be forced to overstate.
PLAN_VERDICTS = {"proceed": None, "revisit": None, "blocked": "BLOCK"}
# Words whose meaning is decided by the findings rather than fixed: `proceed` is true only of a plan
# with nothing blocking, and `revisit` of one that is not clean either.
DERIVED = {"proceed", "revisit"}


def anchor_pair(text: str) -> tuple[str, int] | None:
    """The `(path, line)` a fragment anchors to, whichever of the documented spellings it uses.

    `path:line`, `` `path:line` ``, and the legacy `path — line N` all reduce to the same pair, so the
    migration that rewrites the documents cannot turn an archived report into a mismatch.

    The line is read from after the *last* colon, never as the first digit run in the fragment: a path
    may carry digits of its own — `report-2026-11-25.md:9` is line 9 of a dated file, not line 2026 —
    and taking the first run made every finding against a dated filename unpersistable.
    """
    for match in re.finditer(ANCHOR, text, re.IGNORECASE):
        fragment = match.group(0)
        if ":" in fragment:
            path, _, tail = fragment.rpartition(":")
            digits = re.match(r"\s*(\d+)\s*$", tail)
            if digits is None:
                continue
            path = path.strip("`* ")
            number = int(digits.group(1))
        else:
            # The legacy form names the line only, so the path is the token just before it.
            digits = re.search(r"\d+", fragment)
            if digits is None:
                continue
            before = text[: match.start()].rstrip().split(" ")
            path = before[-1].strip("`* ") if before and before[-1] else ""
            number = int(digits.group(0))
        if path:
            return (path, number)
    return None


def finding_anchor(finding) -> tuple[str, int] | None:
    """The anchor a finding record carries: `file` with `line`, or the location in its evidence."""
    path = finding.text("file").strip().strip("`")
    line = finding.text("line").strip()
    if path and line.isdigit():
        return (path, int(line))
    return anchor_pair(finding.text("evidence"))


def entry_blocks(report: str) -> list[dict]:
    """Each numbered finding in the report, with the label, score, and anchor it states. A quoted (`>`) line is a
    finding's prose (`consolidate --render` quotes each body), never its label or anchor."""
    body = "".join("\n" if line.lstrip().startswith(">") else line for line in without_fences(report).splitlines(keepends=True))
    matches = list(ENTRY.finditer(body))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        bracket = match.group("label")
        score = SCORE.search(bracket)
        blocks.append(
            {
                "line": body[: match.start()].count("\n") + 1,
                "label": SCORE.sub("", bracket).strip().lower(),
                "score": int(score.group(1)) if score else None,
                "anchor": anchor_pair(body[match.start() : end]),
            }
        )
    return blocks


def finding_score(finding) -> int | None:
    """The score a finding record carries, or None when it was written before the field existed."""
    return finding.confidence if isinstance(finding.confidence, int) else None


def check_list(report: str, emitted: list) -> str | None:
    """The first disagreement between the report's numbered list and the emitted findings."""
    blocks = entry_blocks(report)
    if len(blocks) != len(emitted):
        return f"the report lists {len(blocks)} numbered finding(s), but {len(emitted)} emitted finding(s) were persisted"
    for index, (block, finding) in enumerate(zip(blocks, emitted), 1):
        where = f"report finding {index} (line {block['line']})"
        label = str(finding.label).strip().lower()
        if block["label"] != label:
            return f"{where} is labelled [{block['label']}], but the persisted finding is [{label}]"
        score = finding_score(finding)
        if block["score"] != score:
            return f"{where} states score {block['score'] or 'none'}, but the persisted finding carries {score if score is not None else 'none'}"
        if block["anchor"] != finding_anchor(finding):
            return f"{where} is anchored at {block['anchor']}, but the persisted finding is anchored at {finding_anchor(finding)}"
    return None


def stated_verdict(report: str) -> tuple[str, str] | None:
    """The last `Verdict:` line outside a fence (`verdict_word`) as `(as written, lowercased)`, or None."""
    word = verdict_word(without_fences(report))
    return (word, word.lower()) if word else None


def plan_outcome(word: str, derived: str) -> str | None:
    """The outcome a plan word claims, or None when its meaning is the findings' to decide.

    `blocked` is fixed: it always means the plan is not ready. `proceed` and `revisit` are relative —
    `proceed` is true only of a plan with nothing blocking, `revisit` of one that is not clean — so
    their outcome is `derived`, and the check below is what refuses the pairings they deny:
    `proceed` against `BLOCK`, `revisit` against `PASS`.
    """
    if word in DERIVED:
        return None if word == "proceed" else derived
    return PLAN_VERDICTS[word]


def expected_verdict(report: str, findings: list, mode: str, degraded: bool = False) -> str | None:
    """The verdict the report states, mapped onto `PASS`/`WARN`/`BLOCK`, or None when it states none.

    ValueError when the word is outside the mode's vocabulary or contradicts the findings; a
    degraded review derives its `PASS` as `WARN`.
    """
    stated = stated_verdict(report)
    if stated is None:
        return None
    written, word = stated
    derived = capped(verdict(findings), degraded)
    if mode in CODE_MODES:
        if word not in CODE_VERDICTS:
            raise ValueError(f"the report states Verdict: {written}, which is not a {mode} verdict (expected one of {', '.join(sorted(CODE_VERDICTS))})")
        mapped = CODE_VERDICTS[word]
    else:
        if word not in PLAN_VERDICTS:
            raise ValueError(f"the report states Verdict: {written}, which is not a {mode} verdict (expected one of {', '.join(sorted(PLAN_VERDICTS))})")
        mapped = plan_outcome(word, derived)
        if word == "proceed" and derived == "BLOCK":
            raise ValueError(f"the report states Verdict: {written}, but its findings derive BLOCK; a plan with a blocking finding has not proceeded")
        if word == "revisit" and derived == "PASS":
            raise ValueError(f"the report states Verdict: {written}, but its findings derive PASS; there is nothing to revisit")
    if mapped is not None and mapped != derived:
        raise ValueError(
            f"the report states Verdict: {written}, but its findings derive {derived}"
            f"{' (degraded review: capped at WARN)' if degraded else ''}; "
            "one of the two is wrong and neither can be trusted until they agree"
        )
    return mapped if mapped is not None else derived


def check_report(report: str, findings: list, mode: str, degraded: bool = False) -> None:
    """Raise ValueError naming the first disagreement between a report and the findings it cites."""
    emitted = [finding for finding in findings if finding.is_emitted()]
    problem = check_list(report, emitted)
    if problem:
        raise ValueError(problem)
    expected_verdict(report, emitted, mode, degraded)


def validate_review_dir(args: argparse.Namespace) -> Path:
    """Resolve `--review-dir` and return the task directory it belongs to."""
    args.review_dir = args.review_dir.resolve()
    if args.review_dir.parent.name != "review":
        raise ValueError(f"--review-dir must be <task>/review/<timestamp>, got {args.review_dir}")
    owner = args.review_dir.parent.parent
    if args.mode in ("self", "changes") and not args.findings:
        raise ValueError(f"--mode {args.mode} requires --findings: the report and probe gates read it")
    if args.mode == "pr" and not args.head.strip():
        raise ValueError("--mode pr requires --head with the reviewed GitHub SHA")
    if args.mode == "pr" and (owner / "SPEC.md").is_file():
        raise ValueError("PR reviews must persist outside task state; use /tmp/crew-review-<repo>/review/<timestamp>")
    return owner


def reviewed_head(args: argparse.Namespace) -> str:
    """The reviewed commit after checking the SHA is real, or "" when none was passed.

    `crew commit` moves HEAD past the reviewed tree, so the gate downstream accepts an ancestor;
    recording the SHA still makes a review of a *different* tree detectable. PR mode is the
    exception: the reviewed tree is the GitHub head and the local checkout never fetches it, so a
    local existence check would reject every PR review. Only the validated value comes back: the
    footer is the one place a report states it, so a second append site cannot disagree.
    """
    if not args.head:
        return ""
    head = args.head.strip()
    if not re.fullmatch(r"[0-9a-f]{7,40}", head):
        raise ValueError(f"--head must be a commit SHA, got {head!r}")
    if args.mode != "pr":
        try:
            rev_parse(None, f"{head}^{{commit}}")
        except GitError:
            raise ValueError(f"--head {head} is not a commit in this repository") from None
    return head


def append_deferred(owner: Path, rows: list[Finding]) -> dict[str, int]:
    """Record the deferred and dropped findings beside the report; see `review_records`."""
    return records.append(owner, rows)


def assemble_report(
    args: argparse.Namespace,
    report: str,
    coverage_section: str,
    coverage_gap: str,
    findings: list[Finding],
    head: str,
    assessments_section: str = "",
    degraded: bool = False,
) -> str:
    """The report body with its generated sections and the decision footer, appended in order.

    Every generated section arrives as a parameter, computed by `persist`, so this function's
    signature names its inputs and reads as "the body plus everything derived from it". `Reviewed
    at:` is skipped when `--head` was empty, but a local review still gets its next step. Hanging the
    footer off the commit instead would leave exactly those reviews with no next step a reader could
    find.

    The derived `Verdict:` line is written only when findings were supplied. With no `--findings`
    there is no comparison, and a verdict derived from an empty list would be `PASS` on a report whose
    own body may say `BLOCK` — a second, unchecked claim stamped on the one path the gate cannot see.
    """
    # The generated sections are derived from --findings, --files, and the persona replies, so a
    # report carrying its own copy would render the table twice and a reader could not tell which is
    # authoritative. Match a real level-3 heading only: a finding may quote one verbatim.
    generated = [heading for heading in GENERATED_SECTIONS if heading in heading_lines(report)]
    if generated:
        raise ValueError(f"{args.report} already contains {', '.join(generated)}, which persist appends; delete it from the report and let persist write it")
    if assessments_section:
        report = report.rstrip() + "\n\n" + assessments_section
    if coverage_section:
        report = report.rstrip() + "\n\n" + coverage_section
    if coverage_gap:
        # stderr alone is invisible in the persisted artifact: the report must say the map is
        # missing, or a reader of REVIEW.md sees a clean review of a partially read diff.
        print(f"warning: {coverage_gap}", file=sys.stderr)
        report = report.rstrip() + f"\n\n### Coverage\n- {coverage_gap}\n"
    if args.files:
        report = report.rstrip() + "\n\n### Files reviewed\n" + "".join(f"- `{name}`\n" for name in args.files)
    step = footer(findings, head, args.mode, args.next, derived=bool(args.findings), degraded=degraded)
    return report.rstrip() + "\n\n" + step + "\n"


def persona_gates(args: argparse.Namespace) -> tuple[str, str, Trail]:
    """Run the persona gates; `(body with any degraded banner, generated sections, trail)`."""
    check_personas_present(args)
    trail = check_provenance(args.review_dir, args.personas)
    sections = "\n".join(part for part in (assessment_section(check_assessments(args.review_dir, args.personas)), trail.section) if part)
    body = with_reviewers(args.report.read_text(encoding="utf-8"), trail.reviewers)
    return (with_banner(body, trail.degraded) if trail.degraded else body), sections, trail


def persist(args: argparse.Namespace) -> int:
    """Write the report, the coverage section, and the deferred findings, after every gate."""
    owner = validate_review_dir(args)
    findings = read_findings(args.findings) if args.findings else []
    body, assessments_section, trail = persona_gates(args)
    head = reviewed_head(args)
    coverage_section = coverage_gap = ""
    strict = strict_mode(args)
    if strict:
        coverage_section, coverage_gap = strict_gates(args, owner, findings)
    report = assemble_report(args, body, coverage_section, coverage_gap, findings, head, assessments_section, bool(trail.degraded))
    if strict:
        # Per-finding rules always; the path-scoped evidence gate only when a path set exists. A spec
        # or idea review passes no paths, and gating the whole check on `--files` silently skipped
        # the `validation` requirement in exactly those modes.
        check_findings([f for f in findings if f.is_emitted()])
        if args.files:
            check_strict([f for f in findings if f.is_emitted()], args.files)
    if args.findings:
        # The body, not the assembled report: the footer states the derived verdict, so comparing it
        # would let any contradiction in the model's own list pass its own gate.
        check_report(body, findings, args.mode, bool(trail.degraded))
        check_probe(args.review_dir, body, findings, args.mode)
    rows = [f for f in findings if f.disposition in records.RECORDED_DISPOSITIONS]
    args.review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(args.review_dir / "REVIEW.md", report)
    task_report = "REVIEW.md" if args.mode in CODE_MODES else f"REVIEW.{args.mode}.md"
    atomic_write(owner / task_report, report)
    record_task_review(str(owner), args.review_dir)
    counts = append_deferred(owner, rows) if rows else {}
    records.record_cost(None if args.mode == "pr" else owner, args.review_dir, (args.review_dir / "layers.json").is_file())
    written = [str(owner / task_report)]
    drafted = comments.write_for_mode(args.review_dir, findings, args.mode, args.head)
    if drafted:
        written.append(str(drafted))
    # A PR review's `comments.md` is its deliverable. Reporting it as absent in the JSON — rather than
    # only on stderr — is what stops Step 8 from describing a review whose findings never reach the PR.
    missing_comments = args.mode == "pr" and not drafted
    print(
        json.dumps(
            {
                "review": written[0],
                "deferred": sum(1 for f in rows if f.disposition == "defer"),
                "dropped": sum(1 for f in rows if f.disposition == "dropped"),
                "appended": counts.get("DEFERRED.md", 0) + counts.get("DROPPED.md", 0),
                **({"degraded": trail.degraded} if trail.degraded else {}),
                **({"comments": written[1]} if len(written) > 1 else {}),
                **({"comments_missing": True} if missing_comments else {}),
            }
        )
    )
    return 0


def check_outcomes(args: argparse.Namespace) -> int:
    """Report what a review recorded, and fail when an acted finding has no outcome.

    Exit 1, not 2: the command ran and found a gap in the run's own bookkeeping, which is a
    finding rather than an unusable invocation. A summary that claimed success while a decision it
    made went unrecorded is exactly the drift this exists to make visible.
    """
    review_dir = args.review_dir.resolve()
    if not review_dir.is_dir():
        raise ValueError(f"{review_dir} is not a review directory")
    recorded = records.summary(review_dir)
    missing = records.missing(review_dir, args.acted)
    payload = {**recorded, "acted": len(args.acted), "missing": missing}
    print(json.dumps(payload, sort_keys=True))
    return 1 if missing else 0


def outcome(args: argparse.Namespace) -> int:
    """Append one audit record for a finding's outcome, carrying the score it was decided under."""
    return records.append_outcome(args)
