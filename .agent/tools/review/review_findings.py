#!/usr/bin/env python3
"""Finding model: vocabulary, parsing, validation, fingerprints, and normalization.

Split out of `crew-review-findings.py` so the CLI stays an argparse entry point. This module owns
what a finding is and what one finding must satisfy; the persona, layer, and report concerns
live in their own modules and import from here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from lib.files import atomic_write  # noqa: F401  re-exported by crew-review-findings.py

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
# Severity says how bad; `kind` says what sort of defect, and the two are independent. Kept out of
# `fingerprint` because identity is "this defect in this file": re-classifying must not split one.
KINDS = {"security", "correctness", "reliability", "documentation", "testing", "other"}
OUTCOMES = {"fixed", "rejected", "deferred", "skipped"}
PERSONAS = {"adversarial", "architecture", "code-quality", "product-flow", "prompt-quality", "explorer"}
LEGACY_PERSONAS = {"fresh-eyes"}  # removed persona; kept so old review dirs still normalize
CODE_MODES = {"self", "changes", "pr"}
# Closed vocabulary for a leading `status:` line in `<persona>.out.md`. Only these three
# failure words are authoritative; anything else (`dispatched`, `done`) falls through to
# the content check, so a placeholder cannot claim a persona completed.
PERSONA_STATUSES = {"failed", "skipped", "truncated"}
# Tiered output cap, counted separately so polish cannot evict severity: a nit has a 4-slot budget
# and non-nits a 12-slot one, so a flat cap cannot bind a real finding out to make room for polish.
MAX_FINDINGS = 12
MAX_NITS = 4
EMITTED = {"patch", "decide"}
EVIDENCE_LOCATION = re.compile(r"^[^:\s][^:]*:\d+(?:@[0-9a-f]{7,40})?$")
SELECT_RULES = {
    "prompt-quality": re.compile(r"(^|/)(agents|skills|evals)/|\.mdc$"),
    "architecture": re.compile(r"router|orchestrator|install|dispatch|tools\.json|(^|/)\.claude/"),
}
DISPOSITIONS = {"patch", "decide", "defer", "dropped", "merged"}
# Absent is not the same as empty: `kind` and `evidence` are optional, and a record must not grow a
# key the persona never wrote, because `normalize` republishes the finding for later steps to parse.
ABSENT = object()


@dataclass
class Finding:
    """One review finding: the fields the gates read, plus everything else the persona wrote.

    Built once by `read_findings` at the JSON boundary, then passed inward, so no gate re-derives
    the shape from string keys. `to_json` writes back exactly the keys that arrived — an unknown
    key stays in `extra` rather than being silently dropped on the way through `normalize`.
    """

    title: str
    label: str
    file: object = ABSENT
    line: object = ABSENT
    kind: object = ABSENT
    disposition: object = ABSENT
    persona: object = ABSENT
    hunks: object = ABSENT
    verified: object = ABSENT
    evidence: object = ABSENT
    validation: object = ABSENT
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
        for key, value in (("file", self.file), ("line", self.line), ("kind", self.kind),
                           ("disposition", self.disposition), ("persona", self.persona),
                           ("hunks", self.hunks), ("verified", self.verified),
                           ("evidence", self.evidence), ("validation", self.validation),
                           ("reason", self.reason), ("memory_ids", self.memory_ids)):
            if value is not ABSENT:
                out[key] = value
        out.update(self.extra)
        out["fingerprint"] = self.fingerprint
        return out

    def merge(self, other: Finding) -> None:
        """Fold a duplicate into this finding: union the personas each one named and the hunks cited.

        A finding that only one of the two anchored still inherits the other's anchors, because the
        merged record is what later steps read; leaving the first one's empty list would lose the
        hunk the duplicate cited.
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


