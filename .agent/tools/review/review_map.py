#!/usr/bin/env python3
"""Layer-map validation: hunk ids, per-layer errors, and one hunk in exactly one layer.

A hunk nobody was asked to read is a coverage hole that no amount of persona output reveals, so a
missing or duplicated id is an error rather than a warning. The same check serves `crew explain`'s
`validate-map` and the persist gate, so a map that renders cannot then be rejected by persist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from review_models import read_json_object

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
