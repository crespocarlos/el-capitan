#!/usr/bin/env python3
"""Layer-map concerns: hunk references, coverage reporting, and the map gate.

Split out of `crew-review-findings.py`. The layer map is what proves the personas were pointed at the
whole diff, so these checks are errors rather than warnings. Validation of the map itself is
`review_map`; this module covers the other side — whether the findings cite hunks, what each layer
yielded, and the two subcommands that report on a map.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.output import bounded_json
from review_map import (  # noqa: F401 — re-exported
    MAX_LAYERS,
    check_coverage,
    check_layers,
    hunk_ids,
    layer_errors,
    layer_header_errors,
    layer_hunk_errors,
)
from review_models import ABSENT, Finding, read_json_object

SEVERITIES = {"high", "medium", "low", "nit"}


def check_hunk_refs(findings: list[Finding], known: list[str]) -> None:
    """Emitted findings name the hunks whose change causes them, and only real ones.

    A blocking or attention finding that no hunk caused is about code the change did not
    touch, which consolidation routes to `defer`; a nit may stay unanchored.
    """
    known_set = set(known)
    for f in findings:
        if not f.is_emitted():
            continue
        refs = [] if f.hunks is ABSENT else f.hunks
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError(f"finding {f.title!r}: hunks must be a list of hunk ids")
        unknown = [ref for ref in refs if ref not in known_set]
        if unknown:
            raise ValueError(f"finding {f.title!r} cites unknown hunk(s): {', '.join(unknown)}")
        if f.label in {"blocking", "attention"} and not refs:
            raise ValueError(
                f"{f.label} finding {f.title!r} cites no hunk; name the hunk(s) whose change "
                "causes it, or route it to defer"
            )


def layer_coverage(layers: list[dict], findings: list[Finding]) -> str:
    """The per-layer table a persisted report appends, with any unmapped finding named."""
    emitted = [f for f in findings if f.is_emitted()]
    lines = ["### Coverage by layer"]
    for layer in layers:
        assigned = set(layer["hunks"])
        hits = [f for f in emitted if assigned & set([] if f.hunks is ABSENT else f.hunks)]
        result = "; ".join(f"[{f.label}] {f.title}" for f in hits) or "no findings"
        lines.append(f"- {layer.get('title') or layer['id']} ({', '.join(layer['hunks'])}): {result}")
    unmapped = [f for f in emitted if not (f.hunks is not ABSENT and f.hunks)]
    if unmapped:
        lines.append("- outside the map: " + "; ".join(f"[{f.label}] {f.title}" for f in unmapped))
    return "\n".join(lines) + "\n"


def coverage(args: argparse.Namespace) -> int:
    """Print the coverage summary, or fail on a hunk in no layer."""
    print(bounded_json(check_coverage(args.hunks, args.layers), args.max_chars, what="coverage"))
    return 0


def validate_map(args: argparse.Namespace) -> int:
    """Check a whole review map (summary, layers, concerns) against the hunk index.

    The contract `crew explain` writes and `crew review` reads, in one place, so a map
    that renders also passes the persist coverage gate.
    """
    review = read_json_object(args.review, "layers")
    known = hunk_ids(args.hunks)
    errors, warnings = check_layers(known, review["layers"])
    errors.extend(map_header_errors(review))
    errors.extend(concern_errors(review.get("concerns") or [], known))
    warnings.extend(reference_warnings(review.get("references") or []))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"review-findings: {error}", file=sys.stderr)
        return 1
    print(bounded_json({"ok": True, "hunks": len(known),
                        "layers": len(review["layers"]), "warnings": len(warnings)},
                       args.max_chars, what="map validation"))
    return 0


def map_header_errors(review: dict) -> list[str]:
    """The map-level fields the contract requires beyond its layers."""
    errors = []
    if not isinstance(review.get("summary"), str) or not review["summary"].strip():
        errors.append("summary must be a non-empty markdown string")
    if "context" in review and not isinstance(review["context"], str):
        errors.append("context must be a markdown string")
    if review.get("risk") is not None and review["risk"] not in ("low", "medium", "high"):
        errors.append("risk must be low, medium, or high")
    return errors


def concern_errors(concerns: list, known: list[str]) -> list[str]:
    """The per-concern fields, including a hunk id that must exist in the index."""
    errors = []
    for index, concern in enumerate(concerns, 1):
        where = f"concerns[{index}]"
        if not isinstance(concern, dict):
            errors.append(f"{where} is not an object")
            continue
        if not isinstance(concern.get("severity"), str) or concern["severity"] not in SEVERITIES:
            errors.append(f"{where}.severity must be one of {', '.join(sorted(SEVERITIES))}")
        for field in ("title", "detail"):
            if not isinstance(concern.get(field), str) or not concern[field].strip():
                errors.append(f"{where}.{field} is missing")
        if concern.get("hunk") is not None and (
                not isinstance(concern["hunk"], str) or concern["hunk"] not in known):
            errors.append(f"{where}.hunk {concern['hunk']!r} is not a hunk in the index")
    return errors


def reference_warnings(references: list) -> list[str]:
    """A reference with neither a url nor a path is a warning, not an error."""
    warnings = []
    for index, reference in enumerate(references, 1):
        where = f"references[{index}]"
        if not isinstance(reference, dict) or not isinstance(reference.get("title"), str):
            warnings.append(f"{where}.title is missing")
        elif not reference.get("url") and not reference.get("path"):
            warnings.append(f"{where} has neither url nor path")
    return warnings
