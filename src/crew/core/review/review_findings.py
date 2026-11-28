"""The finding gates and the `normalize`/`validate` work over a findings file.

`check_findings` is per finding (spec and idea reviews pass no `--files`); `check_strict` adds the
path-scoped evidence rule and the output caps. With `--repo`, a path outside the diff that is tracked
at the reviewed head may carry a finding (`anchor: "non-hunk"`); an untracked path is refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crew.core.review.review_models import Finding, check_confidence_floor, check_confidence_raise, check_probe_move, to_finding
from crew.core.review.review_vocabulary import ABSENT, EVIDENCE_LOCATION, KINDS, MAX_FINDINGS, MAX_NITS, confidence_scale
from crew.lib.git import GitError, output
from crew.lib.output import bounded_json


def require_kind(finding: Finding) -> None:
    """Reject a finding with no `kind`, naming every value the vocabulary allows.

    Required at persist, because `kind` is the one defect axis independent of severity. A recorded
    review is re-read through `--lenient`, which is where legacy data stays readable.
    """
    if finding.kind is ABSENT:
        raise ValueError(f"finding {finding.title!r} has no kind; state what sort of defect it is, one of: {', '.join(sorted(KINDS))}")


def require_confidence(finding: Finding) -> None:
    """Reject a finding with no `confidence`, naming every band and its anchor.

    Enforced at persist, like `require_kind`, and `--lenient` is how a review written before the
    field existed stays readable. The score is the reviewer's own belief, not a severity: it is
    never summed into a review-level number, because a value no outcome can be joined to cannot be
    checked.
    """
    if finding.confidence is ABSENT:
        raise ValueError(f"finding {finding.title!r} has no confidence; state how sure you are, one of: {confidence_scale()}")


def check_findings(findings: list[Finding]) -> None:
    """Per-finding rules that need no changed-file list."""
    for f in findings:
        require_kind(f)
        require_confidence(f)
        check_confidence_raise(f)
        check_probe_move(f)
        check_confidence_floor(f)
        evidence = None if f.evidence is ABSENT else f.evidence
        if f.label in {"blocking", "attention"} and not (f.verified is True and isinstance(evidence, str) and EVIDENCE_LOCATION.fullmatch(evidence)):
            raise ValueError(
                f"unverified {f.label} finding {f.title!r}: set verified=true with evidence as path:line (or path:line@headSHA), or downgrade to 'needs more info'"
            )
        if evidence is not None and not isinstance(evidence, str):
            # A type error is a caller bug, not an absent location: fail loudly rather than let the
            # file gate below skip a malformed value as though the finding had cited nothing.
            raise ValueError(f"finding {f.title!r}: evidence must be a string path:line, got {type(evidence).__name__}")
        if f.verified is True:
            # `verified: true` asserts a second read happened. Without its conclusion recorded, the
            # next reader has only a boolean and an anchor and cannot tell why the check passed.
            validation = None if f.validation is ABSENT else f.validation
            if not isinstance(validation, str) or not validation.strip():
                raise ValueError(f"finding {f.title!r} is verified but records no validation sentence; state what the verification read and concluded")
            require_excerpt(f)


def require_excerpt(finding: Finding) -> None:
    """A finding verified at a PR head carries the lines it verified, so the record proves itself.

    Scoped to the `path:line@sha` form, because that read cannot be repeated locally: re-checking four
    such findings cost five `gh api` reads and three file reads. A working-tree finding needs none.
    """
    evidence = None if finding.evidence is ABSENT else finding.evidence
    if not (isinstance(evidence, str) and "@" in evidence):
        return
    excerpt = None if finding.excerpt is ABSENT else finding.excerpt
    if finding.label in {"blocking", "attention"} and not (isinstance(excerpt, str) and excerpt.strip()):
        raise ValueError(
            f"{finding.label} finding {finding.title!r} is verified at {evidence} but records no "
            "excerpt; paste the 2-3 verified lines under `excerpt`, or the record cannot be re-read "
            "without the network"
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
        if files and evidence and f.extra.get("anchor") != "non-hunk":
            # Shape is not enough: evidence must point at something under review, or a
            # finding about an untouched file is reported as verified. A finding with no
            # evidence is allowed here — `blocking`/`attention` were already required to have
            # it above, and a nit may stay unanchored, so there is nothing to check.
            location = evidence.split("@", 1)[0].rsplit(":", 1)[0]
            if not any(is_path_prefix(name, location) for name in files):
                raise ValueError(f"finding {f.title!r} cites {location}, which is not in the reviewed file set")
    nits = [f for f in emitted if f.label == "nit"]
    severity = len(emitted) - len(nits)
    # Counted separately: a nit must never consume a severity slot, so the two budgets do not
    # trade against each other.
    if severity > MAX_FINDINGS:
        raise ValueError(
            f"{severity} emitted non-nit findings exceed the cap of {MAX_FINDINGS}; drop the lowest severity or route pre-existing findings to 'defer'"
        )
    if len(nits) > MAX_NITS:
        raise ValueError(
            f"{len(nits)} emitted nits exceed the cap of {MAX_NITS}; keep the ones with a stated cost and drop the rest, so polish cannot occupy a severity slot"
        )


NON_HUNK = "non-hunk"


def strip_markers(findings: list[Finding]) -> None:
    """Drop any incoming `anchor`: only `mark_outside` may set it, so a hand-set marker skips no rule."""
    for finding in findings:
        finding.extra.pop("anchor", None)


def evidence_path(finding: Finding) -> str:
    evidence = finding.text("evidence")
    return evidence.split("@", 1)[0].rsplit(":", 1)[0] if evidence else ""


def tracked_at(repo: Path, head: str) -> set[str]:
    try:
        return set(output(repo, ["ls-tree", "-r", "--name-only", head or "HEAD"]).splitlines())
    except GitError as error:
        raise ValueError(
            f"cannot list tracked files at {head or 'HEAD'} ({error}); a PR head is not in the local checkout, so in PR mode leave out --repo and --head and anchor every finding in the diff"
        ) from error


def mark_outside(findings: list[Finding], files: list[str], repo: Path, head: str) -> list[str]:
    """Mark each emitted finding anchored outside `files`; return their paths."""
    outside = [(f, evidence_path(f)) for f in findings if f.is_emitted()]
    outside = [(f, path) for f, path in outside if path and not any(is_path_prefix(n, path) for n in files)]
    if not outside:
        return []
    tracked = tracked_at(repo, head)
    for finding, path in outside:
        if path not in tracked:
            raise ValueError(f"finding {finding.title!r} cites {path}, which is not in the reviewed file set and not a tracked file at {head or 'HEAD'}")
        if finding.label == "blocking" and finding.extra.get("line_read") is not True:
            raise ValueError(
                f"blocking finding {finding.title!r} anchors outside the diff at {path}; set line_read=true only after reading the cited line at the reviewed head, or lower the label"
            )
        finding.extra["anchor"] = NON_HUNK
    return sorted({path for _, path in outside})


def read_findings(path: Path) -> list[Finding]:
    """Every finding in a JSON list, or in an object carrying a `findings` list."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        raise ValueError("finding input must be a JSON list or an object with a findings list")
    return [to_finding(finding, index) for index, finding in enumerate(data, 1)]


