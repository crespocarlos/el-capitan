#!/usr/bin/env python3
"""The sections `persist` writes itself, and the guard that stops a report writing them too.

Two jobs, both about the boundary between what a model authors and what the pipeline derives. The
report body is the model's; these sections are not. A body that already carries one renders it twice
and a reader cannot tell which copy is authoritative, so the headings are matched before anything is
appended — against real level-3 headings only, because the contract requires a finding to quote, and a
quote inside a fence is not a section.

This module owns both halves, so the heading a guard rejects and the heading a renderer writes cannot
drift: `GENERATED_SECTIONS` is built from the constants beside the functions that use them. The
assessment section is the one carrying a judgement rather than a count — what each lens thinks of the
change as a whole, which findings alone cannot answer.
"""
from __future__ import annotations

from review_vocabulary import ASSESSMENT_ORDER

ASSESSMENT_HEADING = "### Assessment of the change"
COVERAGE_HEADING = "### Coverage by layer"
FILES_HEADING = "### Files reviewed"
# What `persist` appends. A report must not carry any of them, or it renders twice.
GENERATED_SECTIONS = (ASSESSMENT_HEADING, COVERAGE_HEADING, FILES_HEADING)
# A lens writes a sentence or three of reason. Past this the line is cut with its remainder reported,
# so a reader skimming `REVIEW.md` gets every lens's judgement without paying for four long paragraphs.
CLAUSE_DISPLAY_MAX = 600


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


def assessment_section(rows: dict) -> str:
    """The lenses' judgement on the change, or "" when there is nothing at all to report.

    `rows` is the gate's report, so this renders the verdicts already parsed and gated rather than
    re-reading every reply. The reading order is the vocabulary's own, so a word added there cannot
    silently disappear from the tally; an unexpected word gets its own line instead of being dropped.

    Two views of one fact, because they answer different questions. The tally says whether the lenses
    agree — "3 of 5 request changes" is what routes a decision. The per-lens lines say *why* each one
    landed there, so a reader acting on the review does not have to open four persona files to learn
    that one approved for a different reason than another. A clause past the display cap is cut with
    its length and the file that holds the rest, because a silently shortened reason reads as complete.

    A run with no tally still emits the section when a lens was skipped or never finished: the reader
    of `REVIEW.md` needs those names, and "no lens was asked" is a different, worse fact than "every
    lens approved" — which is why the tally alone cannot decide whether the section appears.
    """
    assessed = rows.get("assessed") or {}
    skipped = rows.get("skipped") or {}
    unavailable = rows.get("unavailable") or {}
    if not (assessed or skipped or unavailable):
        return ""
    by_word: dict[str, list[str]] = {}
    for persona, (word, _clause) in assessed.items():
        by_word.setdefault(word, []).append(persona)
    lines = [ASSESSMENT_HEADING, ""]
    for word in ASSESSMENT_ORDER:
        names = by_word.pop(word, [])
        if names:
            lines.append(f"- **{word}** — {', '.join(sorted(names))}")
    for word in sorted(by_word):
        lines.append(f"- **{word}** — {', '.join(sorted(by_word[word]))}")
    if skipped:
        lines.append(f"- not asked (package predates the rule) — {', '.join(sorted(skipped))}")
    if unavailable:
        named = ", ".join(f"{name} ({outcome})" for name, outcome in sorted(unavailable.items()))
        lines.append(f"- no assessment — {named}")
    if assessed:
        lines.append("")
        lines.append("#### Each lens, and why")
        for persona in sorted(assessed):
            word, clause = assessed[persona]
            lines.append(f"- **{persona}** — {word}: {clause_text(persona, clause)}")
    return "\n".join(lines) + "\n"


def clause_text(persona: str, clause: str, limit: int = CLAUSE_DISPLAY_MAX) -> str:
    """One lens's reason, shortened only when it has to be, and never without saying so.

    The clause is the evidence a reader weighs, so it is reproduced as written. Past the cap it is cut
    at a word boundary with the remaining length and the file that holds the whole line, because a
    reason that ends mid-sentence with no marker is indistinguishable from one the persona wrote short.
    """
    text = " ".join(clause.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return f"{cut}… (+{len(text) - len(cut)} chars; see `{persona}.out.md`)"
