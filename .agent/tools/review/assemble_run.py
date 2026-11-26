#!/usr/bin/env python3
"""One assembly run: decide the personas, plan any slices, build, write, and report sizes.

`assemble_build.assemble_all` still builds every persona (kept for callers and tests). This is the
entry point's path: it records which personas it skipped and why, optionally slices the two lenses
that may be sliced (`assemble_slice`), prints a per-persona size report, and merges the decisions
into `manifest.json` (`assemble_applicability.record`). Every package is built before any is written.
"""
from __future__ import annotations

from pathlib import Path

from assemble_applicability import decide, record, size_report
from assemble_build import build, write_packages
from assemble_common import common
from assemble_config import read_json
from assemble_personas import PERSONAS
from assemble_slice import plan, slice_text


def layers_of(review_dir: Path) -> list[dict]:
    path = review_dir / "layers.json"
    return (read_json(path, "the layer map").get("layers") or []) if path.is_file() else []


def assemble_run(review_dir: Path, config: dict, hunks_json: dict | None) -> tuple[list[tuple], dict, dict, str]:
    """`(assembled, skipped, sliced, note)`; nothing is written."""
    diff = (review_dir / "package.diff").read_text(encoding="utf-8")
    packaged, skipped = decide(PERSONAS, diff, config)
    sliced, note = ({}, "")
    if config.get("slice") is True:
        sliced, note = plan(layers_of(review_dir), hunks_json, diff, packaged)
    head = common(review_dir, config)
    assembled = []
    for persona in packaged:
        cut = None
        if persona in sliced:
            cut = {**sliced[persona], "text": slice_text(diff, sliced[persona]["paths"])}
        content, report = build(persona, review_dir, config, head, hunks_json, cut)
        assembled.append((persona, content, report))
    return assembled, skipped, sliced, note


def write_run(review_dir: Path, assembled: list[tuple], skipped: dict, sliced: dict, note: str) -> None:
    write_packages(review_dir, assembled)
    sizes = {persona: len(content) for persona, content, _ in assembled}
    for line in size_report(sizes, max(sizes.values(), default=0), skipped, sliced):
        print(line)
    if note:
        print(f"slice: {note}")
    record(review_dir, sizes, skipped, sliced)