def mode_arg(value: str) -> str:
    """Normalize a mode before the choices check, so `--mode PR` is accepted.

    The protocol names the mode `PR` while the CLI enumerates lowercase values, which made a
    correct review fail on an argparse error before any persona was dispatched. Accept the
    documented casing and the `auto`/`auto-loop` modifiers instead of failing the run.
    """
    normalized = value.strip().lower()
    for modifier in (" auto-loop", " auto", "-auto-loop", "-auto"):
        normalized = normalized.replace(modifier, "")
    return normalized


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def canonical_personas(value: object, *, split_commas: bool = True) -> list[str]:
    if not split_commas and isinstance(value, str) and "," in value:
        raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
    raw = value if isinstance(value, list) else str(value or "").split(",")
    result = []
    for item in raw:
        name = re.sub(r"\s+", "-", str(item).strip().lower()).removeprefix("reviewer-")
        if not split_commas and "," in str(item):
            raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
        if not name:
            continue
        if name not in PERSONAS | LEGACY_PERSONAS:
            raise ValueError(f"unknown persona: {item!r} (expected one of {sorted(PERSONAS)})")
        if name not in result:
            result.append(name)
    return result


def read_json_object(path: Path, key: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path} has no {key!r} list")
    return payload


def fingerprint(finding: Finding) -> str:
    material = "|".join(
        [
            str(finding.file if finding.file is not ABSENT else "").strip(),
            str(finding.label).strip().lower(),
            normalized_title(str(finding.title)),
        ]
    )
    return hashlib.sha1(material.encode()).hexdigest()


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
    # Optional: every review recorded before `kind` existed has none, and refusing those would make
    # the tool unable to re-read its own history. A typo is different — an unknown value is rejected
    # so the vocabulary cannot drift one spelling at a time.
    kind = ABSENT
    if "kind" in finding:
        kind = str(finding["kind"]).strip().lower()
        if kind not in KINDS:
            raise ValueError(
                f"finding {index} has invalid kind: {finding['kind']!r} "
                f"(expected one of {', '.join(sorted(KINDS))})"
            )
    persona = ABSENT
    if "persona" in finding or "personas" in finding:
        persona = canonical_personas(finding.get("persona", finding.get("personas")))
    known = {"title", "label", "file", "line", "kind", "disposition", "persona", "personas",
             "hunks", "verified", "evidence", "validation", "reason", "memory_ids", "fingerprint"}
    record = Finding(
        title=finding["title"], label=label, kind=kind, persona=persona,
        file=finding.get("file", ABSENT), line=finding.get("line", ABSENT),
        disposition=finding.get("disposition", ABSENT), hunks=finding.get("hunks", ABSENT),
        verified=finding.get("verified", ABSENT), evidence=finding.get("evidence", ABSENT),
        validation=finding.get("validation", ABSENT), reason=finding.get("reason", ABSENT),
        memory_ids=finding.get("memory_ids", ABSENT),
        extra={key: value for key, value in finding.items() if key not in known},
    )
    record.fingerprint = fingerprint(record)
    return record


def read_findings(path: Path) -> list[Finding]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        raise ValueError("finding input must be a JSON list or an object with a findings list")
    return [to_finding(finding, index) for index, finding in enumerate(data, 1)]


def check_findings(findings: list[Finding]) -> None:
    """Per-finding rules that need no changed-file list.

    Split out from `check_strict` because `persist` used to reach every per-finding rule only when
    `--files` carried at least one path, and a spec or idea review has no path list to pass. The
    result was a `verified: true` finding with no validation sentence persisting successfully in
    exactly the modes that pass no files, while both `TOOLS.md` and the consolidation protocol said
    the sentence was required.
    """
    for f in findings:
        evidence = None if f.evidence is ABSENT else f.evidence
        if f.label in {"blocking", "attention"} and not (
            f.verified is True
            and isinstance(evidence, str)
            and EVIDENCE_LOCATION.fullmatch(evidence)
        ):
            raise ValueError(
                f"unverified {f.label} finding {f.title!r}: set verified=true with evidence as path:line "
                "(or path:line@headSHA), "
                "or downgrade to 'needs more info'"
            )
        if evidence is not None and not isinstance(evidence, str):
            # A type error is a caller bug, not an absent location: fail loudly rather than let the
            # file gate below skip a malformed value as though the finding had cited nothing.
            raise ValueError(
                f"finding {f.title!r}: evidence must be a string path:line, got {type(evidence).__name__}"
            )
        if f.verified is True:
            # `verified: true` asserts a second read happened. Without its conclusion recorded, the
            # next reader has only a boolean and an anchor and cannot tell why the check passed —
            # which is the reasoning the consolidator used to discard.
            validation = None if f.validation is ABSENT else f.validation
            if not isinstance(validation, str) or not validation.strip():
                raise ValueError(
                    f"finding {f.title!r} is verified but records no validation sentence; "
                    "state what the verification read and concluded"
                )


