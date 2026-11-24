#!/usr/bin/env python3
"""Contract checks for the reviewer eval scorer in evals/reviewer/run.py.

The scorer is what turns a persona's response into the numbers a regression gate reads, so a bug
here silently makes every persona look better or worse than it is. Two real defects motivate these
checks: precision credited a finding on its hint alone, so a right issue under the wrong severity
scored 1.0; and finding boundaries were split only on `1.`, so every bulleted response scored zero
recall. Both are measured here without an API key.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("reviewer_run", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def fixture(*findings: dict) -> dict:
    return {"expected_findings": list(findings)}


def expected(severity: str, hint: str, persona: str = "reviewer-adversarial") -> dict:
    return {"persona": persona, "severity": severity, "match_hint": hint}


def check_accepts_every_finding_marker() -> None:
    """A finding is a finding whatever list marker the persona used."""
    cases = {
        "numbered dot": "1. [blocking] src/a.ts:5 null deref\n",
        "numbered paren": "1) [blocking] src/a.ts:5 null deref\n",
        "bare number": "1 [blocking] src/a.ts:5 null deref\n",
        "dash bullet": "- [blocking] src/a.ts:5 null deref\n",
        "star bullet": "* [blocking] src/a.ts:5 null deref\n",
        "unmarked label": "[blocking] src/a.ts:5 null deref\n",
        "bold label": "1. **[blocking]** src/a.ts:5 null deref\n",
    }
    for name, output in cases.items():
        _, recall, matched, _ = MODULE.compute_precision_recall(
            output, fixture(expected("blocking", "null deref")), "reviewer-adversarial"
        )
        assert recall == 1.0, f"{name}: recall {recall}"


def check_wrong_severity_earns_no_precision() -> None:
    """A correct issue under the wrong label is a miss, not a hit."""
    output = "1. [attention] src/a.ts:5 null deref on an empty list\n"
    precision, recall, _, unmatched = MODULE.compute_precision_recall(
        output, fixture(expected("blocking", "null deref")), "reviewer-adversarial"
    )
    assert recall == 0.0, recall
    assert precision == 0.0, precision
    assert len(unmatched) == 1, unmatched


def check_extra_findings_lower_precision() -> None:
    """One correct and one invented finding is 0.5 precision, not 1.0."""
    output = (
        "1. [blocking] src/a.ts:5 null deref\n"
        "2. [attention] src/b.ts:9 naming preference\n"
    )
    precision, recall, _, _ = MODULE.compute_precision_recall(
        output, fixture(expected("blocking", "null deref")), "reviewer-adversarial"
    )
    assert (precision, recall) == (0.5, 1.0), (precision, recall)


def check_hint_in_one_finding_does_not_credit_another() -> None:
    """A label from one finding and a hint from another must not combine."""
    output = (
        "1. [blocking] src/a.ts:5 unrelated guard\n"
        "2. [attention] src/b.ts:9 the null deref is discussed here without a label\n"
    )
    precision, recall, _, _ = MODULE.compute_precision_recall(
        output, fixture(expected("blocking", "null deref")), "reviewer-adversarial"
    )
    assert recall == 0.0, recall
    assert precision == 0.0, precision


def check_clean_fixture_scores_no_false_positive() -> None:
    """Saying nothing on a clean fixture is correct, not a zero."""
    clean = {"expected_findings": [], "clean_for": ["reviewer-adversarial"]}
    precision, recall, _, _ = MODULE.compute_precision_recall(
        "1. [blocking] src/a.ts:5 invented\n", clean, "reviewer-adversarial"
    )
    # No expected findings for this persona means the pair is excluded from aggregation.
    assert precision is None and recall is None, (precision, recall)


def check_scope_violations_count_only_for_code_quality() -> None:
    output = "1. [attention] src/a.ts:5 the coupling here is wrong\n"
    assert MODULE.score_scope_violations(output, "reviewer-code-quality") >= 1
    assert MODULE.score_scope_violations(output, "reviewer-adversarial") == 0


def check_spec_fixtures_skip_precision() -> None:
    """A spec fixture has no severity, so precision is excluded rather than invented."""
    spec_fixture = fixture({"persona": "specwriter-scope", "severity": None, "match_hint": "granularity"})
    precision, recall, _, _ = MODULE.compute_precision_recall(
        "The task list violates granularity.\n", spec_fixture, "specwriter-scope"
    )
    assert precision is None and recall == 1.0, (precision, recall)


def check_a_spec_hint_is_absent_from_its_own_content() -> None:
    """A spec fixture's hint must be a diagnosis the reply introduces, not a word the spec supplies.

    Spec fixtures score on hint presence alone (`run.py:186-191`), with no label and no finding
    boundary. A hint drawn from the spec's own vocabulary — or from the sentences the persona is told
    to quote — credits a reply that only echoed the input, so recall rises while nothing was found.
    """
    for entry in MODULE.load_fixtures():
        if entry.get("input_type", "diff") != "spec":
            continue
        content = entry["content"].lower()
        for finding in entry.get("expected_findings", []):
            hint = finding["match_hint"].lower()
            assert hint not in content, (
                f"{entry['id']}: hint {hint!r} already appears in the fixture's own content, so a "
                f"reply that quotes the spec scores recall without producing a finding"
            )


def check_every_lens_has_fixture_coverage() -> None:
    """Each reviewer persona needs at least one fixture that scores it, and a clean control.

    A persona with one fixture cannot regress visibly, and a lens with only positive fixtures has
    no way to catch a persona that manufactures findings outside its lane.
    """
    fixtures = MODULE.load_fixtures()
    positive: dict[str, int] = {}
    clean: dict[str, int] = {}
    for entry in fixtures:
        for finding in entry.get("expected_findings", []):
            positive[finding["persona"]] = positive.get(finding["persona"], 0) + 1
        for persona in entry.get("clean_for", []):
            clean[persona] = clean.get(persona, 0) + 1
    lens = [
        "reviewer-adversarial",
        "reviewer-architecture",
        "reviewer-code-quality",
        "reviewer-product-flow",
        "reviewer-prompt-quality",
    ]
    for persona in lens:
        assert positive.get(persona, 0) >= 1, f"{persona} has no fixture that scores it"
        assert clean.get(persona, 0) >= 1, f"{persona} has no clean control fixture"
    # Explorer reports prior art, not findings, so it is covered by a `severity: null` fixture.
    assert positive.get("reviewer-explorer", 0) >= 1, "reviewer-explorer has no fixture"


def check_a_scored_label_still_scores() -> None:
    """`[attention · 4]` is a labelled finding, not an unlabelled one.

    The score is rendered in the label column, so a scorer that matched a bare `]` would credit no
    banded finding and report a regression the prompt change did not cause.
    """
    output = "1. [blocking · 5] src/a.ts:5 null deref\n"
    precision, recall, _, _ = MODULE.compute_precision_recall(
        output, fixture(expected("blocking", "null deref")), "reviewer-adversarial"
    )
    assert (precision, recall) == (1.0, 1.0), (precision, recall)
    # The wrong severity stays a miss, so the suffix did not widen what counts as correct.
    wrong = "1. [attention · 5] src/a.ts:5 null deref\n"
    assert MODULE.compute_precision_recall(
        wrong, fixture(expected("blocking", "null deref")), "reviewer-adversarial"
    )[:2] == (0.0, 0.0)


def check_scored_bare_labels_stay_separate_findings() -> None:
    """Two unnumbered scored findings are two units, so a hint cannot cross between them.

    `FINDING_START` splits units and `LABELS_IN_UNIT` labels them; widening only the second lets one
    unit carry a hint from one finding and a label from another, which inflates precision.
    """
    output = "[attention · 4] src/a.ts:5 the timeout is dropped\n[blocking · 5] src/b.ts:9 null deref\n"
    assert len(MODULE.finding_units(output)) == 2, MODULE.finding_units(output)
    matched = "src/b.ts:9 null deref"
    precision, recall, _, _ = MODULE.compute_precision_recall(
        output, fixture(expected("blocking", matched)), "reviewer-adversarial"
    )
    assert (precision, recall) == (0.5, 1.0), (precision, recall)
    # And with the correct hint on the correct label it is a full hit, in either order.
    hit = "[blocking · 5] src/b.ts:9 null deref\n[attention · 4] src/a.ts:5 the timeout is dropped\n"
    assert MODULE.compute_precision_recall(
        hit, fixture(expected("blocking", matched)), "reviewer-adversarial"
    )[:2] == (0.5, 1.0)


CHECKS = [
    check_accepts_every_finding_marker,
    check_wrong_severity_earns_no_precision,
    check_extra_findings_lower_precision,
    check_hint_in_one_finding_does_not_credit_another,
    check_clean_fixture_scores_no_false_positive,
    check_scope_violations_count_only_for_code_quality,
    check_spec_fixtures_skip_precision,
    check_a_spec_hint_is_absent_from_its_own_content,
    check_every_lens_has_fixture_coverage,
    check_a_scored_label_still_scores,
    check_scored_bare_labels_stay_separate_findings,
]


def main() -> int:
    failures = 0
    for check in CHECKS:
        try:
            check()
        except AssertionError as error:
            failures += 1
            print(f"FAIL: {check.__name__}: {error}")
        else:
            print(f"pass: {check.__name__}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
