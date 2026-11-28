"""The finding record and the probe rules that may change its score.

`read_findings` builds each `Finding` once at the JSON boundary; `to_json` writes back exactly the keys
that arrived (unknown ones stay in `extra`). A read only raises a score; a refuting probe is the one
record that may lower it. `PROBE_OUTCOMES` is the closed set `to_finding` validates `probe` against.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from crew.review.review_vocabulary import (
    ABSENT,
    ACTED_CONFIDENCE,
    DISPOSITIONS,
    EMITTED,
    KINDS,
    LABELS,
    PROBE_OUTCOMES,
    canonical_personas,
    confidence_scale,
    confidence_value,
    normalized_title,
)

ACTED_LABELS = {"blocking", "attention"}


def probe_value(finding: dict, index: int) -> object:
    """The `probe` outcome written, normalized; absence stays absent and a typo is refused here."""
    if "probe" not in finding:
        return ABSENT
    outcome = str(finding["probe"]).strip().lower()
    if outcome not in PROBE_OUTCOMES:
        raise ValueError(f"finding {index} has invalid probe: {finding['probe']!r} (expected one of {', '.join(sorted(PROBE_OUTCOMES))})")
    return outcome


def refuted(finding: Finding) -> bool:
    """True when a probe refuted this finding, the only record that buys a lower score."""
    return finding.probe == "refuted"


def _validation(finding: Finding) -> str:
    """The recorded sentence, as text; an absent or non-string value is no sentence at all."""
    value = finding.validation
    if value is ABSENT or not isinstance(value, str):
        return ""
    return value.strip()


def check_probe_move(finding: Finding) -> None:
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
        f"finding {finding.title!r} records probe: {finding.probe} but no validation sentence; quote the command and the observed output, scored on the {confidence_scale()} scale"
    )


def check_confidence_raise(finding: Finding) -> None:
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
            f"finding {finding.title!r} records confidence_from {finding.confidence_from} equal to its score; an unchanged score is not a raise, so omit confidence_from"
        )
    if _validation(finding):
        return
    raise ValueError(
        f"finding {finding.title!r} moves its confidence from {finding.confidence_from} to {finding.confidence} but records no validation sentence; name the read or the probe that settled it"
    )


def check_confidence_floor(finding: Finding) -> None:
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
    under and `--confidence-from` the one it arrived with, so the record carries evidence rather than
    a bare label. Both halves or neither, and either direction needs `--validation`, because a move
    with no recorded evidence is the one record that could lie about where a score came from. A lower score
    needs `--probe refuted` on top, and a raise refuses that outcome for the mirror reason.
    """
    if (args.confidence is None) != (args.confidence_from is None):
        raise ValueError("--confidence and --confidence-from go together: a score move records both")
    if args.confidence is None:
        return {}
    if args.confidence == args.confidence_from:
        raise ValueError(f"--confidence and --confidence-from are both {args.confidence}; an unchanged score is not a move, so log it without both flags")
    validation = (args.validation or "").strip()
    if not validation:
        raise ValueError(
            f"a score move from {args.confidence_from} to {args.confidence} needs --validation "
            "naming the read or the probe that settled it; a move with no recorded evidence is an "
            "assertion, and this journal is the only record of where a score came from"
        )
    outcome = getattr(args, "probe", None)
    if args.confidence < args.confidence_from and outcome != "refuted":
        raise ValueError(
            f"--confidence {args.confidence} is below --confidence-from {args.confidence_from}; a raise only ever moves up, so a lower score needs --probe refuted and the output that refuted it"
        )
    if args.confidence > args.confidence_from and outcome == "refuted":
        raise ValueError(
            f"--confidence {args.confidence} is above --confidence-from {args.confidence_from} with "
            "--probe refuted; a refutation settles a finding against itself, so it cannot also raise "
            "the score — record --probe confirmed or omit --probe"
        )
    fields = {"confidence": confidence_value(args.confidence), "confidence_from": confidence_value(args.confidence_from), "validation": validation}
    if outcome:
        fields["probe"] = outcome
    return fields


