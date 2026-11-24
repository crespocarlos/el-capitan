#!/usr/bin/env python3
"""`crew-lint` fails an agent that reads only but never declares `readonly: true`.

Cursor inherits every parent tool into a subagent and honours no `tools:` line, so `readonly: true` is
the only thing stopping a reviewer persona from editing the tree mid-review. Nothing enforced it: the
flag was copied by hand into each persona, and a new one could ship without it and still pass lint,
because an absent key looks like every other absent key.

The rule has two exemption sets, and both are the point of the test: a worker that writes by definition
(`crew-builder`, `crew-pr-resolver`) and an orchestrator the router refuses to dispatch, where a
subagent-only field cannot apply. A blanket rule would flag both, and the temptation is to satisfy it by
setting the flag on an agent that must write.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "maintenance" / "crew-lint.py"


def make_root(base: Path, agents: dict[str, str]) -> Path:
    """A repo holding only what the frontmatter rule reads: the catalog and the agent files."""
    root = base / "repo"
    (root / ".agent" / "tools").mkdir(parents=True)
    (root / ".cursor" / "agents").mkdir(parents=True)
    (root / "rules").mkdir()
    (root / ".agent" / "tools" / "tools.json").write_text(json.dumps({
        "schema_version": 1, "tools": [], "scripts": [], "assets": [],
        "mcp_servers": {}, "native_tools": ["Read", "Grep", "Glob"],
    }))
    for name, frontmatter in agents.items():
        (root / ".cursor" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: \"Fixture agent.\"\n{frontmatter}---\nBody.\n"
        )
    return root


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--root", str(root)],
                          capture_output=True, text=True)


def findings(result: subprocess.CompletedProcess, rule: str) -> list[str]:
    return [line for line in result.stdout.splitlines() if f": {rule}: " in line]


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"pass: {name}")


def test_a_read_only_agent_without_the_flag_is_a_finding() -> None:
    """The case the rule exists for: a persona that never writes, silently able to."""
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), {"reviewer-fixture": "tools: Read\n"})
        result = run(root)
        hits = findings(result, "missing-readonly")
        check("an unflagged persona is reported", len(hits) == 1, result.stdout + result.stderr)
        check("the finding names the file", hits[0].startswith(".cursor/agents/reviewer-fixture.md:1:"),
              hits[0])
        check("an unflagged persona exits 1", result.returncode == 1, str(result.returncode))


def test_the_flag_clears_the_finding() -> None:
    """Positive control: the fix the message asks for is enough."""
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), {"reviewer-fixture": "readonly: true\ntools: Read\n"})
        result = run(root)
        check("a flagged persona is silent", not findings(result, "missing-readonly"), result.stdout)
        check("a flagged persona exits 0", result.returncode == 0, result.stdout + result.stderr)


def test_a_false_value_is_not_a_declaration() -> None:
    """`readonly: false` is a decision to write, so it cannot pass as the read-only declaration."""
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), {"reviewer-fixture": "readonly: false\n"})
        result = run(root)
        check("readonly: false is still a finding", len(findings(result, "missing-readonly")) == 1,
              result.stdout)


def test_a_worker_that_declares_readonly_is_refused() -> None:
    """The mirror failure: the flag copied into a writing agent blocks every edit it exists to make."""
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), {"crew-builder": "readonly: true\n"})
        result = run(root)
        hits = findings(result, "unexpected-readonly")
        check("a readonly worker is reported", len(hits) == 1, result.stdout + result.stderr)
        check("the finding says what it blocks", "block every edit" in hits[0], hits[0])


def test_an_exempt_writer_writes_freely() -> None:
    """Both exemption sets, because a blanket rule would demand a flag that breaks them."""
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), {
            "crew-builder": "",
            "crew-pr-resolver": "",
            "crew-reviewer": "",
            "crew-specwriter": "",
        })
        result = run(root)
        hits = findings(result, "missing-readonly")
        check("no worker or orchestrator is flagged", not hits, result.stdout)
        check("exempt agents exit 0", result.returncode == 0, result.stdout + result.stderr)


def test_a_broken_frontmatter_is_its_own_finding() -> None:
    """An unclosed block would otherwise read as `no readonly key`, naming the wrong thing."""
    with tempfile.TemporaryDirectory() as temporary:
        root = make_root(Path(temporary), {})
        (root / ".cursor" / "agents" / "reviewer-broken.md").write_text(
            "---\nname: reviewer-broken\ndescription: \"Fixture agent.\"\nBody.\n"
        )
        result = run(root)
        check("broken frontmatter is reported as such", len(findings(result, "invalid-agent-frontmatter")) == 1,
              result.stdout)
        check("broken frontmatter does not also claim the flag is missing",
              not findings(result, "missing-readonly"), result.stdout)


def test_the_repository_itself_passes() -> None:
    """The real tree is the fixture that matters: every shipped persona must satisfy the rule."""
    root = Path(__file__).resolve().parents[2]
    result = run(root)
    check("the repo reports no missing readonly", not findings(result, "missing-readonly"),
          result.stdout)


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as error:
            failed += 1
            print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
