#!/usr/bin/env python3
"""The resolver's edit-verify contract.

`crew-pr-resolver` fixes review threads inline rather than through `crew-builder`, so it inherits none
of the builder's machinery: no per-task verify line, no spec `## Tests` gate, no diff-scope check, no
report. Until this suite existed its only post-edit checks were "run lints" and "run a type-check",
which meant a thread could be replied to as "Fixed" with no test ever run and no proof the edit did
only what the thread asked.

This suite pins the four steps that close that gap — scope, tests, lint, type-check — plus the two
ways the fix could itself be wrong: a skipped check that reads as a passed one, and a failing test
made green by moving its expected value. It also pins that the commands come from project guidance,
because a prompt that names one repository's runner is overfitted to the PR that prompted it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / ".cursor" / "agents" / "crew-pr-resolver" / "references" / "acting-on-threads.md"
PROMPT = ROOT / ".cursor" / "agents" / "crew-pr-resolver.md"
MAINTENANCE = ROOT / ".agent" / "tools" / "maintenance"
if str(MAINTENANCE) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE))

from lint_prompts import MAX_PROMPT_FILE_BYTES  # noqa: E402

# Runner names from one repository or ecosystem. The prompt states the obligation; guidance supplies
# the command, so naming a runner here would only work on the repo where it was written.
FOREIGN_RUNNERS = ("jest", "pytest", "kbn", "vitest", "mocha", "cargo", "go test")


def reference() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def code_changes() -> str:
    """The `## Code changes` body up to the next heading, so a rule is checked where it is stated."""
    text = reference()
    start = text.index("## Code changes")
    end = text.index("## Commit and push")
    return text[start:end]


def test_every_verify_step_is_named() -> None:
    """Four steps, and tests are one of them: lint plus type-check cannot see wrong behavior."""
    body = code_changes()
    for step, rule in (
        ("Scope check", r"git status --porcelain"),
        ("Tests", r"narrowest test file"),
        ("Lint", r"lint command"),
        ("Type-check", r"tsc --noEmit"),
    ):
        assert step in body, f"the {step.lower()} step is missing"
        assert re.search(rule, body), f"{step} states no command: {rule!r}"


def test_verification_runs_before_the_reply_claims_a_fix() -> None:
    """The reply is the claim; a claim made before the checks is the failure this pins."""
    body = code_changes()
    assert "before any reply claims it is fixed" in body, "the ordering rule is missing"
    assert re.search(r"The reply says what was\s+verified\s+and what was not", body), (
        "the reply must carry the verification result"
    )


def test_a_failed_or_stopped_check_leaves_the_thread_open() -> None:
    """Resolving a thread tells the reviewer "handled"; a contradicted check cannot say that."""
    body = code_changes()
    assert "Three failed attempts" in body, "the stop rule is missing"
    assert "leave the thread open" in body, "the stopped edit must not resolve"
    assert "handled" in body, "the reason resolution is refused is stated"


def test_a_skipped_check_must_name_its_reason() -> None:
    """`no test covers <path>` is an answer; silence reads as a pass."""
    body = code_changes()
    assert "`no test covers <path>`" in body, "the empty test answer is not allowed for"
    assert "complete answer, not a failed gate" in body, "the empty answer is scoped as acceptable"
    assert "a check skipped without a named reason reads as a check that passed" in body, (
        "the reason a skip must be named is stated"
    )


def test_a_failing_test_is_never_fixed_by_moving_its_expected_value() -> None:
    """Moving the expectation proves the test agrees with the change, not that the change is right."""
    body = code_changes()
    assert "never made to pass by" in body, "the overfitting refusal is missing"
    assert "expected value" in body, "the fixture-fitting case is named"
    assert "Step 4 refuses" in body, "the rule points at the verdict that owns it"


def test_an_unrequested_edit_is_raised_not_bundled() -> None:
    """A reply that carries an extra fix misreports the thread's scope."""
    body = code_changes()
    assert "nothing else" in body, "the scope check has no exclusion"
    assert "separate observation, not into the" in body, "the extra fix has no destination"


def test_commands_come_from_guidance_not_from_a_runner_name() -> None:
    """The obligation is stated here; the command belongs to the repository under review."""
    body = code_changes()
    assert "take them from project guidance" in body, "the command source is unstated"
    for runner in FOREIGN_RUNNERS:
        assert runner not in body.lower(), f"the prompt hardcodes the runner {runner!r}"


def test_the_prompt_points_at_verify_not_at_lint() -> None:
    """Step 7 must not still describe the weaker contract it replaced."""
    text = PROMPT.read_text(encoding="utf-8")
    step_seven = text[text.index("### Step 7:"):]
    assert "verify, commit, push, reply" in step_seven, "Step 7 does not name verification and commit"
    assert "edit, lint, type-check" not in step_seven, "the old lint-only contract survives"


def test_both_files_stay_under_the_byte_ceiling() -> None:
    """`crew-lint --budget` enforces the same ceiling; this fails closer to the edit that broke it."""
    for path, body in ((PROMPT, PROMPT.read_text(encoding="utf-8")),
                       (REFERENCE, reference())):
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
