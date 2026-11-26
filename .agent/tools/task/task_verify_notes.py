"""What a verify run says about the CI it did not mirror, so a pass is never read as more than it is.

`skipped` (from `task_verify_sources.py`) holds one string per step left out: `<name>: setup step`,
`<name>: has an if: ...`, `<name>: runs a publish ...`, `<job>: job with environment: ...`, `<job>: job
with an if: ...`, `<file>: workflow not mirrored (on: ...)`, `<file>: not CI (on: ...)` and `uses:
<action>`. The setup steps, the `uses:` steps and the workflows that are not CI (no `push` or
`pull_request` trigger) are expected; anything else makes the mirror partial, which is printed as a warning
and recorded as `partial: true`; it also makes the run NOT VERIFIED (`verified: false`, exit 3, or 2 with
`--strict`) even when every gate passed. A failed gate still exits 1.
"""
from __future__ import annotations


def not_ci(skipped: list[str]) -> list[str]:
    """The workflows left out because they are not CI; they never make the run partial."""
    return [s for s in skipped if ": not CI (on: " in s]


def kinds(skipped: list[str]) -> tuple[list[str], list[str], list[str]]:
    """`(setup, other, uses)` entries of the skipped list; the not-CI workflows are in none of them."""
    uses = [s for s in skipped if s.startswith("uses: ")]
    setup = [s for s in skipped if s.endswith(": setup step")]
    expected = set(uses) | set(setup) | set(not_ci(skipped))
    return setup, [s for s in skipped if s not in expected], uses


def is_partial(skipped: list[str]) -> bool:
    return bool(kinds(skipped)[1])


def partial_line(skipped: list[str]) -> str:
    """The verdict line of a partial mirror: its gates may all pass, and it is still not a pass."""
    return f"verify: NOT VERIFIED: partial mirror ({len(kinds(skipped)[1])} steps skipped); a pass here does not prove CI passes"


def partial_exit(skipped: list[str], gates_ok: bool, strict: bool) -> int:
    """The process exit: 1 for a failed gate, else 3 (2 with --strict) when the mirror is partial, else 0."""
    if not gates_ok:
        return 1
    return (2 if strict else 3) if is_partial(skipped) else 0


def note_lines(declared: dict) -> list[str]:
    """The lines printed before any gate runs: the verdict of a partial mirror, the workflow files, what was skipped."""
    gates = declared["gates"]
    files = sorted({g["workflow"] for g in gates if g.get("workflow")})
    setup, other, uses = kinds(declared["skipped"])
    lines = [partial_line(declared["skipped"])] if other and gates else []
    lines += [f"workflows: {', '.join(files)}"] if files else []
    if setup or other:
        lines.append(f"skipped: {len(setup) + len(other)} steps ({'; '.join(setup + other)})")
    if uses:
        lines.append(f"not mirrored: {len(uses)} uses: steps")
    if not_ci(declared["skipped"]):
        lines.append(f"not CI: {'; '.join(not_ci(declared['skipped']))}")
    return lines
