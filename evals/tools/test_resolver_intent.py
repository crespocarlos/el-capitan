#!/usr/bin/env python3
"""The resolver prompt's context and intent contract.

A real run resolved 12 threads and reported success on work it had no business applying. It edited
prompt and code files without loading the guidance that governs them, and it applied threads that
asked to reverse a design decision, because every challenge question it asked was a code-fact
question. The prompt now loads project guidance once for the paths under review, asks intent before
the code-fact questions, and carries a seventh action for the author's own decisions.

This suite pins those four things in the prompt text, plus the two ways the fix could itself be
wrong: a repository-specific eval suite name or a rule name that only reaches the agent through the
guidance call, and an eval requirement that turned a suggestion into a gate.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / ".cursor" / "agents" / "crew-pr-resolver.md"
MAINTENANCE = ROOT / ".agent" / "tools" / "maintenance"
if str(MAINTENANCE) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE))

from lint_prompts import MAX_PROMPT_FILE_BYTES  # noqa: E402

# Names that only made sense for the one PR that failed. A prompt that repeats them is overfitted to
# that repository and says nothing about the next one.
FOREIGN_TARGETS = ("kbn-evals", "bank-of-anthos", "md.text", "discovery.md")
INTENT = "Is this a fault or a decision?"
CODE_FACT_QUESTIONS = ("Is the premise present?", "Is the chain traceable?", "Are the stakes real?")
# Each enumeration of the action set, addressed by a phrase that only that enumeration carries. The
# summary line is prose and lowercase like its neighbours; the three that render a verdict are
# capitalized because the verdict vocabulary is.
REPORTING = ROOT / ".cursor" / "agents" / "crew-pr-resolver" / "references" / "reporting-a-run.md"
ENUMERATIONS = {
    "Step 4 classify": (r"Classify each as (?:\*\*[^*]+\*\*,?\s*)+", "Decide", PROMPT),
    "Step 5 prepare": (r"- \*\*(?:Apply/Adapt|Decide)\*\*:[^\n]*(?:\n  [^\n]*)*", "Decide", PROMPT),
    "Step 6 table": (r"\| \d+ \| path/to/file\.ts:\d+ \| @reviewer \| (\w+(?: \w+)?) · \d \|",
                     "Decide", PROMPT),
    "summary counts": (r"N apply / ([^\n`]*)", "decide", REPORTING),
}


def prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    """The prompt text from one heading up to the next, so a rule is checked where it is stated."""
    text = prompt()
    return text[text.index(start):text.index(end)]


def test_guidance_is_loaded_once_with_every_path() -> None:
    """One call, all paths: the reviewer's rule, and the reason it exists is the same here."""
    text = prompt()
    step_one = section("### Step 1:", "### Step 2:")
    assert "crew-agent-context.py" in step_one, "Step 1 never calls the guidance tool"
    assert "paths ..." in step_one, "the call's shape is stated, not just its name"
    assert "**once**" in step_one, "the call is once, not per thread"
    assert re.search(r"every path the PR touches", step_one), "the call takes all paths at once"
    assert "never per thread" in step_one, "the per-thread alternative is refused by name"
    assert re.search(r"re-reads the same\s+`AGENTS\.md`", step_one), "the reason states the cost"
    calls = [line for line in step_one.splitlines() if "crew-agent-context.py $" in line]
    assert len(calls) == 1, f"expected one call site, found {len(calls)}"


def test_decide_appears_in_every_enumeration() -> None:
    """A seventh action only works if all four renderings of the action set carry it."""
    text = prompt()
    for name, (pattern, spelling, path) in ENUMERATIONS.items():
        body = text if path == PROMPT else path.read_text(encoding="utf-8")
        found = " ".join(re.findall(pattern, body))
        assert found, f"{name}: the enumeration is not found by {pattern!r} in {path.name}"
        assert spelling in found, f"{name} omits Decide: {found[:120]!r}"
    step_seven = text[text.index("### Step 7:"):]
    assert "`Decide` thread" in step_seven, "a Decide thread must be scoped out of resolution"


