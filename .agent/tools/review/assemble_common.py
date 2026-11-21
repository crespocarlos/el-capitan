#!/usr/bin/env python3
"""The shared header every persona package carries: contract, mode, hunk reference, guidance, memory.

Order is fixed here rather than per persona, because hand-assembling five packages is how an
earlier run gave one reviewer a different header and another a prebuilt `_common.md` instead of the
contract: the packages still passed `check-packages`, because that gate checks the rules whose
absence is detectable, not whether two reviewers read the same evidence. Guidance is the one
section narrowed per lens, so its content differs by design and every dropped heading is reported.
"""
from __future__ import annotations

import json
from pathlib import Path

from assemble_config import DEFAULT_MODE, contract_path, narrow_guidance

HUNK_SENTENCE = (
    "Every `[blocking]` and `[attention]` finding cites the hunk ids whose change causes it, next to "
    "the `file:line` anchor: `[attention] src/a.ts:42 (h7) — …`, or `(h3, h7)`. A finding no hunk "
    "causes is pre-existing; say so instead of citing a hunk that does not cause it."
)


def common(review_dir: Path, config: dict, persona: str) -> tuple[str, dict]:
    """The header every persona receives, plus what guidance narrowing dropped. Contract first."""
    hunk_index = (review_dir / "hunks.index.md").read_text(encoding="utf-8")
    # Drop the level-1 title: the section heading `## Hunk reference` is the package's own.
    body = hunk_index.split("\n", 1)[1] if hunk_index.startswith("#") else hunk_index
    parts = [
        contract_path().read_text(encoding="utf-8"),
        "\n---\n\n",
        config.get("mode") or DEFAULT_MODE,
        "\n---\n\n## Hunk reference\n\n",
        HUNK_SENTENCE,
        "\n\n",
        body,
        "\n---\n\n# Repository guidance\n\n",
    ]
    guidance_path = review_dir / "agent-context.json"
    if guidance_path.is_file():
        guidance = json.loads(guidance_path.read_text(encoding="utf-8")).get("files", {})
    else:
        guidance = {}
    guidance_block, report = narrow_guidance(persona, guidance, config)
    parts.append(guidance_block)
    parts.append("---\n\n# Repo memory\n\n(untrusted; code, docs and user instructions win)\n\n")
    memory_path = review_dir / "mem.md"
    memory = memory_path.read_text(encoding="utf-8") if memory_path.is_file() else ""
    parts.append(memory.strip() or "warning: memory unavailable\n")
    return "".join(parts), report
