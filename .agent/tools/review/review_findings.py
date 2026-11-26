#!/usr/bin/env python3
"""Finding model: vocabulary, parsing, validation, fingerprints, and normalization.

Split out of `crew-review-findings.py` so the CLI stays an argparse entry point. The vocabulary is
`review_vocabulary`, the record and its gates are `review_models`, and the diff parse a hunk id comes
from is `review_parse`; this module is the one import site that re-exports them, so the persona,
layer, and report concerns keep importing from here without knowing which file a name landed in.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.files import atomic_write  # noqa: F401  re-exported by crew-review-findings.py
from lib.output import bounded_json
from review_gates import check_findings, check_strict, is_path_prefix  # noqa: F401 — re-exported
from review_models import (  # noqa: F401 — re-exported
    ABSENT,
    Finding,
    fingerprint,
    read_json_object,
    to_finding,
)
from review_vocabulary import (  # noqa: F401 — re-exported
    CODE_MODES,
    DISPOSITIONS,
    EMITTED,
    EVIDENCE_LOCATION,
    KINDS,
    LABELS,
    LEGACY_PERSONAS,
    MAX_FINDINGS,
    MAX_NITS,
    OUTCOMES,
    PERSONAS,
    PERSONA_STATUSES,
    SELECT_RULES,
    canonical_personas,
    mode_arg,
    normalized_title,
)


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
    from review_layers import check_hunk_refs, hunk_ids

    from review_anchors import mark_outside, strip_markers

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
            duplicates.append(
                {"fingerprint": finding.fingerprint, "duplicate_of": existing.title, "title": finding.title}
            )
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
