#!/usr/bin/env python3
"""Rendering a finding for a report: the number beside the label, never buried in the prose.

A reader scanning ten findings needs the reviewer's confidence in the same column as the severity,
so the score joins the label — `[attention · 4]` — and never appears as its own sentence. Both
generated lists `persist` writes (the layer coverage table and the deferred file) use the same
helper, so a finding rendered in either place cannot drift from the other.

The numbered list itself is not rendered here: the reviewer model writes it into the report, and its
shape is pinned by the contract and by `test_confidence.py` against a persisted report. A second
renderer for it would be code no path runs. What `persist` does author is the decision footer, so the
verdict, the next step, and the reviewed commit are written once, in the same place, from the same
findings every reader already agrees on.
"""
from __future__ import annotations

from lib.next_steps import next_sentence
from review_models import ABSENT, Finding
from review_vocabulary import verdict

# The stage key per mode, so the footer asks the shared table for its next step instead of restating
# it. A code review branches on the verdict it just derived — `BLOCK` resolves findings first, `PASS`
# and `WARN` commit — and the other three modes each have one successor. `pr` is the one entry that
# names a person's action, because a PR review's findings go to `comments.md` and nothing is posted.
STAGE_BY_MODE = {"self": "review", "changes": "review", "pr": "review.pr",
                 "spec": "review.spec", "idea": "review.idea"}


def stage_key(mode: str, findings: list[Finding]) -> str:
    """The `next-steps.json` key for this mode and its derived verdict."""
    stage = STAGE_BY_MODE.get(mode)
    if stage is None:
        raise ValueError(f"no next-step stage for mode {mode!r}: {', '.join(sorted(STAGE_BY_MODE))}")
    return f"build.{stage}.{verdict(findings).lower()}" if stage == "review" else f"build.{stage}"


def score_suffix(finding: Finding) -> str:
    """` · 4` when the finding carries a score, empty when it was written before the field existed.

    Empty rather than a placeholder: a historical review has no score to show, and printing ` · ?`
    would claim the reviewer was asked and said nothing.
    """
    return "" if finding.confidence is ABSENT else f" · {finding.confidence}"


def label_with_score(finding: Finding) -> str:
    """The label and its score as one bracketed token, which is how every report line carries it."""
    return f"[{finding.label}{score_suffix(finding)}]"


def footer(findings: list[Finding], head: str, mode: str, next_step: str = "",
          derived: bool = True) -> str:
    """The decision block `persist` appends last: verdict, next step, and the reviewed commit.

    Written from the findings rather than copied from the report, because the report's verdict is a
    model's word and this one is derived. `Reviewed at:` is omitted entirely when no `--head` was
    passed: an empty value would claim a tree identity the run never had, and a spec or idea review
    always passes a head, so the omission is a local review saying so.

    `derived=False` writes the next step and the commit without a `Verdict:` line. That is the
    no-`--findings` path: `persist` compared nothing there, so a verdict derived from an empty list
    would be `PASS` stamped under a body that may say `BLOCK`, and every tail-first reader of the
    file takes the last `Verdict:` it finds.

    The next step comes from `next-steps.json` keyed by this mode's stage and the verdict just
    derived, so the persisted report's `> Next:` and `crew-next.py` cannot disagree. A caller may pass
    `next_step` to override it, which is what `persist --next` does. A skill's own trailer is written
    prose that `lint_handoff` holds to the router; it does not read this table.
    """
    step = next_step or next_sentence(stage_key(mode, findings))
    lines = [f"> Next: {step}"]
    if derived:
        lines.insert(0, f"Verdict: {verdict(findings)}")
    if head:
        lines.append(f"Reviewed at: {head}")
    return "\n".join(lines)
