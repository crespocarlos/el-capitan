"""The layer map: its validation (hunk ids, one hunk in exactly one layer) and the reports over it.

A hunk nobody was asked to read is a coverage hole no persona output reveals, so a missing or
duplicated id is an error. The same check serves `validate-map` and the persist gate; this module
also checks that findings cite hunks and reports what each layer yielded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from review_models import Finding
from review_render import label_with_score
from review_vocabulary import ABSENT

from lib.files import read_json_object
from lib.output import bounded_json

MAX_LAYERS = 8


def hunk_ids(path: Path) -> list[str]:
    """Every hunk id in an index, refusing a missing or duplicated one."""
    entries = read_json_object(path, "hunks")["hunks"]
    if not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"{path}: every hunk must be an object")
    known = [entry.get("id") for entry in entries]
    if not all(isinstance(hunk_id, str) and hunk_id for hunk_id in known):
        raise ValueError(f"{path}: every hunk needs a string id")
    duplicated = sorted({hunk_id for hunk_id in known if known.count(hunk_id) > 1})
    if duplicated:
        raise ValueError(f"{path}: duplicate hunk ids: {', '.join(duplicated)}")
    return known


def layer_header_errors(layer: object, where: str, layer_ids: set[str]) -> list[str]:
    """The errors in one layer's identity: its id, explainer, and review focus."""
    errors: list[str] = []
    if not isinstance(layer, dict):
        return [f"{where} is not an object"]
    layer_id = layer.get("id")
    if not isinstance(layer_id, str) or not layer_id.strip():
        errors.append(f"{where}.id is missing")
    elif layer_id in layer_ids:
        errors.append(f"{where}.id {layer_id!r} is duplicated")
    else:
        layer_ids.add(layer_id)
    if not isinstance(layer.get("explainer"), str) or not layer["explainer"].strip():
        errors.append(f"{where}.explainer is missing")
    if not isinstance(layer.get("reviewFocus"), str) or not layer["reviewFocus"].strip():
        errors.append(f"{where}.reviewFocus is missing")
    return errors


def layer_hunk_errors(layer: dict, where: str, known_set: set[str],
                      seen: dict[str, str]) -> list[str]:
    """The errors in one layer's hunk assignment and its notes, recording each id in `seen`."""
    errors: list[str] = []
    assigned = layer.get("hunks")
    if not isinstance(assigned, list) or not assigned:
        return [f"{where}.hunks must be a non-empty list of hunk ids"]
    for hunk_id in assigned:
        if not isinstance(hunk_id, str):
            errors.append(f"{where}.hunks has a non-string id {hunk_id!r}")
        elif hunk_id not in known_set:
            errors.append(f"{where} references unknown hunk {hunk_id!r}")
        elif hunk_id in seen:
            errors.append(
                f"hunk {hunk_id} is in both {seen[hunk_id]} and {where}; "
                "each hunk belongs to exactly one layer"
            )
        else:
            seen[hunk_id] = where
    notes = layer.get("hunkNotes", {})
    if not isinstance(notes, dict):
        errors.append(f"{where}.hunkNotes must be an object keyed by hunk id")
        return errors
    for note_id in notes:
        if note_id not in assigned:
            errors.append(f"{where}.hunkNotes has a note for {note_id}, which is not in its hunks")
    return errors


def layer_errors(
    known: list[str], layers: object
) -> tuple[list[str], dict[str, str]]:
    """Per-layer errors and the hunk-id → layer assignment this map produced."""
    if not isinstance(layers, list) or not layers:
        return ["layers must be a non-empty array of layer objects"], {}
    errors: list[str] = []
    known_set, seen, layer_ids = set(known), {}, set()
    for index, layer in enumerate(layers, 1):
        where = f"layers[{index}]"
        errors.extend(layer_header_errors(layer, where, layer_ids))
        if isinstance(layer, dict):
            errors.extend(layer_hunk_errors(layer, where, known_set, seen))
    return errors, seen


def check_layers(known: list[str], layers: object) -> tuple[list[str], list[str]]:
    """Every hunk id lands in exactly one layer, and no layer invents an id."""
    errors, seen = layer_errors(known, layers)
    if errors and not isinstance(layers, list):
        return errors, []
    missing = [hunk_id for hunk_id in known if hunk_id not in seen]
    if missing:
        errors.append(f"{len(missing)} hunk(s) in no layer: {', '.join(missing)}")
    if isinstance(layers, list) and len(layers) > MAX_LAYERS:
        errors.append(f"{len(layers)} layers exceeds the maximum of {MAX_LAYERS}")
    return errors, []


def check_coverage(hunks_path: Path, layers_path: Path) -> dict:
    """Every hunk id lands in exactly one layer, and no layer invents an id.

    Shared with `validate-map`, so a map that validates for `crew explain` cannot then be
    rejected by the persist gate.
    """
    known = hunk_ids(hunks_path)
    layers = read_json_object(layers_path, "layers")["layers"]
    errors, _ = check_layers(known, layers)
    if errors:
        raise ValueError("; ".join(errors))
    return {"hunks": len(known), "layers": len(layers)}


def parse_map_block(reply: str) -> dict:
    """The one fenced `json` block in a `reviewer-layers` reply, parsed; anything else raises.

    Coverage is a hunk check, so a map with a stray comma inside its fence failed as
    "not valid JSON" only after the whole review had been packaged, or not at all when the
    orchestrator hand-repaired the block before writing it. Parsing here makes the failure
    attributable to the one dispatch that produced it, at the step that receives the reply.
    """
    blocks = re.findall(r"```json\s*\n(.*?)\n```", reply, re.DOTALL)
    if len(blocks) != 1:
        raise ValueError(
            f"the layers reply holds {len(blocks)} fenced json blocks; reply with exactly one"
        )
    try:
        payload = json.loads(blocks[0])
    except json.JSONDecodeError as error:
        raise ValueError(f"the layers reply is not valid JSON: {error}") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("layers"), list):
        raise ValueError("the layers reply must be a JSON object carrying a `layers` array")
    return payload


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
        if f.label in {"blocking", "attention"} and not refs and f.extra.get("anchor") != "non-hunk":
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
        result = "; ".join(f"{label_with_score(f)} {f.title}" for f in hits) or "no findings"
        lines.append(f"- {layer.get('title') or layer['id']} ({', '.join(layer['hunks'])}): {result}")
    unmapped = [f for f in emitted if not (f.hunks is not ABSENT and f.hunks)]
    if unmapped:
        lines.append("- outside the map: " + "; ".join(f"{label_with_score(f)} {f.title}"
                                                      for f in unmapped))
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
