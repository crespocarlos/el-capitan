#!/usr/bin/env python3
"""Slicing the diff for the two lenses that read part of a change, with a closure rule and a gate.

Only `product-flow` and `code-quality` may be sliced; `adversarial` and `architecture` need the whole
diff, and `prompt-quality` has its own tier, so they always receive every hunk. Slicing is opt-in
(`"slice": true` in `assemble.json`) and needs the layer map: a lens's slice is the files of the hunks
in its primary layer kinds (`assemble_map.PRIMARY_KINDS`).

Closure rule: a changed symbol's referencing files travel with it. A file joins a slice when it
mentions a symbol or module name that a slice file defines (a caller) or when a slice file mentions one
it defines (a callee), repeated to a fixpoint; names under four characters are ignored as noise.

Coverage gate: every hunk of the index must appear in at least one package, together with the files
that reference it. When the gate cannot prove it, or nothing would be saved, no slice is made and the
persona gets the whole diff; slicing may cost a lens context but never lose a hunk.
"""
from __future__ import annotations

import re
from pathlib import Path

from assemble_map import PRIMARY_KINDS

SLICED = ("product-flow", "code-quality")
DEFINES = re.compile(r"\b(?:def|class|function|const|let|var|interface|type|enum|fn|func|struct|trait)\s+([A-Za-z_]\w{3,})")
MIN_NAME = 4


def split_diff(diff: str) -> dict[str, str]:
    """`{path: that file's diff text}` in diff order."""
    from assemble_applicability import changed_paths

    blocks = re.split(r"(?m)^(?=diff --git )", diff)
    blocks = [b for b in blocks if b.startswith("diff --git ")]
    return dict(zip(changed_paths(diff), blocks))


def names_defined(path: str, text: str) -> set[str]:
    """Symbols a file's changed lines define, plus its module stem."""
    changed = "\n".join(line[1:] for line in text.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---"))
    found = set(DEFINES.findall(changed))
    stem = Path(path).stem
    if len(stem) >= MIN_NAME:
        found.add(stem)
    return found


def mentions(text: str, names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in names)


def closure(seed: set[str], files: dict[str, str]) -> set[str]:
    """`seed` plus every file linked to it by a changed name, to a fixpoint."""
    chosen = set(seed)
    defined = {path: names_defined(path, text) for path, text in files.items()}
    grown = True
    while grown:
        grown = False
        for path, text in files.items():
            if path in chosen:
                continue
            callers = any(mentions(text, defined[s]) for s in chosen)
            callees = mentions("\n".join(files[s] for s in chosen), defined[path])
            if callers or callees:
                chosen.add(path)
                grown = True
    return chosen


def seed_files(persona: str, layers: list[dict], hunk_file: dict[str, str]) -> set[str]:
    kinds = PRIMARY_KINDS[persona]
    return {hunk_file[h] for layer in layers if layer.get("kind") in kinds
            for h in layer.get("hunks") or [] if h in hunk_file}


def plan(layers: list[dict], hunks_json: dict | None, diff: str, packaged: list[str]) -> tuple[dict[str, dict], str]:
    """`({persona: {files, of, closure, paths}}, note)`; empty plan with a note when nothing is sliced."""
    files = split_diff(diff)
    hunks = (hunks_json or {}).get("hunks") or []
    if not layers or not hunks or not files:
        return {}, "slicing needs a layer map and a hunk index; every lens gets the whole diff"
    hunk_file = {h["id"]: h["file"] for h in hunks if isinstance(h, dict) and "id" in h and "file" in h}
    sliced: dict[str, dict] = {}
    for persona in SLICED:
        if persona not in packaged:
            continue
        seed = seed_files(persona, layers, hunk_file) & set(files)
        chosen = closure(seed, files) if seed else set()
        if not chosen or chosen >= set(files):
            continue
        sliced[persona] = {"files": len(chosen), "of": len(files), "closure": sorted(chosen - seed),
                           "paths": [p for p in files if p in chosen]}
    full = [p for p in packaged if p not in sliced]
    covered = set(hunk_file) if full else {h for n in sliced.values() for h, f in hunk_file.items() if f in n["paths"]}
    if covered != set(hunk_file):
        return {}, "coverage gate: a hunk would reach no persona; every lens gets the whole diff"
    return sliced, ""


def slice_text(diff: str, paths: list[str]) -> str:
    """The diff restricted to `paths`, in diff order."""
    files = split_diff(diff)
    return "".join(files[p] for p in files if p in set(paths))
