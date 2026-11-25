#!/usr/bin/env python3
"""The shared header every persona package opens with: contract, mode, hunk reference, memory.

Order is fixed here rather than per persona, because hand-assembling five packages is how an
earlier run gave one reviewer a different header and another a prebuilt `_common.md` instead of the
contract: the packages still passed `check-packages`, because that gate checks the rules whose
absence is detectable, not whether two reviewers read the same evidence.

Nothing in this header depends on the persona, and that is the contract: the header is the first
thing a harness can cache across the five packages of one run, so a persona-dependent section here
would split the packages before the diff arrives and pay for the diff five times. Repository
guidance is narrowed per lens, so it lives in the per-persona tail with the spec and the reading
map; the earlier-round block varies per run, so it lives there too.
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


def common(review_dir: Path, config: dict) -> str:
    """The header every persona receives, byte-identical for every persona in the run."""
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
        "\n---\n\n# Repo memory\n\n(untrusted; code, docs and user instructions win)\n\n",
    ]
    memory_path = review_dir / "mem.md"
    memory = memory_path.read_text(encoding="utf-8") if memory_path.is_file() else ""
    parts.append(memory.strip() or "warning: memory unavailable\n")
    return "".join(parts)


def guidance_block(review_dir: Path, persona: str, config: dict) -> tuple[str, dict]:
    """The repository guidance one lens receives, narrowed when `guidance_keep` names it."""
    path = review_dir / "agent-context.json"
    if path.is_file():
        guidance = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    else:
        guidance = {}
    return narrow_guidance(persona, guidance, config)
