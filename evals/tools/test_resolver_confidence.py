#!/usr/bin/env python3
"""The resolver prompt's verdict contract: one gate, a challenge pass, a score, and the Ask floor.

`crew-pr-resolver` classified every review thread after one read and never said what made a verdict
right, so a comment with a false premise was as easy to apply as one with a true premise. Worse, a
`Reject` the resolver barely believed in could resolve the thread, telling the reviewer "handled"
about work nobody stood behind.

This suite pins the prompt text, because a prompt's contract is the report it makes an agent produce:
exactly one approval gate, a challenge pass citing `path:line` before any verdict, a 1-5 score on the
shared scale, and the floor — a `Reject` scoring below `ACTED_CONFIDENCE` is rendered `Ask`, whose row
carries a question and no resolve command. `report_rows` is the format check the prompt's own example
table is held to, and the negative cases below prove it rejects the two ways a row can lie about a
`Reject`: too little confidence for the claim, and no anchor behind it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / ".cursor" / "agents" / "crew-pr-resolver.md"
for directory in (ROOT / ".agent" / "tools" / "review", ROOT / ".agent" / "tools" / "maintenance"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from lint_budget import MAX_PROMPT_FILE_BYTES  # noqa: E402
from review_vocabulary import ACTED_CONFIDENCE, CONFIDENCE  # noqa: E402

# The scale as the resolver prompt is written against. A frozen snapshot on purpose: parity is only
# a check if one side is fixed, so a drift in `review_vocabulary.py` fails here instead of both
# sides moving together and agreeing about the wrong bands.
EXPECTED_BANDS = {5: "confirmed", 4: "strong", 3: "likely", 2: "uncertain", 1: "suspicion"}
ACTIONS = ("Apply", "Adapt", "Reject", "Decide", "Defer", "Already Addressed", "Ask")
VERDICT_CELL = re.compile(r"^(%s) · ([1-5])$" % "|".join(ACTIONS))
ANCHOR = re.compile(r"[\w./-]+:\d+")


def prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


def cell(row: str, index: int) -> str:
    return row.strip().strip("|").split("|")[index].strip()


def verdict_rows(text: str) -> list[str]:
    """The example rows of the Step 6 report table, separator and the `...` filler excluded."""
    rows, inside = [], False
    for line in text.splitlines():
        if line.startswith("| # | File | Reviewer | Verdict · N"):
            inside = True
            continue
        if inside and not line.startswith("|"):
            break
        if not inside or set(line) <= set("|- "):
            continue
        if all(part.strip() in ("...", "") for part in line.strip("|").split("|")):
            continue
        rows.append(line)
    return rows


def row_problem(row: str) -> str:
    """Why one report row breaks the prompt's contract, or "" when it is well formed.

    The floor and the anchor are checked here rather than trusted to prose: a row is what the agent
    renders and what a reviewer acts on, so the two rules that make a `Reject` honest have to hold on
    the row itself.
    """
    match = VERDICT_CELL.match(cell(row, 3))
    if not match:
        return f"verdict cell is not `<action> · <1-5>`: {cell(row, 3)!r}"
    action, score = match.group(1), int(match.group(2))
    if action not in ACTIONS:
        return f"unknown action {action!r}; expected one of {ACTIONS}"
    reply, edit = cell(row, 5), cell(row, 4)
    if "crew-pr-actions.py resolve" in row:
        return "a report row never carries a resolve command; Step 7 runs it after approval"
    if action == "Reject" and score < ACTED_CONFIDENCE:
        return (f"a Reject at {score} is below the floor of {ACTED_CONFIDENCE}; render it "
                f"`Ask · {score}` so the thread stays open")
    if action == "Reject" and not ANCHOR.search(reply):
        return "a Reject reply must cite the path:line its claim rests on"
    if action == "Ask" and "?" not in reply:
        return "an Ask row must ask a question"
    if action in ("Apply", "Adapt") and edit == "—":
        return f"an {action} row must carry the proposed edit"
    return ""


def test_the_resolver_has_one_approval_gate() -> None:
    """Step 4 no longer tells the agent to act, so Step 6's ask and Step 7's wait are the only gate."""
    text = prompt()
    assert "Do not ask the user before acting" not in text, "the deleted instruction is back"
    assert text.count("not mid-stream") == 1, (
        "the verdicts belong to the final report once, not as a sentence plus a dangling repeat"
    )
    assert re.search(r"^### Step 6: .*approval", text, re.MULTILINE), "Step 6 is the gate"
    assert re.search(r"^### Step 7: ", text, re.MULTILINE), "Step 7 exists"
    assert "Only after the user responds:" in text, "Step 7 must wait for the response"
    step_four = text[text.index("### Step 4:"):text.index("### Step 5:")]
    assert "no side effects" in step_four, "Step 4 must say evaluation changes nothing"


def test_the_challenge_pass_precedes_every_verdict() -> None:
    """The three questions come from consolidation.md, each answered with a citation."""
    text = prompt()
    assert "### Challenge each thread" in text, "the challenge pass needs its own section"
    section = text[text.index("### Challenge each thread"):text.index("### Step 5:")]
    assert text.index("### Challenge each thread") < text.index("### Step 5:"), (
        "the challenge runs before the score and the verdict"
    )
    for question in ("Is the premise present?", "Is the chain traceable?", "Are the stakes real?"):
        assert question in section, f"missing challenge question: {question}"
    assert section.count("`path:line`") >= 1, "each answer cites path:line"
    assert "consolidation.md" in section, "the questions are borrowed, and the source is named"
    step_four = text[text.index("### Step 4:"):text.index("### Challenge each thread")]
    assert "Challenge each thread" in step_four, "Step 4 orders the challenge before classifying"
    assert "adds no reads" in step_four, "the challenge keeps the read-once constraint"


def test_the_confidence_scale_is_the_shared_one() -> None:
    """Scale and floor are read from `review_vocabulary.py`, never restated in the prompt."""
    text = prompt()
    assert CONFIDENCE == EXPECTED_BANDS, f"the shared scale moved: {CONFIDENCE} != {EXPECTED_BANDS}"
    assert ACTED_CONFIDENCE == 3 and ACTED_CONFIDENCE in CONFIDENCE, ACTED_CONFIDENCE
    assert "review_vocabulary.py" in text and "CONFIDENCE" in text and "ACTED_CONFIDENCE" in text
    assert "confidence_scale()" in text, "the wording comes from the shared helper, not from prose"
    for score, band in CONFIDENCE.items():
        assert f"{score} {band}" not in text.lower(), (
            f"the prompt restates the band {score} {band!r}; point at the code"
        )


def test_the_report_table_carries_the_score_and_an_ask_row() -> None:
    """One table, `verdict · N`, with an Ask row that asks and resolves nothing."""
    text = prompt()
    rows = verdict_rows(text)
    assert len(rows) >= 3, f"expected the render's example rows, found {len(rows)}"
    for row in rows:
        assert not row_problem(row), row_problem(row)
    actions = [VERDICT_CELL.match(cell(row, 3)).group(1) for row in rows]
    assert "Ask" in actions, f"no Ask row in the example table: {actions}"
    assert "Reject" in actions, f"no Reject row in the example table: {actions}"
    assert "as `verdict · N`" in text, "the prose states the render as `verdict · N`"
    assert "| Verdict · N |" in text, "the column header carries the score"
    assert text.count("| Verdict · N |") == 1, "one table, not two competing shapes"


def test_a_reject_below_the_floor_becomes_an_ask() -> None:
    """The floor is the leverage: at 1-2 the thread cannot be resolved, so the action is a question."""
    row = "| 9 | a.ts:4 | @reviewer | Reject · 2 | — | Not changing this: `a.ts:4` is fine. |"
    problem = row_problem(row)
    assert "below the floor" in problem and "Ask · 2" in problem, problem
    asked = "| 9 | a.ts:4 | @reviewer | Ask · 2 | — | Does the premise hold at `a.ts:4`? |"
    assert not row_problem(asked), row_problem(asked)
    text = prompt()
    assert "Ask" in text and "stays open" in text, "the prompt states the thread stays open"
    assert "Ask` thread gets the reply alone" in text, "Step 7 scopes resolve away from an Ask"
    # And a row that carried a resolve command is refused: resolution is Step 7's, after approval.
    resolving = ("| 9 | a.ts:4 | @reviewer | Ask · 2 | — | Does it hold? "
                 "Run crew-pr-actions.py resolve. |")
    assert "resolve command" in row_problem(resolving), row_problem(resolving)


def test_a_reject_without_an_anchor_is_rejected() -> None:
    """A rationale with no `path:line` cannot be falsified, which is why it is refused."""
    unanchored = "| 4 | a.ts:7 | @reviewer | Reject · 4 | — | I left this as-is: it is fine. |"
    assert "path:line" in row_problem(unanchored), row_problem(unanchored)
    anchored = ("| 4 | a.ts:7 | @reviewer | Reject · 4 | — | Not changing this: `a.ts:7` returns "
                "before the guard would run. |")
    assert not row_problem(anchored), row_problem(anchored)
    assert "path:line" in prompt(), "Step 5 must state the anchor rule"


def test_the_outcome_link_is_noted_and_writes_nothing_new() -> None:
    """A resolved Apply/Adapt thread is the same decision the reviewer pipeline records."""
    step_eight = prompt()[prompt().index("### Step 8:"):]
    assert "whose verdict was Apply or Adapt" in step_eight, "the link names the verdicts it covers"
    assert "is the same decision the reviewer pipeline\nrecords as an outcome" in step_eight, (
        "the link must state the equivalence, not merely mention outcomes"
    )
    assert "may cite it" in step_eight, "the entry may cite the recorded outcome"
    assert "Write nothing new" in step_eight, "nothing extra is written for it"
    assert "durable record" in step_eight, "the thread is the record"


def test_the_prompt_stays_under_the_byte_ceiling() -> None:
    """`crew-lint --budget` enforces the same ceiling; this fails closer to the edit that broke it."""
    size = len(prompt().encode("utf-8"))
    assert size <= MAX_PROMPT_FILE_BYTES, f"{size} bytes (>{MAX_PROMPT_FILE_BYTES})"


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"pass: {test.__name__}")
        except AssertionError as error:
            failed += 1
            print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
