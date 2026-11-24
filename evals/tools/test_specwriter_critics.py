#!/usr/bin/env python3
"""The specwriter's critic contract: a usable turn budget, and a reply that says what it is.

A real spec run had its adversarial critic stop at the turn limit with a partial result and nothing
reported, while the scope critic ran on. Under Claude Code `maxTurns` is enforced, so `maxTurns: 5`
meant four reads and no report: the critic spent its budget verifying a 199-line spec and never
reached the turn that writes. Under Cursor the field is ignored, which is how the budget stayed
unnoticed — the same file behaved differently in the two harnesses.

Two rules are pinned here. The budget must leave room to report, and every critic reply must end with
a `Verdict:` line, because the specwriter otherwise cannot tell a budget stop from a clean pass: both
arrive as a reply with no findings in it.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".cursor" / "agents"
CRITICS = ("specwriter-adversarial", "specwriter-scope")
SPECWRITER = AGENTS / "crew-specwriter.md"
# Reads before the report turn. A critic that cannot read the spec, check a few claims, and still
# write is a critic that returns nothing, which is the failure this suite exists for.
MIN_TURNS = 8


def text(name: str) -> str:
    return (AGENTS / f"{name}.md").read_text(encoding="utf-8")


def frontmatter(name: str) -> str:
    body = text(name)
    return body.split("---", 2)[1]


def test_every_critic_can_read_then_report() -> None:
    """`maxTurns` is a total, so the budget must exceed the reads a spec review needs."""
    for name in CRITICS:
        found = re.search(r"^maxTurns:\s*(\d+)\s*$", frontmatter(name), re.MULTILINE)
        assert found, f"{name} declares no maxTurns"
        turns = int(found.group(1))
        assert turns >= MIN_TURNS, (
            f"{name} allows {turns} turns; a critic needs reads plus a report turn, so at least "
            f"{MIN_TURNS}. Claude Code enforces this, and 5 produced a run that stopped with nothing."
        )


def test_the_budget_is_stated_in_the_prompt() -> None:
    """The number is enforced by the harness, so the prompt must say how to spend it."""
    for name in CRITICS:
        body = text(name)
        for phrase in ("Budget:", "last one reports", "Claude Code enforces"):
            assert phrase in body, f"{name} does not state its budget: missing {phrase!r}"
        assert "unverified" in body, f"{name} has no way to report a claim it could not check"


def test_every_critic_ends_with_a_verdict_line() -> None:
    """Without it, a silent stop and a clean pass are the same reply."""
    for name in CRITICS:
        body = text(name)
        assert "Verdict: 0 finding" in body, f"{name} never defines the clean-pass line"
        assert re.search(r"Verdict: N finding", body), f"{name} never defines the findings line"
        assert "always" in body.lower(), f"{name} does not make the line mandatory"


def test_someone_owns_the_premise() -> None:
    """A wrong approach is a spec defect, and both critics excluding it leaves it nobody's lane.

    Adversarial once excluded "implementation approach" while its own intro asked whether the
    approach was correct, and the scope critic excludes business requirements — so a spec that
    stored one value in two systems and reconciled it on read passed both critics unchallenged.
    """
    adversarial = text("specwriter-adversarial")
    assert "### The premise" in adversarial, "the adversarial critic has no premise focus area"
    for marker in ("reconcil", "read path", "contradict"):
        assert marker in adversarial.lower(), f"the premise lane never names {marker!r}"
    assert "You do NOT critique:** PR scope" in adversarial, (
        "the critic must still cede PR scope and task granularity to the scope critic"
    )
    assert "implementation approach" not in adversarial, (
        "the critic excludes the approach it is now asked to judge"
    )
    dispatch = SPECWRITER.read_text(encoding="utf-8")
    assert "whether the approach is correct" in dispatch, (
        "the orchestrator still describes the critic as criteria-and-edge-cases only"
    )


def test_the_specwriter_treats_a_missing_verdict_as_incomplete() -> None:
    """The reader half: a reply with no line is resumed once, then reported as a gap."""
    body = SPECWRITER.read_text(encoding="utf-8")
    assert "Verdict:" in body, "the specwriter never mentions the outcome line"
    assert "incomplete, not a clean pass" in body, (
        "a critic reply without the line reads as a clean pass"
    )
    assert "resume" in body.lower(), "an incomplete reply is not resumed"
    assert "turn-limit" in body, "the turn-limit stop is not named among the failure cases"


def test_the_specwriter_stays_under_the_byte_ceiling() -> None:
    """`crew-lint --budget` enforces the same ceiling; this fails closer to the edit that broke it."""
    maintenance = ROOT / ".agent" / "tools" / "maintenance"
    if str(maintenance) not in sys.path:
        sys.path.insert(0, str(maintenance))
    from lint_budget import MAX_PROMPT_FILE_BYTES

    for path in [SPECWRITER] + [AGENTS / f"{name}.md" for name in CRITICS]:
        size = len(path.read_text(encoding="utf-8").encode("utf-8"))
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