@dataclass
class Finding:
    """One review finding: the fields the gates read, plus everything else the persona wrote."""

    title: str
    label: str
    file: object = ABSENT
    line: object = ABSENT
    kind: object = ABSENT
    confidence: object = ABSENT
    confidence_from: object = ABSENT
    probe: object = ABSENT
    disposition: object = ABSENT
    persona: object = ABSENT
    hunks: object = ABSENT
    verified: object = ABSENT
    evidence: object = ABSENT
    validation: object = ABSENT
    excerpt: object = ABSENT
    comment: object = ABSENT
    suggestion: object = ABSENT
    reason: object = ABSENT
    memory_ids: object = ABSENT
    fingerprint: str = ""
    extra: dict = field(default_factory=dict)

    def is_emitted(self) -> bool:
        """True for a finding the review stands behind, as opposed to one it deferred."""
        return self.disposition in EMITTED

    def text(self, name: str) -> str:
        """An optional field rendered as text: empty when absent, else `str(value)` as before."""
        value = getattr(self, name)
        return "" if value is ABSENT else str(value)

    def to_json(self) -> dict:
        """The finding as JSON, with a key present only when the persona supplied it."""
        out: dict = {"title": self.title, "label": self.label}
        for key, value in (
            ("file", self.file),
            ("line", self.line),
            ("kind", self.kind),
            ("confidence", self.confidence),
            ("confidence_from", self.confidence_from),
            ("probe", self.probe),
            ("disposition", self.disposition),
            ("persona", self.persona),
            ("hunks", self.hunks),
            ("verified", self.verified),
            ("evidence", self.evidence),
            ("validation", self.validation),
            ("excerpt", self.excerpt),
            ("comment", self.comment),
            ("suggestion", self.suggestion),
            ("reason", self.reason),
            ("memory_ids", self.memory_ids),
        ):
            if value is not ABSENT:
                out[key] = value
        out.update(self.extra)
        out["fingerprint"] = self.fingerprint
        return out

    def merge(self, other: Finding) -> None:
        """Fold a duplicate in: union the personas each named and the hunks cited, losing neither.

        The score reconciles to the higher of the two, not to whichever lens ran first: candidate
        order must not decide whether the run clears the floor gate. `confidence_from` and `probe`
        drop with it, because a merge is not a read — a refutation one lens recorded cannot survive
        beside a merged score that rose. `excerpt`, `comment`, and `suggestion` keep the first value
        either lens supplied, since candidate order must not decide which reaches `comments.md`.
        """
        if isinstance(other.persona, list):
            for persona in other.persona:
                if not isinstance(self.persona, list):
                    self.persona = []
                if persona not in self.persona:
                    self.persona.append(persona)
        ours = [] if self.hunks is ABSENT else self.hunks
        theirs = [] if other.hunks is ABSENT else other.hunks
        if isinstance(ours, list) and isinstance(theirs, list):
            self.hunks = list(dict.fromkeys(ours + theirs))
        scores = [score for score in (self.confidence, other.confidence) if isinstance(score, int) and not isinstance(score, bool)]
        if scores and max(scores) != self.confidence:
            self.confidence = max(scores)
            # A merge is not a read: no single read produced this score, and a probe claimed a
            # measurement settled the finding one way the merged score may contradict.
            self.confidence_from = ABSENT
            self.probe = ABSENT
        for name in ("excerpt", "comment", "suggestion"):
            if getattr(self, name) is ABSENT and getattr(other, name) is not ABSENT:
                setattr(self, name, getattr(other, name))


def fingerprint(finding: Finding) -> str:
    """This defect in this file: a re-classification keeps the same identity."""
    material = "|".join(
        [str(finding.file if finding.file is not ABSENT else "").strip(), str(finding.label).strip().lower(), normalized_title(str(finding.title))]
    )
    return hashlib.sha1(material.encode()).hexdigest()


def kind_value(finding: dict, index: int) -> object:
    """The `kind` written, normalized. A typo is refused here; absence is left to `require_kind`."""
    if "kind" not in finding:
        return ABSENT
    kind = str(finding["kind"]).strip().lower()
    if kind not in KINDS:
        raise ValueError(f"finding {index} has invalid kind: {finding['kind']!r} (expected one of {', '.join(sorted(KINDS))})")
    return kind


def confidence_value_in(finding: dict, index: int) -> object:
    """The score a caller wrote, with absence left to `require_confidence` for the same reason."""
    if "confidence" not in finding:
        return ABSENT
    try:
        return confidence_value(finding["confidence"])
    except ValueError as error:
        raise ValueError(f"finding {index} {error}") from None


def confidence_from_in(finding: dict, index: int) -> object:
    """The score this finding carried before a raise, which is how a raise is told from a guess."""
    if "confidence_from" not in finding:
        return ABSENT
    try:
        return confidence_value(finding["confidence_from"])
    except ValueError as error:
        raise ValueError(f"finding {index} {error} (confidence_from)") from None


def to_finding(finding: dict, index: int) -> Finding:
    """Build the record from one JSON object, refusing a value the vocabulary does not allow."""
    if not isinstance(finding, dict) or not isinstance(finding.get("title"), str):
        raise ValueError(f"finding {index} requires a string title")
    label = str(finding.get("label", "")).lower()
    if label not in LABELS:
        raise ValueError(f"finding {index} has invalid label: {label!r}")
    disposition = finding.get("disposition")
    if disposition is not None and disposition not in DISPOSITIONS:
        raise ValueError(f"finding {index} has invalid disposition: {disposition!r}")
    kind = kind_value(finding, index)
    confidence = confidence_value_in(finding, index)
    confidence_from = confidence_from_in(finding, index)
    probe = probe_value(finding, index)
    persona = ABSENT
    if "persona" in finding or "personas" in finding:
        persona = canonical_personas(finding.get("persona", finding.get("personas")))
        if not persona:
            # An absent key is legacy data the tool must still re-read; an empty list is a caller
            # that meant to attribute the finding and did not, so it is refused here rather than
            # landing in an unattributed bucket that no precision number can ever explain.
            raise ValueError(
                f"finding {index} names no persona; attribute it to the one that raised it (or omit the key entirely for a record written before personas were recorded)"
            )
    known = {
        "title",
        "label",
        "file",
        "line",
        "kind",
        "confidence",
        "confidence_from",
        "probe",
        "disposition",
        "persona",
        "personas",
        "hunks",
        "verified",
        "evidence",
        "validation",
        "excerpt",
        "comment",
        "suggestion",
        "reason",
        "memory_ids",
        "fingerprint",
    }
    record = Finding(
        title=finding["title"],
        label=label,
        kind=kind,
        confidence=confidence,
        confidence_from=confidence_from,
        probe=probe,
        persona=persona,
        file=finding.get("file", ABSENT),
        line=finding.get("line", ABSENT),
        disposition=finding.get("disposition", ABSENT),
        hunks=finding.get("hunks", ABSENT),
        verified=finding.get("verified", ABSENT),
        evidence=finding.get("evidence", ABSENT),
        validation=finding.get("validation", ABSENT),
        excerpt=finding.get("excerpt", ABSENT),
        comment=finding.get("comment", ABSENT),
        suggestion=finding.get("suggestion", ABSENT),
        reason=finding.get("reason", ABSENT),
        memory_ids=finding.get("memory_ids", ABSENT),
        extra={key: value for key, value in finding.items() if key not in known},
    )
    record.fingerprint = fingerprint(record)
    return record
