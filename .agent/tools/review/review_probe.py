#!/usr/bin/env python3
"""The probe's vocabulary and the score rules a measurement changes.

Consolidation sets a score from a measurement, and a measurement can refute as well as confirm. That
makes a refuting probe the one record that may move a score downward, which no reading may do: a read
resolves the unknown it went looking for, so it only ever raises one. Both score gates live here
because the probe exception is what separates them from a plain floor, and one named place beats
scattering negations through `review_gates`.

`PROBE_OUTCOMES` is the closed set `to_finding` validates `probe` against, the way `KINDS` validates
`kind`: an unvalidated value would land in `extra` and mean nothing to any gate.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from review_vocabulary import (
    ABSENT,
    ACTED_CONFIDENCE,
    PROBE_OUTCOMES,
    confidence_scale,
    confidence_value,
)

if TYPE_CHECKING:
    from review_models import Finding

ACTED_LABELS = {"blocking", "attention"}


def probe_value(finding: dict, index: int) -> object:
    """The `probe` outcome written, normalized; absence stays absent and a typo is refused here."""
    if "probe" not in finding:
        return ABSENT
    outcome = str(finding["probe"]).strip().lower()
    if outcome not in PROBE_OUTCOMES:
        raise ValueError(
            f"finding {index} has invalid probe: {finding['probe']!r} "
            f"(expected one of {', '.join(sorted(PROBE_OUTCOMES))})"
        )
    return outcome


def refuted(finding: "Finding") -> bool:
    """True when a probe refuted this finding, the only record that buys a lower score."""
    return finding.probe == "refuted"


def _validation(finding: "Finding") -> str:
    """The recorded sentence, as text; an absent or non-string value is no sentence at all."""
    value = finding.validation
    if value is ABSENT or not isinstance(value, str):
        return ""
    return value.strip()


def check_probe_move(finding: "Finding") -> None:
    """A probe recorded beside a score move carries the sentence the measurement earned.

    The sentence quotes the command and the observed output, because a score a probe set rests on a
    measurement rather than a reading and a later reader has to see which one. A probe that neither
    moved the score nor refuted the finding is already evidence the report carries, so it needs no
    second sentence; a refutation is a claim about the code and always carries its evidence.
    """
    moved = refuted(finding) or finding.confidence_from is not ABSENT
    if not moved or _validation(finding):
        return
    raise ValueError(
        f"finding {finding.title!r} records probe: {finding.probe} but no validation sentence; "
        f"quote the command and the observed output, scored on the {confidence_scale()} scale"
    )


def check_confidence_raise(finding: "Finding") -> None:
    """A changed score is a recorded change: it names where it came from and what settled it.

    Consolidation may raise a score by resolving an unknown through a read, and may lower one when a
    probe refutes the finding, so a record either way carries both halves: `confidence_from` for the
    old value and `validation` for the evidence. A downward move with no refuting probe is refused,
    because a reading that contradicts a score is not a measurement of it, and a refutation recorded
    beside a score that rose is refused for the mirror reason: a measurement cannot both refute a
    finding and make it more believable. A pair naming one score is not a move at all, so it is
    refused rather than logged as one.
    """
    if finding.confidence_from is ABSENT:
        return
    if finding.confidence is not ABSENT and finding.confidence < finding.confidence_from:
        if not refuted(finding):
            raise ValueError(
                f"finding {finding.title!r} records confidence_from {finding.confidence_from} above "
                f"its score {finding.confidence}; a raise only ever moves up, and only a refuting "
                "probe lowers a score, so record `probe: refuted` with the output that refuted it"
            )
    if finding.confidence is not ABSENT and finding.confidence > finding.confidence_from:
        if refuted(finding):
            raise ValueError(
                f"finding {finding.title!r} records probe: refuted beside a score that rose from "
                f"{finding.confidence_from} to {finding.confidence}; a refutation settles a finding "
                "against itself, so it cannot also raise the score — record `confirmed` or drop "
                "confidence_from"
            )
    if finding.confidence is not ABSENT and finding.confidence == finding.confidence_from:
        raise ValueError(
            f"finding {finding.title!r} records confidence_from {finding.confidence_from} equal to "
            "its score; an unchanged score is not a raise, so omit confidence_from"
        )
    if _validation(finding):
        return
    raise ValueError(
        f"finding {finding.title!r} moves its confidence from {finding.confidence_from} to "
        f"{finding.confidence} but records no validation sentence; name the read or the probe that "
        "settled it"
    )


def check_confidence_floor(finding: "Finding") -> None:
    """A finding the review asks the author to act on must be one the reviewer believes.

    A `blocking` or `attention` finding scored 1 or 2 is a request the reviewer does not stand behind,
    so it is refused by redirecting it to `[needs more info]` rather than by dropping it: the doubt is
    the signal worth keeping, and a question carries it as well as a demand does. A probe buys no
    exemption from this — a refuted request is not a request at all, so it drops or relabels, and the
    floor holds on both paths.
    """
    if finding.label not in ACTED_LABELS or finding.confidence is ABSENT:
        return
    if finding.confidence >= ACTED_CONFIDENCE:
        return
    if refuted(finding):
        raise ValueError(
            f"{finding.label} finding {finding.title!r} is scored {finding.confidence} and its "
            "probe refuted it; a refuted request is not a request, so drop it or relabel it "
            "'needs more info' carrying the observed output"
        )
    raise ValueError(
        f"{finding.label} finding {finding.title!r} is scored {finding.confidence}, below "
        f"{ACTED_CONFIDENCE}: a request the reviewer does not believe belongs as "
        "'needs more info', which states the stakes without asking for the change"
    )


def score_move(args) -> dict:
    """The score fields one decision records, refusing a move nothing settled.

    The journal's copy of the finding-side rule: `--confidence` is the score the finding was acted on
    under and `--confidence-from` the one it arrived with, so the join in `crew review-stats` reads
    evidence rather than the label the record carries. Both halves or neither, and either direction
    needs `--validation`, because `scored()` makes this journal authoritative — a move with no
    recorded evidence is the one record that could lie about where a score came from. A lower score
    needs `--probe refuted` on top, and a raise refuses that outcome for the mirror reason.
    """
    if (args.confidence is None) != (args.confidence_from is None):
        raise ValueError("--confidence and --confidence-from go together: a score move records both")
    if args.confidence is None:
        return {}
    if args.confidence == args.confidence_from:
        raise ValueError(
            f"--confidence and --confidence-from are both {args.confidence}; an unchanged score is "
            "not a move, so log it without both flags"
        )
    validation = (args.validation or "").strip()
    if not validation:
        raise ValueError(
            f"a score move from {args.confidence_from} to {args.confidence} needs --validation "
            "naming the read or the probe that settled it; a move with no recorded evidence is an "
            "assertion, and this journal is what `scored()` treats as authoritative"
        )
    outcome = getattr(args, "probe", None)
    if args.confidence < args.confidence_from and outcome != "refuted":
        raise ValueError(
            f"--confidence {args.confidence} is below --confidence-from {args.confidence_from}; "
            "a raise only ever moves up, so a lower score needs --probe refuted and the output "
            "that refuted it"
        )
    if args.confidence > args.confidence_from and outcome == "refuted":
        raise ValueError(
            f"--confidence {args.confidence} is above --confidence-from {args.confidence_from} with "
            "--probe refuted; a refutation settles a finding against itself, so it cannot also raise "
            "the score — record --probe confirmed or omit --probe"
        )
    fields = {"confidence": confidence_value(args.confidence),
              "confidence_from": confidence_value(args.confidence_from),
              "validation": validation}
    if outcome:
        fields["probe"] = outcome
    return fields
