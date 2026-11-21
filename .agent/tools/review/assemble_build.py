#!/usr/bin/env python3
"""Building the packages, and writing them.

A package is deterministic text built from files the run already produced, in one fixed order:
shared header, size gate, spec, reading map, diff, then the extras a lens needs. Every package is
built before any is written, because a refusal on persona four must not leave personas one to
three written beside four stale ones from an earlier run — a package set nobody can tell apart from
a complete one.
"""
from __future__ import annotations

from pathlib import Path

from assemble_common import common
from assemble_config import read_json
from assemble_files import excerpt, full_file
from assemble_map import CONSUMER_LENSES, reading_map
from assemble_personas import PERSONAS


def build(persona: str, review_dir: Path, config: dict, shared: str,
          hunks_json: dict | None) -> tuple[str, dict]:
    """One persona's package, plus a report of what was narrowed and what elided."""
    report: dict = {"whole": []}
    parts = [shared]
    if config.get("size_gate"):
        parts += ["\n---\n\n# Size gate\n\n", config["size_gate"].rstrip() + "\n"]
    spec_path = review_dir / f"spec.{persona}.md"
    if spec_path.is_file():
        parts += ["\n---\n\n## Spec\n\n", spec_path.read_text(encoding="utf-8"), "\n"]
    layers_path = review_dir / "layers.json"
    if layers_path.is_file():
        layers = read_json(layers_path, "the layer map").get("layers") or []
        parts += ["\n---\n\n", reading_map(persona, layers), "\n"]
    parts += [
        "\n---\n\n# Diff (package.diff — every non-generated hunk)\n\n```diff\n",
        (review_dir / "package.diff").read_text(encoding="utf-8"),
        "\n```\n",
    ]
    repo = Path(config.get("repo") or ".").resolve()
    consumers = config.get("consumers") or []
    if persona in CONSUMER_LENSES and consumers:
        parts += ["\n---\n\n# Consumers of the changed contracts (unchanged files)\n\n"]
        for path, start, end, label in consumers:
            parts.append(excerpt(repo, path, start, end, label))
    prompt_files = config.get("prompt_files") or []
    if persona == "prompt-quality" and prompt_files:
        parts += [
            "\n---\n\n# Prompt tier: complete changed prompt and contract files\n\n",
            "The diff above shows what changed; these are the same files with the changed lines "
            "elided and every unchanged line kept, because a rule collides with the text around it "
            "rather than with itself. Line numbers prefix every kept line, so an anchor resolves "
            "against the file; an elided range is marked with the lines it stands for.\n\n",
        ]
        diff = (review_dir / "package.diff").read_text(encoding="utf-8")
        for path in prompt_files:
            block, elided = full_file(repo, path, diff, hunks_json)
            parts.append(block)
            if not elided:
                report["whole"].append(path)
    return "".join(parts), report


def assemble_all(review_dir: Path, config: dict, hunks_json: dict | None) -> list[tuple]:
    """Every package, built before any is written."""
    assembled = []
    for persona in PERSONAS:
        shared, guidance_report = common(review_dir, config, persona)
        content, report = build(persona, review_dir, config, shared, hunks_json)
        assembled.append((persona, content, report, guidance_report))
    return assembled


def write_packages(review_dir: Path, assembled: list[tuple]) -> None:
    """Write each package and print its size plus whatever the run narrowed or sent whole."""
    for persona, content, report, guidance_report in assembled:
        (review_dir / f"{persona}.in.md").write_text(content, encoding="utf-8")
        narrowed = sum(len(v) for v in guidance_report["dropped"].values())
        notes = []
        if narrowed:
            # Printed, never silent: a lens given the wrong sections loses a rule silently.
            notes.append(f"guidance narrowed, {narrowed} section(s) dropped: "
                         + "; ".join(f"{p.split('/')[-1]}: {', '.join(v)}"
                                     for p, v in guidance_report["dropped"].items() if v))
        if report["whole"]:
            notes.append("prompt files sent whole (elision unsafe): "
                         + ", ".join(p.split("/")[-1] for p in report["whole"]))
        print(f"{persona:<15} {len(content):>7} bytes"
              + (f"  [{' | '.join(notes)}]" if notes else ""))