def is_path_prefix(name: str, location: str) -> bool:
    """True when two evidence paths name the same path, allowing one to be a trailing suffix.

    A finding may cite `profile.ts` while the reviewed set names `src/user/profile.ts`, and the
    reverse occasionally happens when a persona anchors on an absolute path. The suffix must land on
    a `/` boundary, so `profile.ts` does not match `myprofile.ts`. This compares already-normalized
    evidence strings rather than joining filesystem paths: `PurePosixPath` would collapse `..` and
    drop a leading separator, changing which evidence is accepted.
    """
    if name == location:
        return True
    shorter, longer = (name, location) if len(name) <= len(location) else (location, name)
    return longer.endswith(f"/{shorter}")


def check_strict(findings: list[Finding], files: list[str] | None = None) -> None:
    emitted = [f for f in findings if f.is_emitted()]
    check_findings(emitted)
    for f in emitted:
        evidence = None if f.evidence is ABSENT else f.evidence
        if files and evidence:
            # Shape is not enough: evidence must point at something under review, or a
            # finding about an untouched file is reported as verified. A finding with no
            # evidence is allowed here — `blocking`/`attention` were already required to have
            # it above, and a nit may stay unanchored, so there is nothing to check.
            location = evidence.split("@", 1)[0].rsplit(":", 1)[0]
            if not any(is_path_prefix(name, location) for name in files):
                raise ValueError(
                    f"finding {f.title!r} cites {location}, which is not in the reviewed file set"
                )
    nits = [f for f in emitted if f.label == "nit"]
    severity = len(emitted) - len(nits)
    # Counted separately: a nit must never consume a severity slot, so the two budgets do not
    # trade against each other.
    if severity > MAX_FINDINGS:
        raise ValueError(
            f"{severity} emitted non-nit findings exceed the cap of {MAX_FINDINGS}; "
            "drop the lowest severity or route pre-existing findings to 'defer'"
        )
    if len(nits) > MAX_NITS:
        raise ValueError(
            f"{len(nits)} emitted nits exceed the cap of {MAX_NITS}; keep the ones with a stated cost "
            "and drop the rest, so polish cannot occupy a severity slot"
        )


def normalize(args: argparse.Namespace) -> int:
    """Deduplicate exact fingerprints and, under `--strict`, apply the per-finding gates."""
    from review_layers import check_hunk_refs, hunk_ids

    findings = read_findings(args.input)
    if args.strict and args.hunks:
        # Validate every candidate before deduplication: otherwise a duplicate's malformed
        # attribution is silently discarded, or its valid hunk never reaches the coverage report.
        check_hunk_refs(findings, hunk_ids(args.hunks))
    kept, duplicates = {}, []
    for finding in findings:
        existing = kept.get(finding.fingerprint)
        if existing:
            existing.merge(finding)
            duplicates.append(
                {"fingerprint": finding.fingerprint, "duplicate_of": existing.title, "title": finding.title}
            )
        else:
            kept[finding.fingerprint] = finding
    if args.strict:
        check_strict(list(kept.values()), args.files)
    payload = {"findings": [finding.to_json() for finding in kept.values()], "duplicates": duplicates}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0
