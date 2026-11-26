#!/usr/bin/env python3
"""Gating a persisted review report: its numbered list and its verdict must match the findings JSON.

`persist` appends generated sections from `--findings`, but the numbered list at the top of the
report is written by a model and was checked by nothing: a finding could be dropped from the list a
reader acts on, re-labelled, or re-scored, while the JSON and every downstream count kept the truth.
The label and anchor vocabularies come from `review_classify`, so this gate and the persona
classifier cannot disagree about what a finding line is.

The gate only runs when `--findings` was supplied. Spec and idea reviews legitimately persist a
report with no JSON beside it, and comparing those against nothing would reject every one.
"""
from __future__ import annotations

import re

from review_classify import ANCHOR, SEVERITY, without_fences
from review_degraded import capped
from review_vocabulary import CODE_MODES, verdict

# One numbered finding's opening line: an ordinal, then the bracketed label and its optional score.
# Punctuation after the ordinal and bold around the label are both optional, because `review_classify`
# credits `2 [attention · 4]` and `2. **[attention · 4]**`; the ordinal itself stays required, or a
# prose mention of a label would count as a finding and inflate the count.
ENTRY = re.compile(
    r"^[ \t]*\d+[.)]?[ \t]*(?:\*\*)?\[(?P<label>" + SEVERITY + r")\]", re.MULTILINE | re.IGNORECASE
)
SCORE = re.compile(r"·\s*([1-5])\s*$")
# The last `Verdict:` line wins, because a report's decision is the one it closes on; `##`, bold, and
# a bare line are all spellings a real report used.
VERDICT_LINE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?Verdict:(?:\*\*)?[ \t]*([A-Za-z]+)", re.MULTILINE | re.IGNORECASE
)
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
            before = text[:match.start()].rstrip().split(" ")
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
    """Each numbered finding in the report, with the label, score, and anchor it states."""
    body = without_fences(report)
    matches = list(ENTRY.finditer(body))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        bracket = match.group("label")
        score = SCORE.search(bracket)
        blocks.append({
            "line": body[:match.start()].count("\n") + 1,
            "label": SCORE.sub("", bracket).strip().lower(),
            "score": int(score.group(1)) if score else None,
            "anchor": anchor_pair(body[match.start():end]),
        })
    return blocks


def finding_score(finding) -> int | None:
    """The score a finding record carries, or None when it was written before the field existed."""
    return finding.confidence if isinstance(finding.confidence, int) else None


def check_list(report: str, emitted: list) -> str | None:
    """The first disagreement between the report's numbered list and the emitted findings."""
    blocks = entry_blocks(report)
    if len(blocks) != len(emitted):
        return (f"the report lists {len(blocks)} numbered finding(s), but {len(emitted)} emitted "
                f"finding(s) were persisted")
    for index, (block, finding) in enumerate(zip(blocks, emitted), 1):
        where = f"report finding {index} (line {block['line']})"
        label = str(finding.label).strip().lower()
        if block["label"] != label:
            return f"{where} is labelled [{block['label']}], but the persisted finding is [{label}]"
        score = finding_score(finding)
        if block["score"] != score:
            return (f"{where} states score {block['score'] or 'none'}, but the persisted finding "
                    f"carries {score if score is not None else 'none'}")
        if block["anchor"] != finding_anchor(finding):
            return (f"{where} is anchored at {block['anchor']}, but the persisted finding is "
                    f"anchored at {finding_anchor(finding)}")
    return None


def stated_verdict(report: str) -> tuple[str, str] | None:
    """The last `Verdict:` line as `(as written, lowercased)`, or None when the report has none."""
    matches = VERDICT_LINE.findall(without_fences(report))
    if not matches:
        return None
    return matches[-1], matches[-1].lower()


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
            raise ValueError(
                f"the report states Verdict: {written}, which is not a {mode} verdict "
                f"(expected one of {', '.join(sorted(CODE_VERDICTS))})"
            )
        mapped = CODE_VERDICTS[word]
    else:
        if word not in PLAN_VERDICTS:
            raise ValueError(
                f"the report states Verdict: {written}, which is not a {mode} verdict "
                f"(expected one of {', '.join(sorted(PLAN_VERDICTS))})"
            )
        mapped = plan_outcome(word, derived)
        if word == "proceed" and derived == "BLOCK":
            raise ValueError(
                f"the report states Verdict: {written}, but its findings derive BLOCK; "
                "a plan with a blocking finding has not proceeded"
            )
        if word == "revisit" and derived == "PASS":
            raise ValueError(
                f"the report states Verdict: {written}, but its findings derive PASS; "
                "there is nothing to revisit"
            )
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
