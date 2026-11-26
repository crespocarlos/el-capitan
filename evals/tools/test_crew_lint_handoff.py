#!/usr/bin/env python3
"""The handoff grammar: one last trailer, resolvable verbs, and quoted per-outcome examples accepted.

The rule exists because `> Next:` had drifted into six shapes across fourteen files with nothing
checking it, so a reader could not tell a real handoff from a sentence containing the token. Each case
below is one of those shapes, either accepted or refused; the fixture tree is written on disk so the
lint runs over files the way `crew-lint` does rather than over strings.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = ROOT / ".agent" / "tools" / "maintenance"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from lint_references import lint_handoff  # noqa: E402

ROUTER = """# Router

| Trigger | Crew member |
|---|---|
| `crew review` | crew-reviewer |
| `crew commit` | crew-commit |
| `crew implement` | crew-builder |
| `crew spec` issue | crew-specwriter |
| `crew test` | crew-test |
| `crew resolve PR` #X | crew-pr-resolver |
| `crew review address` | crew-address-review skill |
"""


def tree(tmp: Path, files: dict[str, str]) -> Path:
    """A repository root holding exactly the given `path -> text` files, plus a router."""
    (tmp / "rules").mkdir(parents=True, exist_ok=True)
    (tmp / "rules" / "crew-router.mdc").write_text(ROUTER)
    for name, text in files.items():
        path = tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp


def findings(root: Path) -> list[tuple[str, int, str, str]]:
    return lint_handoff(root, root / "rules" / "crew-router.mdc")


def rules(root: Path) -> list[str]:
    return [rule for _, _, rule, _ in findings(root)]


SKILL = ".cursor/skills/{name}/SKILL.md"


def path_for(name: str) -> str:
    """The skill file a case builds, under the tree layout the lint globs."""
    return SKILL.format(name=name)


def test_a_conforming_trailer_passes(tmp: Path) -> None:
    root = tree(tmp, {path_for("crew-commit"): "Do the work.\n\n> Next: run `crew commit` to continue.\n"})
    assert rules(root) == [], findings(root)


def test_a_second_unquoted_trailer_fails(tmp: Path) -> None:
    """Two handoffs in one file means the reader is told two different next steps."""
    root = tree(tmp, {path_for("crew-commit"): (
        "> Next: run `crew commit` to continue.\n\nMore prose.\n\n"
        "> Next: run `crew review` to continue.\n")})
    assert "handoff-multiple-trailers" in rules(root), findings(root)


def test_a_trailer_that_is_not_last_fails(tmp: Path) -> None:
    """Anything after the trailer runs after the handoff, which is how a step gets dropped."""
    root = tree(tmp, {path_for("crew-commit"): (
        "> Next: run `crew commit` to continue.\n\n## Later\n\nStill more prose.\n")})
    assert "handoff-trailer-not-last" in rules(root), findings(root)


def test_a_verb_absent_from_the_router_fails_naming_file_line_and_verb(tmp: Path) -> None:
    root = tree(tmp, {path_for("crew-commit"): "Prose.\n\n> Next: run `crew frobnicate` to continue.\n"})
    found = findings(root)
    assert len(found) == 1, found
    name, line, rule, message = found[0]
    assert name == path_for("crew-commit"), name
    assert line == 3, line
    assert rule == "handoff-unrouted-command", rule
    assert "crew frobnicate" in message, message


def test_a_quoted_multi_outcome_skill_passes(tmp: Path) -> None:
    """`crew-test` prints one of three lines; each sits in backticks, so none is a trailer."""
    root = tree(tmp, {path_for("crew-test"): (
        "- If PASS: print `Verdict: PASS` then `> Next: run \\`crew review\\` to continue.`\n"
        "- If WARN: print `Verdict: WARN` then `> Next: verify the acceptance criteria.`\n"
        "- If FAIL: print `Verdict: FAIL` then `> Next: fix the failures, then re-run \\`crew "
        "test\\`.`\n")})
    assert rules(root) == [], findings(root)


def test_four_quoted_branches_pass(tmp: Path) -> None:
    """`crew-address-review` documents four, one per mode; the count is not the rule."""
    branches = "".join(
        f"- Branch {index}: `> Next: run \\`crew review\\` to verify.`\n" for index in range(4))
    root = tree(tmp, {path_for("crew-address-review"): branches})
    assert rules(root) == [], findings(root)


def test_a_bare_next_in_a_trailerless_file_fails(tmp: Path) -> None:
    """Without a trailer, a stray `Next:` is a handoff nobody lints or reads as one."""
    root = tree(tmp, {".cursor/agents/reviewer-adversarial.md": (
        "## Method\n\n1. Read the diff.\n2. Next: check the error paths.\n")})
    assert "handoff-stray-next" in rules(root), findings(root)


def test_the_pr_paste_exception_passes(tmp: Path) -> None:
    """A PR review's findings are pasted by a person, so no `crew` verb can name that step."""
    root = tree(tmp, {path_for("crew-review"): (
        "Prose.\n\n> Next: paste the bodies from `comments.md` onto PR #12; nothing was posted.\n")})
    assert rules(root) == [], findings(root)


