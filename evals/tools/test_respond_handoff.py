#!/usr/bin/env python3
"""The `respond` stage sequence, stated in four places that must agree.

A reply tells the reviewer the fix is in the branch, so a reply posted before the push points at a
branch that does not carry it. The workflow therefore commits and pushes before any thread is answered,
and `crew review` runs over the pushed fixes rather than gating them: the resolver is a subagent and
cannot dispatch the inline-only reviewer.

The order is written in four documents — the resolver's stage line and handoff, the orchestrator's
workflow list, the router's review invariant, and the README diagram and stage line. Any one of them
left saying `address-pr → commit → push` or naming review as a gate sends the next run past the commit
or re-introduces a review the resolver cannot perform.

This suite pins the sequence in every one of those places, and it pins the two rules a shorter
statement could quietly drop: replies come after the push, and every reply goes through the voice
rules.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / ".cursor" / "agents" / "crew-pr-resolver.md"
ACTING = ROOT / ".cursor" / "agents" / "crew-pr-resolver" / "references" / "acting-on-threads.md"
ORCHESTRATOR = ROOT / "rules" / "crew-orchestrator.mdc"
ROUTER = ROOT / "rules" / "crew-router.mdc"
README = ROOT / "README.md"
STAGE = "address-pr → commit → push → reply"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_resolver_stage_line_names_the_commit_before_the_reply() -> None:
    """The stage line is what a session reads first when it resolves a PR."""
    line = next(row for row in text(RESOLVER).splitlines() if row.startswith("**Workflow**: respond"))
    assert STAGE in line, line


def test_the_resolver_handoff_offers_review_without_gating_the_commit() -> None:
    """`crew review` is advisory here: the resolver cannot dispatch an inline-only reviewer."""
    handoff = next(row for row in text(RESOLVER).splitlines()
                   if row.startswith("> Next:") and "crew review" in row)
    assert "`crew review`" in handoff, "the handoff no longer offers the review"
    assert "crew commit" not in handoff, (
        "the handoff promises a separate commit the resolver already made"
    )


def test_the_resolver_never_posts_before_the_push() -> None:
    """The ordering rule lives where the run reads it, both in the stage and in Step 7."""
    step_seven = text(RESOLVER)
    step_seven = step_seven[step_seven.index("### Step 7:"):]
    assert re.search(r"no reply or resolution\s+happens before the\s+commit is pushed", step_seven), (
        "Step 7 does not order the reply after the push when edits were approved"
    )
    acting = text(ACTING)
    assert "## The order is fixed" in acting, "the reference states no order"
    assert "Reply on each approved thread." in acting, "the reference omits the reply step"
    order = acting[acting.index("## The order is fixed"):acting.index("## Code changes")]
    assert order.index("Commit, then push") < order.index("Reply on each approved thread"), (
        "the reference orders the reply before the push"
    )


def test_every_reply_applies_the_voice_rules() -> None:
    """A reply is public text under the author's name, so voice is part of the deliverable."""
    acting = text(ACTING)
    assert "Every reply is written under `~/.cursor/rules/voice.mdc`, with no exceptions" in acting, (
        "the voice rule no longer covers every verdict"
    )
    assert "post nothing" in acting, "an unreadable voice file does not stop the run"
    assert "voice.mdc" in text(RESOLVER), "the agent file does not carry the voice rule"


def test_the_orchestrator_workflow_lists_the_same_order() -> None:
    """`crew-orchestrator.mdc` owns the workflow list; a stale copy is a second source of truth."""
    body = text(ORCHESTRATOR)
    line = body[body.index("- **respond**"):]
    line = line[:line.index("\n\n")]
    assert STAGE in line, line


def test_the_router_allows_review_outside_the_pr_gate() -> None:
    """The invariant said review is pre-PR only, which refused the respond stage it now names."""
    invariant = text(ROUTER)
    start = invariant.index("- `crew review` is pre-commit")
    line = invariant[start:invariant.index("\n- ", start + 1)]
    assert "`respond`" in line, "the invariant does not name the respond workflow"
    assert "advisory" in line.lower(), (
        "the invariant does not say the respond review is advisory rather than a gate"
    )


def test_the_readme_names_the_stage_and_draws_it() -> None:
    """The diagram and the stage line are the two places a reader learns the sequence."""
    body = text(README)
    assert STAGE in body, "the stage line is stale"
    subgraph = body[body.index("subgraph respond"):]
    subgraph = subgraph[:subgraph.index("end")]
    assert 'resolver["🧩 pr-resolver"] --> rcommit' in subgraph, "the diagram skips the commit"
    assert 'rcommit --> rpush' in subgraph, "the commit does not reach the push"
    assert 'rpush --> rreply' in subgraph, "the diagram does not reply only after the push"


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"pass: {test.__name__}")
        except (AssertionError, StopIteration, ValueError) as error:
            failed += 1
            print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
