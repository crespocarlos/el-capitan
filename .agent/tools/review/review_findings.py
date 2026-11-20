#!/usr/bin/env python3
"""Finding model: vocabulary, parsing, validation, fingerprints, and normalization.

Split out of `review-findings.py` so the CLI stays an argparse entry point. This module owns
what a finding is and what one finding must satisfy; the persona, layer, and report concerns
live in their own modules and import from here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from lib.files import atomic_write  # noqa: F401  re-exported by review-findings.py

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


def fingerprint(finding: dict) -> str:
    material = "|".join(
        [
            str(finding.get("file", "")).strip(),
            str(finding.get("label", "")).strip().lower(),
            normalized_title(str(finding["title"])),
        ]
    )
    return hashlib.sha1(material.encode()).hexdigest()


def read_findings(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        raise ValueError("finding input must be a JSON list or an object with a findings list")
    result = []
    for index, finding in enumerate(data, 1):
        if not isinstance(finding, dict) or not isinstance(finding.get("title"), str):
            raise ValueError(f"finding {index} requires a string title")
        label = str(finding.get("label", "")).lower()
        if label not in LABELS:
            raise ValueError(f"finding {index} has invalid label: {label!r}")
        disposition = finding.get("disposition")
        if disposition is not None and disposition not in DISPOSITIONS:
            raise ValueError(f"finding {index} has invalid disposition: {disposition!r}")
        normalized = {**finding, "label": label}
        # Optional: every review recorded before this field existed has no `kind`, and refusing those
        # would make the tool unable to re-read its own history. A typo is a different matter — an
        # unknown value is rejected so the vocabulary cannot drift one spelling at a time.
        if "kind" in finding:
            kind = str(finding["kind"]).strip().lower()
            if kind not in KINDS:
                raise ValueError(
                    f"finding {index} has invalid kind: {finding['kind']!r} "
                    f"(expected one of {', '.join(sorted(KINDS))})"
                )
            normalized["kind"] = kind
        if "persona" in finding or "personas" in finding:
            normalized.pop("personas", None)
            normalized["persona"] = canonical_personas(finding.get("persona", finding.get("personas")))
        result.append({**normalized, "fingerprint": fingerprint(normalized)})
    return result


def check_findings(findings: list[dict]) -> None:
    """Per-finding rules that need no changed-file list.

    Split out from `check_strict` because `persist` used to reach every per-finding rule only when
    `--files` carried at least one path, and a spec or idea review has no path list to pass. The
    result was a `verified: true` finding with no validation sentence persisting successfully in
    exactly the modes that pass no files, while both `TOOLS.md` and the consolidation protocol said
    the sentence was required.
    """
    for f in findings:
        evidence = f.get("evidence")
        if f["label"] in {"blocking", "attention"} and not (
            f.get("verified") is True
            and isinstance(evidence, str)
            and EVIDENCE_LOCATION.fullmatch(evidence)
        ):
            raise ValueError(
                f"unverified {f['label']} finding {f['title']!r}: set verified=true with evidence as path:line "
                "(or path:line@headSHA), "
                "or downgrade to 'needs more info'"
            )
        if evidence is not None and not isinstance(evidence, str):
            # A type error is a caller bug, not an absent location: fail loudly rather than let the
            # file gate below skip a malformed value as though the finding had cited nothing.
            raise ValueError(
                f"finding {f['title']!r}: evidence must be a string path:line, got {type(evidence).__name__}"
            )
        if f.get("verified") is True:
            # `verified: true` asserts a second read happened. Without its conclusion recorded, the
            # next reader has only a boolean and an anchor and cannot tell why the check passed —
            # which is the reasoning the consolidator used to discard.
            validation = f.get("validation")
            if not isinstance(validation, str) or not validation.strip():
                raise ValueError(
                    f"finding {f['title']!r} is verified but records no validation sentence; "
                    "state what the verification read and concluded"
                )


def check_strict(findings: list[dict], files: list[str] | None = None) -> None:
    emitted = [f for f in findings if f.get("disposition") in EMITTED]
    check_findings(emitted)
    for f in emitted:
        evidence = f.get("evidence")
        if files and evidence:
            # Shape is not enough: evidence must point at something under review, or a
            # finding about an untouched file is reported as verified. A finding with no
            # evidence is allowed here — `blocking`/`attention` were already required to have
            # it above, and a nit may stay unanchored, so there is nothing to check.
            location = evidence.split("@", 1)[0].rsplit(":", 1)[0]
            matches = [name for name in files
                       if name == location or name.endswith("/" + location) or location.endswith("/" + name)]
            if not matches:
                raise ValueError(
                    f"finding {f['title']!r} cites {location}, which is not in the reviewed file set"
                )
    nits = [f for f in emitted if f["label"] == "nit"]
    findings_only = len(emitted) - len(nits)
    # Counted separately: a nit must never consume a severity slot, so the two budgets do not
    # trade against each other.
    if findings_only > MAX_FINDINGS:
        raise ValueError(
            f"{findings_only} emitted non-nit findings exceed the cap of {MAX_FINDINGS}; "
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
        existing = kept.get(finding["fingerprint"])
        if existing:
            for persona in finding.get("persona", []):
                if persona not in existing.setdefault("persona", []):
                    existing["persona"].append(persona)
            if isinstance(existing.get("hunks", []), list) and isinstance(finding.get("hunks", []), list):
                existing["hunks"] = list(dict.fromkeys(existing.get("hunks", []) + finding.get("hunks", [])))
            duplicates.append(
                {"fingerprint": finding["fingerprint"], "duplicate_of": existing["title"], "title": finding["title"]}
            )
        else:
            kept[finding["fingerprint"]] = finding
    if args.strict:
        check_strict(list(kept.values()), args.files)
    payload = {"findings": list(kept.values()), "duplicates": duplicates}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0
