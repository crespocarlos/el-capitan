#!/usr/bin/env python3
"""The shared probe contract: an unsettled claim is measured, not guessed.

The resolver has probed its threads since the probe landed there; every other read-only persona could
only read, and a doubt the code would answer in one run went to a human as a question. This suite pins
the move that closes the gap — one worker, dispatched by an orchestrator, returning evidence — and the
four ways it could go wrong: a probe per claim instead of one run per review, a probe that leaves the
tree changed, a score no measurement earned, and a probe reported for work that never executed.

The run is a prompt, so the protocol text is the artifact a suite can check; the score rules are
checked through the CLI, because a gate result is the real contract. Every assertion here is on prose or
on a command's output, never on a private function.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".cursor" / "agents"
PROBE_REFERENCE = AGENTS / "references" / "probing.md"
REVIEWER = AGENTS / "crew-reviewer.md"
CONSOLIDATION = AGENTS / "crew-reviewer" / "references" / "consolidation.md"
WORKER = AGENTS / "reviewer-probe.md"
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-review-findings.py"


def reference() -> str:
    return PROBE_REFERENCE.read_text(encoding="utf-8")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


def base(**overrides: object) -> dict:
    """A complete `attention` finding at confidence 4; an override replaces or drops a field."""
    finding = {"title": "Guard missing", "label": "attention", "file": "a.ts", "line": 3,
               "disposition": "patch", "verified": True, "evidence": "a.ts:3",
               "kind": "correctness", "confidence": 4,
               "validation": "read a.ts:1-9; the guard is absent"}
    for key, value in overrides.items():
        if value is None:
            finding.pop(key, None)
        else:
            finding[key] = value
    return finding


def normalize(tmp: Path, payload: list[dict]) -> subprocess.CompletedProcess:
    source = tmp / "candidates.json"
    source.write_text(json.dumps(payload))
    return run("normalize", str(source))


def outcome(tmp: Path, *extra: str) -> subprocess.CompletedProcess:
    directory = tmp / "review" / "ts"
    directory.mkdir(parents=True, exist_ok=True)
    return run("outcome", "--review-dir", str(directory), "--fingerprint", "c3",
               "--persona", "adversarial", "--label", "attention", "--outcome", "fixed",
               "--reason", "applied", *extra)


# --- the dispatch rule ------------------------------------------------------


def test_the_worker_exists_and_is_dispatched_by_an_orchestrator_only() -> None:
    """A persona cannot run code, so a persona must never be the caller of the worker that does."""
    body = WORKER.read_text(encoding="utf-8")
    assert "orchestrator" in body and "never by a persona" in body, (
        "the worker does not say who may dispatch it"
    )
    assert "evidence" in body.lower(), "the worker does not say it returns evidence rather than verdicts"
    assert "references/probing.md" in body, "the worker does not link the probe lifecycle"


def test_one_dispatch_carries_every_unsettled_claim() -> None:
    """One run per review, not one per claim: the tree comparison only means something that way."""
    text = flatten(REVIEWER.read_text(encoding="utf-8"))
    assert "one `reviewer-probe` run" in text, (
        "the reviewer does not dispatch a single probe run for the review"
    )
    assert "every unsettled finding" in text, "the reviewer does not collect all the unsettled claims"
    body = flatten(reference())
    assert "every unsettled claim" in body or "all of them" in body, (
        "the reference does not state that one run carries every unsettled claim"
    )


def test_the_worker_is_not_readonly_and_is_exempt_from_the_readonly_rule() -> None:
    """A probe is a throwaway artifact: `readonly` would block the one thing the worker exists to do."""
    frontmatter = WORKER.read_text(encoding="utf-8").split("---", 2)[1]
    assert "readonly:" not in frontmatter, "the probe worker declares readonly and could not run anything"
    maintenance = ROOT / ".agent" / "tools" / "maintenance"
    if str(maintenance) not in sys.path:
        sys.path.insert(0, str(maintenance))
    from lint_prompts import WRITE_CAPABLE_AGENTS

    assert "reviewer-probe" in WRITE_CAPABLE_AGENTS, "the worker has no reviewed exemption"


# --- the score, moved by evidence -------------------------------------------


def test_a_confirming_probe_may_raise_the_score(tmp: Path) -> None:
    """A measurement that confirms a finding outranks a reading that merely suggests it."""
    raised = base(confidence=4, confidence_from=2, probe="confirmed",
                  validation="ran `node --test guard.test.js`; the assertion fails without the guard")
    result = normalize(tmp, [raised])
    assert result.returncode == 0, result.stderr
    stored = json.loads(result.stdout)["findings"][0]
    assert stored["probe"] == "confirmed" and stored["confidence"] == 4, stored


def test_a_refuting_probe_may_lower_the_score(tmp: Path) -> None:
    """The exception a probe buys: a refuted finding may sit below what a read could ever justify."""
    lowered = base(label="needs more info", disposition="decide", confidence=1, confidence_from=4,
                   probe="refuted", verified=None, evidence=None,
                   validation="ran `pytest test_guard.py`; the guard fires before the retry, so 3 rows")
    result = normalize(tmp, [lowered])
    assert result.returncode == 0, result.stderr
    stored = json.loads(result.stdout)["findings"][0]
    assert stored["confidence"] == 1 and stored["probe"] == "refuted", stored


def test_a_lowered_score_without_a_refuting_probe_is_refused(tmp: Path) -> None:
    """A reading that contradicts a score is not a measurement of it, so it may not lower one."""
    dropped = base(label="needs more info", disposition="decide", confidence=2, confidence_from=4,
                   validation="read a.ts:1-9 again; the guard is there after all")
    result = normalize(tmp, [dropped])
    assert result.returncode == 2, result.stdout
    assert "only ever moves up" in result.stderr, result.stderr
    assert "refuted" in result.stderr, "the refusal does not name the one record that would allow it"


def test_a_refuted_request_leaves_the_acted_label(tmp: Path) -> None:
    """A `Reject` at 3 overturned by a refuting probe cannot persist as a request scored 2."""
    refused = base(confidence=2, confidence_from=3, probe="refuted",
                   validation="ran `pytest test_retry.py`; the loop fires once, so no double-fire")
    result = normalize(tmp, [refused])
    assert result.returncode == 2, result.stdout
    assert "refuted request is not a request" in result.stderr, result.stderr
    assert "needs more info" in result.stderr, "the refusal does not name the label that carries it"
    # The same refutation is accepted once the finding stops asking for a change.
    accepted = {**refused, "label": "needs more info", "disposition": "decide",
                "verified": None, "evidence": None}
    assert normalize(tmp, [accepted]).returncode == 0, "a refuted finding cannot be relabelled"


def test_a_probe_outcome_outside_the_vocabulary_is_refused_at_parse(tmp: Path) -> None:
    """An unvalidated value lands in `extra` and means nothing to a gate, so parse refuses it."""
    for bad in ("refutes", "CONFIRMED-ish", "", 7):
        result = normalize(tmp, [base(probe=bad)])
        assert result.returncode == 2, f"{bad!r} was accepted: {result.stdout}"
        assert "invalid probe" in result.stderr, f"{bad!r}: {result.stderr}"
        assert "confirmed, inconclusive, refuted" in result.stderr, (
            f"{bad!r} does not name the allowed set: {result.stderr}"
        )


def test_a_score_move_recorded_as_an_outcome_needs_its_evidence(tmp: Path) -> None:
    """`scored()` trusts the journal, so a move logged there carries the same evidence a record does."""
    unevidenced = outcome(tmp, "--confidence", "4", "--confidence-from", "2")
    assert unevidenced.returncode == 2 and "--validation" in unevidenced.stderr, unevidenced.stderr
    lowered = outcome(tmp, "--confidence", "1", "--confidence-from", "4",
                      "--validation", "ran the probe; the guard fires first")
    assert lowered.returncode == 2 and "--probe refuted" in lowered.stderr, lowered.stderr
    refuted = outcome(tmp, "--confidence", "1", "--confidence-from", "4",
                      "--validation", "ran the probe; the guard fires first", "--probe", "refuted")
    assert refuted.returncode == 0, refuted.stderr
    assert json.loads(refuted.stdout)["probe"] == "refuted", refuted.stdout
    # A downward move needs the evidence too: this is the case that let the authoritative journal
    # record a lowered score with no reason, while the finding gate demanded one.
    bare = outcome(tmp, "--confidence", "1", "--confidence-from", "4", "--probe", "refuted")
    assert bare.returncode == 2 and "--validation" in bare.stderr, bare.stderr
    # And a refutation cannot ride along with a score that rose, in either layer.
    rising = outcome(tmp, "--confidence", "4", "--confidence-from", "2",
                     "--validation", "ran the probe; it confirms the guard fires", "--probe", "refuted")
    assert rising.returncode == 2, rising.stdout
    assert "cannot also raise" in rising.stderr, rising.stderr


def test_a_probe_with_no_score_move_still_carries_its_sentence(tmp: Path) -> None:
    """The gate call in `check_findings` is the only thing refusing this shape, so pin it here.

    Deleting the `check_probe_move(f)` line left the whole suite green before this test existed. The
    shape has to be one no other gate objects to: a `nit` (no floor, no `verified` requirement), no
    `confidence_from` (the raise gate returns early), and no validation sentence — which leaves
    `probe: refuted` as the single thing wrong with it.
    """
    refused = base(label="nit", probe="refuted", validation=None, verified=None, evidence=None)
    result = normalize(tmp, [refused])
    assert result.returncode == 2, result.stdout
    assert "no validation sentence" in result.stderr, result.stderr
    # The same record with its sentence is accepted, so the refusal is about the sentence alone.
    accepted = base(label="nit", probe="refuted", verified=None, evidence=None,
                    validation="ran the probe; the guard fires once")
    assert normalize(tmp, [accepted]).returncode == 0


# --- the paths that must not move anything ----------------------------------


def test_a_probe_that_cannot_run_keeps_the_score_and_says_why() -> None:
    """A guess dressed as a measurement is worse than no probe, so the text forbids both."""
    body = reference()
    assert "cannot run" in body, "the infeasible case is missing"
    assert "keeps its score" in body, "a probe that did not run is allowed to change the score"
    assert "dressed as a measurement" in body, "the guess is not refused in so many words"


def test_the_clean_tree_rule_is_a_snapshot_compare() -> None:
    """A reviewer's tree already holds the edits under review, so empty output is unachievable."""
    body = reference()
    assert "porcelain" in body, "the clean-tree check is not named"
    assert "before the probe" in body, "the reading taken before the probe is unstated"
    assert "identical output" in body, "the rule is not stated as a compare"
    assert "emptiness is not" in body, "the text still implies an empty tree is the requirement"


def flatten(text: str) -> str:
    """The prose with its line breaks collapsed, so an assertion states a phrase, not a wrap."""
    return " ".join(text.split())


def test_consolidation_puts_the_probe_inside_the_single_pass() -> None:
    """The probe is part of the one pass, so the paragraph must not read as a second one."""
    body = flatten(CONSOLIDATION.read_text(encoding="utf-8"))
    assert "one pass, one read or one probe" in body.lower(), (
        "the single-pass sentence does not account for the probe"
    )
    assert "may lower it" in body, "consolidation never lets a measurement lower a score"
    assert "`probe: refuted`" in body, "the record key that permits a lower score is unnamed"


def test_pr_mode_never_dispatches_a_probe() -> None:
    """A PR review has no checkout, so a PR finding keeps its question and names the blocked probe."""
    body = reference()
    assert "PR mode never dispatches" in body, "the PR-mode refusal is missing"
    assert "blocked probe" in body, "an unprobed PR finding has no required shape"
    assert "PR mode never does this" in flatten(REVIEWER.read_text(encoding="utf-8")), (
        "the reviewer's own dispatch sentence omits the PR-mode refusal"
    )


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                if test.__code__.co_argcount:
                    test(Path(directory))
                else:
                    test()
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
