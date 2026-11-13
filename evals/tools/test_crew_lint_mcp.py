#!/usr/bin/env python3
"""Hermetic checks for crew-lint.py's tool-reference resolution.

Builds a fixture root for each case so a finding can only come from the rule under test. The other
checks stay quiet because the fixture supplies a valid catalog and an empty rules directory.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "crew-lint.py"

SERVERS = {"semantic-code-search": ["map_symbols_by_query", "symbol_analysis"]}
NATIVE = ["Glob", "Grep", "Read"]


def make_root(base: Path, tools_line: str, extra: str = "") -> Path:
    root = base / "repo"
    (root / ".agent" / "tools").mkdir(parents=True)
    (root / ".cursor" / "agents").mkdir(parents=True)
    (root / "rules").mkdir()
    (root / ".agent" / "tools" / "tools.json").write_text(json.dumps({
        "schema_version": 1, "tools": [], "scripts": [], "assets": [],
        "mcp_servers": SERVERS, "native_tools": NATIVE,
    }))
    (root / ".cursor" / "agents" / "fixture-agent.md").write_text(
        "---\n"
        "name: fixture-agent\n"
        "description: \"Fixture agent for lint checks.\"\n"
        f"{tools_line}\n"
        "readonly: true\n"
        "maxTurns: 4\n"
        "---\n"
        f"Body text.\n{extra}"
    )
    return root


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--root", str(root)],
                          capture_output=True, text=True)


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"pass: {name}")


def findings(result: subprocess.CompletedProcess, rule: str) -> list[str]:
    return [line for line in result.stdout.splitlines() if f": {rule}: " in line]


def main() -> int:
    cases = [
        (
            "declared mcp reference and declared native id",
            "tools: Read, Grep, Glob, mcp__semantic-code-search__map_symbols_by_query",
            None, 0,
        ),
        (
            "undeclared mcp server",
            "tools: Read, mcp__elastic-docs__search_docs",
            "mcp-tool-unknown", 1,
        ),
        (
            "undeclared tool on a declared server",
            "tools: Read, mcp__semantic-code-search__bogus_tool",
            "mcp-tool-unknown", 1,
        ),
        (
            "undeclared native tool id",
            "tools: Read, Grep, SemanticSearch",
            "tool-id-unknown", 1,
        ),
    ]

    for label, tools_line, rule, expected in cases:
        with tempfile.TemporaryDirectory() as temporary:
            root = make_root(Path(temporary), tools_line)
            result = run(root)
            hits = findings(result, rule) if rule else [
                line for line in result.stdout.splitlines() if "tool-" in line
            ]
            check(f"{label}: finds {len(hits)} {rule or 'tool'} finding(s)", len(hits) == expected,
                  result.stdout + result.stderr)
            if rule:
                check(f"{label}: exit code 1", result.returncode == 1, str(result.returncode))
                check(f"{label}: names the file and line",
                      hits[0].startswith(".cursor/agents/fixture-agent.md:4:"), hits[0])
            else:
                check(f"{label}: exit code 0", result.returncode == 0,
                      result.stdout + result.stderr)

    # An MCP reference in prose is caught too, so a stale id cannot hide in a rule or doc.
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), "tools: Read")
        (root / "rules" / "fixture.mdc").write_text(
            "---\ndescription: \"Fixture rule\"\nalwaysApply: false\n---\n"
            "Use mcp__retired-server__old_tool for docs.\n"
        )
        result = run(root)
        hits = findings(result, "mcp-tool-unknown")
        check("catches an mcp id in prose", len(hits) == 1, result.stdout)
        check("prose finding names the rule file", hits[0].startswith("rules/fixture.mdc:5:"), hits[0])

    # A malformed allowlist is a catalog error, not a silent pass that disables the check.
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), "tools: Read")
        (root / ".agent" / "tools" / "tools.json").write_text(json.dumps({
            "schema_version": 1, "tools": [], "scripts": [], "assets": [],
            "mcp_servers": "semantic-code-search", "native_tools": NATIVE,
        }))
        result = run(root)
        hits = findings(result, "invalid-tool-catalog")
        check("malformed mcp_servers is reported", len(hits) == 1, result.stdout)
        check("malformed allowlist exits 1", result.returncode == 1, str(result.returncode))

    # A docs server declared but no persona granted its tools is the gap this repo hit: the
    # instruction keeps running while no persona can execute it. The lint cannot judge prose intent,
    # so the repo asserts the grant directly.
    text = (ROOT / ".cursor/agents/crew-reviewer.md").read_text()
    check("docs trigger still names a docs server capability", "docs\nMCP server" in text or
          "docs MCP server" in text, "crew-reviewer.md lost the docs instruction")
    verifying = ["reviewer-adversarial", "reviewer-architecture", "reviewer-code-quality",
                 "reviewer-product-flow", "reviewer-prompt-quality", "reviewer-explorer",
                 "specwriter-adversarial", "specwriter-scope", "specwriter-explorer"]
    for name in verifying:
        frontmatter = (ROOT / f".cursor/agents/{name}.md").read_text().split("---")[1]
        check(f"{name} holds a docs fetch tool", "get_internal_document_by_url" in frontmatter
              or "get_document_by_url" in frontmatter, frontmatter)

    print("all crew-lint tool-reference checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
