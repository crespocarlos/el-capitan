#!/usr/bin/env python3
"""The resolver's probe contract: an unsettled thread is measured, not guessed.

A real session had a reviewer ask what a workflow step's output renders to when that step was skipped.
The resolver could not tell from reading the engine, and the honest options were a vague reply or a
guess — either way the thread closed on opinion. A throwaway test in the engine's own package answered
it in a minute.

The prompt now sends an unsettled thread to a probe before the verdict is scored. This suite pins that
trigger, and pins the three ways the instruction could itself go wrong: a probe that becomes the
default for every thread, a probe that leaves a file behind, and a probe reported as a measurement of
more than it measured.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / ".cursor" / "agents" / "crew-pr-resolver.md"
REFERENCE = ROOT / ".cursor" / "agents" / "crew-pr-resolver" / "references" / "probing-a-question.md"
MAINTENANCE = ROOT / ".agent" / "tools" / "maintenance"
if str(MAINTENANCE) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE))

from lint_budget import MAX_PROMPT_FILE_BYTES  # noqa: E402


def prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


def reference() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def step_four() -> str:
    """Step 4 up to the challenge section, so the trigger is checked in the evaluation it governs."""
    text = prompt()
    return text[text.index("### Step 4:"):text.index("### Challenge each thread")]


def test_an_unsettled_thread_is_probed_before_it_is_scored() -> None:
    """The trigger is low confidence, not one narrow kind of question."""
    body = step_four()
    assert "`ACTED_CONFIDENCE`" in body, "the trigger is not tied to the confidence floor"
    assert "`Ask`" in body, "a thread headed for Ask is not routed to a probe"
    assert body.index("ACTED_CONFIDENCE") < body.index("4. **Evaluate all threads"), (
        "the probe rule is ordered after the verdict it is meant to inform"
    )


def test_the_probe_reference_is_linked_and_exists() -> None:
    """Material a step needs only sometimes lives in references/, linked from the step."""
    assert REFERENCE.is_file(), f"{REFERENCE.name} is missing"
    assert "](crew-pr-resolver/references/probing-a-question.md)" in prompt(), (
        "Step 4 does not link the probe reference"
    )


def test_the_question_is_a_heuristic_and_the_probe_is_the_check() -> None:
    """The framing is the rule: a comment you cannot settle is a suspicion until measured."""
    body = reference()
    assert "heuristic" in body, "the question's status as a heuristic is unstated"
    assert "the probe is the check" in body, "the probe is not named as what settles it"


def test_several_kinds_of_uncertainty_route_to_a_probe() -> None:
    """Runtime behavior is one case; a fixture's assertion or a helper's accepted input are others."""
    body = reference()
    for case in ("runtime", "fixture", "schema", "caller"):
        assert case in body.lower(), f"the probe guidance omits the {case!r} case"


def test_a_probe_is_removed_before_the_report() -> None:
    """A probe left behind is an unrequested edit; the run must leave the tree as it found it."""
    body = reference()
    assert "Delete it" in body, "the probe is never deleted"
    assert "clean before the report" in body, "nothing proves the tree returned to its prior state"
    assert "only write evaluation makes" in body, "the write scope of a probe is unstated"


def test_a_kept_probe_goes_through_the_approval_gate() -> None:
    """A probe worth keeping is a test proposed in the edit, not a file the run leaves."""
    body = reference()
    assert "through the approval gate" in body, "a kept probe bypasses the gate"
    assert "proposed as a test" in body, "the kept probe has no shape"


def test_a_probe_that_cannot_run_leaves_the_thread_open() -> None:
    """`Cannot verify here` with its reason is an answer; a guess dressed as one is not."""
    body = reference()
    assert "cannot run" in body, "the infeasible case is missing"
    assert "leaves the thread `Ask`" in prompt(), "an unprobed thread may still resolve"
    assert "dressed as a measurement" in body, "the guess is not refused in so many words"


def test_the_reply_states_what_the_probe_does_not_cover() -> None:
    """A probe covers the case it built, not the workflow around it."""
    body = reference()
    assert "State the limit" in body, "the reply has no scope statement for the probe"
    assert "not the whole workflow" in body, "the common over-read is not named"


def test_the_probe_does_not_become_the_default_for_every_thread() -> None:
    """A probe costs a runner; a thread the code settles must not pay for one."""
    body = reference()
    assert "Skip the probe only when it is infeasible" in body, (
        "the skip condition is unstated, so the probe reads as optional everywhere"
    )
    for bound in ("below `ACTED_CONFIDENCE`", "would render `Ask`", "torn between"):
        assert bound in body, f"the trigger omits one of its bounds: {bound!r}"


def test_the_prompt_stays_under_the_byte_ceiling() -> None:
    """`crew-lint --budget` enforces the same ceiling; this fails closer to the edit that broke it."""
    for path, body in ((PROMPT, prompt()), (REFERENCE, reference())):
        size = len(body.encode("utf-8"))
        assert size <= MAX_PROMPT_FILE_BYTES, f"{path.name}: {size} bytes (>{MAX_PROMPT_FILE_BYTES})"


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
