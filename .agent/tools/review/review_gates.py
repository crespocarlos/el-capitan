#!/usr/bin/env python3
"""The finding gates: what one finding must satisfy, and what a reviewed set must satisfy.

Two checks with different inputs, deliberately separate. `check_findings` is per-finding and needs
no changed-file list; `check_strict` adds the path-scoped evidence rule and the two output caps.

They are split because `persist` used to reach every per-finding rule only when `--files` carried a
path, and a spec or idea review has no path list to pass: the result was a `verified: true` finding
with no validation sentence persisting successfully in exactly the modes that pass no files, while
both `TOOLS.md` and the consolidation protocol said the sentence was required.
"""
from __future__ import annotations

from review_models import ABSENT, Finding, require_kind
from review_vocabulary import EVIDENCE_LOCATION, MAX_FINDINGS, MAX_NITS


def check_findings(findings: list[Finding]) -> None:
    """Per-finding rules that need no changed-file list."""
    for f in findings:
        require_kind(f)
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
    """The per-finding rules plus the ones that need the reviewed file set and the two caps."""
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
