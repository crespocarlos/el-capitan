#!/usr/bin/env python3
"""Classifying a persona's artifact: did it run, and did it produce review content?

Reviewer personas do not all number their findings: three document an unnumbered
`**path — line N**` — title body closed by `Fix/Response:`, and explorer returns `##` sections. A
classifier narrower than the formats the personas document refuses real reviews as placeholders,
which is why every accepted shape here is one a persona actually writes.

A finding is credited by evidence, not by layout: a `path:line` anchor in the same block, an
`Anchor:` line, a quoted sentence from the artifact under review, or a bare line number with a
body. The verdict line is a signal for an empty review, never a cancellation of findings above it:
six anchored findings followed by `### Verdict: no findings` was observed in a real PR review.
"""
from __future__ import annotations

import re

from review_vocabulary import PERSONA_STATUSES

# Reviewer personas do not all number their findings: three document an unnumbered
# `**path — line N**` — title body closed by `Fix/Response:`, and explorer returns `##` sections.
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
# bullet, or after the anchor. Rejecting one aborts the review, and the anchor must still be a real
# `path:line`. The label may carry its confidence score (`[attention · 4]`), which the contract makes
# mandatory, so the suffix is part of the token: a bare `]` would refuse every finding now written.
_SEVERITY = r"(?:blocking|attention|concern|nit|needs more info)(?:\s*·\s*[1-5])?"
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
    says "nothing to report"; a finding says the opposite. Content wins: the verdict line is a
    signal for an empty review, never a cancellation of findings above it.
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

    A finding is credited by evidence, not by layout. Four real spec reviews and five bullet-style
    code reviews were refused as placeholders because the accepted shape was narrower than the
    format the persona documents.
    """
    if VERDICT_NO_FINDINGS.search(text):
        return True
    return has_findings(text)


def persona_outcome(path) -> str:
    """Classify a persona artifact: ok, failed, skipped, truncated, summarized, missing, unknown.

    Only the leading block is read, so a persona quoting `status: failed` from the finding it
    reviews cannot flip a good run. The documented success signal is a verdict line or a complete
    labeled finding; an empty artifact is `unknown`, not `ok`, because the failure this guards
    against is a persona that died silently. Only `failed|skipped|truncated` are read from a
    `status:` line: any other word (`dispatched`, `done`, `complete`) is not a success claim, so it
    falls through to the content check and a placeholder without a verdict stays `unknown`.

    `summarized` is an orchestrator's condensed digest written in place of the persona's response.
    It is a separate outcome from `unknown` because the artifact does contain findings, but nothing
    in it is attributable to the persona or re-verifiable later, so persistence refuses it and names
    the real cause instead of "no output".
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
