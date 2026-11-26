#!/usr/bin/env python3
"""Building the packages, and writing them.

A package is deterministic text built from files the run already produced, in one fixed order:
the shared header, the whole diff, then the per-persona material (size gate, spec, reading map,
guidance, prior-round block, consumers, prompt tier). Every package is built before any is written,
because a refusal on persona four must not leave personas one to three written beside four stale
ones from an earlier run — a package set nobody can tell apart from a complete one.

The order is the cost model. Every persona receives the identical header and the identical diff, so
putting both first makes the longest prefix common to all five packages as long as the content they
share; anything per-persona before the diff splits the packages early and the shared bytes are paid
for once per persona. Nothing is filtered to buy that: each package carries every hunk of
`package.diff`, which is the property the order must not disturb.
"""
from __future__ import annotations

import sys
from pathlib import Path

from assemble_common import common, guidance_block
from assemble_config import read_json
from assemble_files import excerpt, full_file
from assemble_map import CONSUMER_LENSES, reading_map
from assemble_personas import PERSONAS
from assemble_prior import section as prior_section

DIFF_HEADING = "\n---\n\n# Diff (package.diff — every non-generated hunk)\n\n```diff\n"
_TASK_TOOLS = Path(__file__).resolve().parents[1] / "task"
if str(_TASK_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TASK_TOOLS))

from task_report_check import capped  # noqa: E402


def unverified_block(report: str | None) -> str:
    """The builder's unverified claims from REPORT.md (config key `report`); empty without them.

    A report from before the section existed, or an unreadable one, adds nothing: the package is
    the same as it was.
    """
    try:
        text = Path(report).read_text(encoding="utf-8") if report else ""
    except OSError:
        return ""
    lines = capped(text, 20)
    return "\n".join(lines) + "\n" if lines else ""


def tail(persona: str, review_dir: Path, config: dict) -> tuple[list[str], dict]:
    """The per-persona material that follows the diff: everything a lens reads alone."""
    parts: list[str] = []
    report: dict = {"whole": [], "guidance": {}}
    if config.get("size_gate"):
        parts += ["\n---\n\n# Size gate\n\n", config["size_gate"].rstrip() + "\n"]
    claims = unverified_block(config.get("report"))
    if claims:
        parts += ["\n---\n\n## Builder's unverified claims (from REPORT.md)\n\n", claims]
    spec_path = review_dir / f"spec.{persona}.md"
    if spec_path.is_file():
        parts += ["\n---\n\n## Spec\n\n", spec_path.read_text(encoding="utf-8"), "\n"]
    layers_path = review_dir / "layers.json"
    if layers_path.is_file():
        layers = read_json(layers_path, "the layer map").get("layers") or []
        parts += ["\n---\n\n", reading_map(persona, layers), "\n"]
    guidance, guidance_report = guidance_block(review_dir, persona, config)
    if guidance:
        parts += ["\n---\n\n# Repository guidance\n\n", guidance]
    report["guidance"] = guidance_report
    prior = config.get("prior_review_dir")
    if prior:
        block = prior_section(Path(prior))
        if block:
            parts += ["\n---\n\n", block]
    return parts, report


def extras(persona: str, config: dict, diff: str,
           hunks_json: dict | None, report: dict) -> list[str]:
    """The consumer excerpts and prompt tier, which read the repository rather than the run."""
    parts: list[str] = []
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
        for path in prompt_files:
            block, elided = full_file(repo, path, diff, hunks_json)
            parts.append(block)
            if not elided:
                report["whole"].append(path)
    return parts


def build(persona: str, review_dir: Path, config: dict, shared: str,
          hunks_json: dict | None, sliced: dict | None = None) -> tuple[str, dict]:
    """One persona's package, plus a report of what was narrowed and what elided.

    `sliced` (`assemble_slice.plan` entry plus its `text`) narrows the diff shown to this lens only.

    The diff is read once and passed on: the prompt tier needs the same bytes to decide which lines
    the package already quotes, and a second read is a second chance to read a different file.
    """
    diff = (review_dir / "package.diff").read_text(encoding="utf-8")
    shown = diff if sliced is None else sliced["text"]
    heading = DIFF_HEADING if sliced is None else DIFF_HEADING.replace(
        "every non-generated hunk", f"sliced to {sliced['files']} of {sliced['of']} files for this lens; "
        "the rest are with the lenses that read the whole diff")
    parts = [shared, heading, shown, "\n```\n"]
    tail_parts, report = tail(persona, review_dir, config)
    parts += tail_parts
    parts += extras(persona, config, diff, hunks_json, report)
    return "".join(parts), report


def assemble_all(review_dir: Path, config: dict, hunks_json: dict | None) -> list[tuple]:
    """Every package, built before any is written.

    The head is built once and passed in. It is documented as identical for every persona, and a
    value computed inside the loop would only be identical because the files it reads happened not
    to change between iterations — the prefix this change exists to create deserves the stronger
    guarantee.
    """
    head = common(review_dir, config)
    assembled = []
    for persona in PERSONAS:
        content, report = build(persona, review_dir, config, head, hunks_json)
        assembled.append((persona, content, report))
    return assembled


def write_packages(review_dir: Path, assembled: list[tuple]) -> None:
    """Write each package and print its size plus whatever the run narrowed or sent whole."""
    for persona, content, report in assembled:
        (review_dir / f"{persona}.in.md").write_text(content, encoding="utf-8")
        guidance_report = report["guidance"]
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