def strict_mode(args: argparse.Namespace) -> bool:
    """True unless `--lenient` was passed: the gates are the default, the flag is the escape.

    `--strict` is still accepted as a no-op alias for one cycle, because an existing script or
    prompt that passes it must not fail for having followed the old documentation.
    """
    return not args.lenient


def normalize(args: argparse.Namespace) -> int:
    """Deduplicate exact fingerprints and, unless `--lenient`, apply the per-finding gates."""
    from crew.core.review.review_layers import check_hunk_refs, hunk_ids

    findings = read_findings(args.input)
    strip_markers(findings)
    strict = strict_mode(args)
    if strict and args.repo and args.files:
        mark_outside(findings, args.files, args.repo, args.head)
    if strict and args.hunks:
        # Validate every candidate before deduplication: otherwise a duplicate's malformed
        # attribution is silently discarded, or its valid hunk never reaches the coverage report.
        check_hunk_refs(findings, hunk_ids(args.hunks))
    kept, duplicates = {}, []
    for finding in findings:
        existing = kept.get(finding.fingerprint)
        if existing:
            existing.merge(finding)
            duplicates.append({"fingerprint": finding.fingerprint, "duplicate_of": existing.title, "title": finding.title})
        else:
            kept[finding.fingerprint] = finding
    if strict:
        check_strict(list(kept.values()), args.files)
    payload = {"findings": [finding.to_json() for finding in kept.values()], "duplicates": duplicates}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        # `--max-chars` bounds the printed copy only; a written file must stay complete.
        print(bounded_json(payload, args.max_chars, what="findings"), end="\n")
    return 0