def test_the_intent_question_precedes_the_code_fact_questions() -> None:
    """Intent first: none of the three code-fact questions can see a request to change a decision."""
    challenge = section("### Challenge each thread", "### Step 5:")
    for question in (INTENT,) + CODE_FACT_QUESTIONS:
        assert question in challenge, f"missing challenge question: {question}"
    positions = [challenge.index(question) for question in (INTENT,) + CODE_FACT_QUESTIONS]
    assert positions == sorted(positions), f"questions are out of order: {positions}"
    assert positions[0] == min(positions), "intent is not first"
    assert "**Decide**, never **Apply**" in challenge, "the outcome for a decision is stated"
    assert "not a veto" in challenge, "the question is scoped away from ordinary fixes"
    for topic in ("behavior", "API surface", "documented contract", "expected value", "naming",
                  "data shape"):
        assert topic in challenge, f"the decision list omits {topic!r}"


def test_a_fixture_value_edit_is_flagged_as_overfitting() -> None:
    """Moving an expected value to match new behavior proves agreement, not correctness."""
    text = prompt()
    for where in ("### Step 4:", "### Challenge each thread", "### Step 6:"):
        following = text[text.index(where):]
        assert re.search(r"expected value", following), f"{where} does not name the fixture case"
    assert "proves the test agrees with the change, not that the change is\nright" in text or \
        "agrees with the change, not that the change is" in text, "the reason is stated"
    step_four = section("### Step 4:", "### Challenge each thread")
    assert re.search(r"expected value[^\n]*overfitting", step_four, re.S), (
        "Step 4 must classify a fixture-fitting edit as overfitting, not apply it"
    )
    assert "Name the expected value a flagged row moves" in text, "the report row names what moved"


def test_the_eval_is_reported_but_never_required() -> None:
    """The eval is a suggestion: naming none of them is a complete answer, not a failed gate."""
    text = prompt()
    assert "`no eval covers this` is a complete answer" in text, "the empty answer is allowed"
    assert "which eval would measure it" in text, "the report still names what would measure it"
    for gate in ("unless an eval is named", "requires an eval", "without both", "must name an eval"):
        assert gate not in text, f"the eval became a gate: {gate!r}"


def test_a_comment_is_a_proposal_not_an_obligation() -> None:
    """A thread gets a decision, not an owed fix: applying it is one outcome among several."""
    text = prompt()
    assert "**A review comment is a proposal, not an obligation.**" in text, "the framing is missing"
    assert "applying it is one possible outcome, not the default" in text
    assert "action all unresolved" not in text, "the description still frames every comment as work owed"


def test_every_verdict_is_refuted_before_it_is_reported() -> None:
    """A verdict must survive a counter-argument, and the row must say so."""
    text = prompt()
    assert "Refute every verdict once" in text, "the refutation pass is missing"
    assert "refuted:" in text, "the report row records the refutation"
    assert "no new reads" in text or "No new reads" in text, "refutation must not add reads"
    reference = (Path(__file__).resolve().parents[2]
                 / ".cursor/agents/crew-pr-resolver/references/refuting-a-verdict.md")
    assert reference.is_file(), "the per-verdict counter-argument reference is missing"
    body = reference.read_text(encoding="utf-8")
    for verdict in ("Reject", "Apply", "Adapt", "Decide", "Already Addressed", "Defer", "Ask"):
        assert verdict in body, f"the reference does not say how to refute a {verdict}"


def test_the_report_is_published_even_with_nothing_to_apply() -> None:
    """Zero edits is a result: the table and questions still go out."""
    text = prompt()
    assert "Publish this report even when nothing can be applied" in text
    assert "Zero edits is a result, not an absence" in text


def test_the_prompt_names_no_foreign_target() -> None:
    """No suite from the failing PR, and no rule it cannot reach without the guidance call itself."""
    text = prompt()
    for target in FOREIGN_TARGETS:
        assert target not in text, f"the prompt hardcodes {target!r}"
    read_by_path = set(re.findall(r"~?\.?/?\.cursor/rules/([\w.-]+\.mdc)", text))
    named = set(re.findall(r"([\w-]+\.mdc)", text))
    stray = named - read_by_path
    assert not stray, (
        f"the prompt names rules it never reads, so it relies on guidance to deliver them: "
        f"{sorted(stray)}"
    )


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