def test_an_unknown_non_crew_next_step_fails(tmp: Path) -> None:
    """The exception is one prefix, not a licence for any prose in a trailer."""
    root = tree(tmp, {path_for("crew-commit"): "Prose.\n\n> Next: ask the user what they think.\n"})
    assert "handoff-no-command" in rules(root), findings(root)


def test_a_trailerless_file_is_not_required_to_gain_one(tmp: Path) -> None:
    """4 of 19 skills and 2 of 16 agents carry a trailer today; requiring one is 29 edits for no reader."""
    root = tree(tmp, {
        path_for("crew-log"): "Write the log line.\n",
        ".cursor/agents/reviewer-architecture.md": "## Method\n\nJudge the boundaries.\n",
    })
    assert rules(root) == [], findings(root)


def test_a_fenced_trailer_is_an_example_not_a_handoff(tmp: Path) -> None:
    """A fenced block is documentation of an output shape, so it neither is nor competes with a trailer."""
    root = tree(tmp, {path_for("crew-log"): (
        "Print this:\n\n```text\n> Next: run `crew commit` to continue.\n```\n")})
    assert rules(root) == [], findings(root)


def test_a_spec_and_idea_trailer_accepts_a_quoted_command_inside_prose(tmp: Path) -> None:
    """The trailer may carry a reason beside its command; only the command has to resolve."""
    root = tree(tmp, {
        path_for("crew-spec"): "Prose.\n\n> Next: run `crew implement` to continue.\n",
        ".cursor/agents/crew-reviewer/references/output-formats.md": (
            "- A self-review ends with `Next: run \\`crew commit\\` to continue.`\n"),
    })
    assert rules(root) == [], findings(root)


def test_an_agent_file_trailer_is_checked_too(tmp: Path) -> None:
    """The grammar covers agents and references, not only skills."""
    root = tree(tmp, {".cursor/agents/crew-specwriter.md": "Prose.\n\n> Next: run `crew nowhere`.\n"})
    assert "handoff-unrouted-command" in rules(root), findings(root)


def test_a_reference_file_trailer_is_checked(tmp: Path) -> None:
    root = tree(tmp, {".cursor/agents/crew-reviewer/references/auto-apply.md": (
        "Prose.\n\n> Next: run `crew nowhere` to continue.\n")})
    assert "handoff-unrouted-command" in rules(root), findings(root)


def test_an_indented_second_handoff_fails(tmp: Path) -> None:
    """A blockquote handoff three spaces in is still a handoff, and a file emits one."""
    root = tree(tmp, {path_for("crew-implement"): (
        "3. Tell the user — mandatory:\n"
        "   > Next: run `crew review` to verify the change.\n\n"
        "> Next: run `crew commit` to continue.\n")})
    assert "handoff-multiple-trailers" in rules(root), findings(root)


def test_a_stray_next_beside_a_trailer_fails(tmp: Path) -> None:
    """Having one trailer does not exempt the rest of the file: two handoffs is the failure."""
    root = tree(tmp, {path_for("crew-quick"): (
        "Print: Next: run `crew commit` to continue.\n\n"
        "> Next: run `crew commit` to continue.\n")})
    assert "handoff-stray-next" in rules(root), findings(root)


def test_the_shared_agent_references_are_governed(tmp: Path) -> None:
    """`.cursor/agents/references/` loads beside every agent, so the grammar reaches it."""
    root = tree(tmp, {".cursor/agents/references/dispatch.md": (
        "Prose.\n\n> Next: run `crew nowhere` to continue.\n")})
    assert "handoff-unrouted-command" in rules(root), findings(root)


def test_a_skill_reference_file_is_governed(tmp: Path) -> None:
    root = tree(tmp, {".cursor/skills/crew-x/references/detail.md": (
        "Prose.\n\n> Next: run `crew nowhere` to continue.\n")})
    assert "handoff-unrouted-command" in rules(root), findings(root)


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
