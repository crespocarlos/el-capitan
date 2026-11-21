#!/usr/bin/env python3
"""The reading map: the per-persona layer order, derived from `layers.json`.

`kind` and `title` are optional on a layer, because the coverage gate that validates a map requires
neither, so a map without them must still produce a package rather than crash. The map is
orientation, never evidence: a claim still needs a verified `path:line` from the package.
"""
from __future__ import annotations

PRIMARY_KINDS = {
    "adversarial": {"core", "foundation", "wiring"},
    "architecture": {"foundation", "wiring"},
    "code-quality": {"core", "tests", "mechanical"},
    "product-flow": {"ui", "wiring", "docs"},
    "prompt-quality": {"prompts"},
}
# Lenses that reason about cross-file effects need the consumers of the changed contracts.
CONSUMER_LENSES = frozenset({"adversarial", "architecture", "product-flow"})


def reading_map(persona: str, layers: list[dict]) -> str:
    """The per-persona reading order, with the layers this lens should spend its budget on first."""
    kinds = PRIMARY_KINDS[persona]
    lines = [
        "## Reading map",
        "",
        "Hunks are ids (`h1`, `h2`, …) from the hunk index. Read layers in this order; earlier "
        "layers explain later ones.",
        "",
    ]
    primary = [str(index) for index, layer in enumerate(layers, 1)
               if layer.get("kind") in kinds]
    if primary:
        lines += ["Your primary layers: " + ", ".join(primary), ""]
    for index, layer in enumerate(layers, 1):
        kind = layer.get("kind") or "layer"
        title = layer.get("title") or layer.get("id") or f"layer {index}"
        lines.append(f"### {index}. {kind} — {title}")
        lines.append("Explain: " + (layer.get("explainer") or ""))
        lines.append("Focus: " + (layer.get("reviewFocus") or ""))
        lines.append("Hunks: " + ", ".join(layer.get("hunks") or []))
        for hunk, note in layer.get("hunkNotes", {}).items():
            lines.append(f"  - {hunk}: {note}")
        lines.append("")
    lines += [
        "The map is orientation, never evidence: a claim still needs a verified `path:line` from the "
        "package. Do not treat layer boundaries as review boundaries — a finding that spans two "
        "layers cites hunks from both.",
        "",
    ]
    return "\n".join(lines)
