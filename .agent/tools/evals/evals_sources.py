#!/usr/bin/env python3
"""Suite source discovery and changed-path classification for `diagnose`.

`diagnose` has to name which surface a score change came from, and that means reading the suite
source it was measured against: the evaluator files, the dataset, the instructions, the tools, and
the retrieval helpers. This module finds the suite and buckets the changed paths. It reads the
checkout, and refuses loudly when the suite is missing rather than guessing at a cause.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

KIND_ORDER = ("prompt", "tool", "retrieval", "evaluator", "dataset", "other")
# Tokens that place a path in a surface, checked in order; the first match wins.
PATH_TOKENS = (
    ("prompt", (".md.text", "/instructions", "/prompt", "/skills/")),
    ("tool", ("/tools/",)),
    ("retrieval", ("/retrieval/", "indicator_", "search_embedding")),
)


def git(repo: Path, *args: str) -> str:
    """A read-only git call in `repo`; any failure names the repository, not the caller's bug."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        message = (error.stderr.strip() if isinstance(error, subprocess.CalledProcessError)
                   else str(error))
        raise SystemExit(f"repository unavailable: {message}")


def locate_suite(repo: Path, suite_id: str) -> Path:
    expected = f"@kbn/evals-suite-{suite_id}"
    for manifest in repo.rglob("kibana.jsonc"):
        try:
            identifier = re.search(r'''["']id["']\s*:\s*["']([^"']+)["']''',
                                   manifest.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if identifier and identifier.group(1) == expected:
            return manifest.parent
    raise SystemExit(f"suite source unavailable: {expected} was not found below {repo}")


def evaluator_sources(suite: Path) -> dict[str, str]:
    """Every evaluator name the suite declares, mapped to the file that declares it."""
    sources = {}
    for path in (suite / "src" / "evaluators").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        try:
            for name in re.findall(r"""name\s*:\s*['"]([^'"]+)['"]""",
                                   path.read_text(encoding="utf-8", errors="replace")):
                sources[name] = str(path)
        except OSError:
            continue
    return sources


def classify_paths(paths: list[str], suite: Path, evaluator_paths: set[str]) -> dict[str, list[str]]:
    """Bucket each changed path by the surface it belongs to, so a delta has a candidate cause."""
    result = {kind: [] for kind in KIND_ORDER}
    suite_text = str(suite)
    for path in paths:
        lower = path.lower()
        absolute = str((suite.parent.parent.parent.parent / path).resolve())
        if path in evaluator_paths or lower.startswith("src/evaluators/") \
                or "/src/evaluators/" in lower:
            kind = "evaluator"
        elif lower.startswith("src/datasets/") or "/src/datasets/" in lower:
            kind = "dataset"
        else:
            kind = next((name for name, tokens in PATH_TOKENS
                         if any(token in lower for token in tokens)),
                        "other" if absolute.startswith(suite_text) else "other")
        result[kind].append(path)
    return result
