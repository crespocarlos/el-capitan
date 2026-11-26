"""An escaped or optioned subcommand is denied by the guard that owns it; a quoted backslash is data.

Each case names the guard that speaks for its command (`destructive-git` for `git reset`,
`local-pr-ref` for `gh pr checkout`) and runs through that guard alone, as the harness would run it.
The script exits 1 when any case gets the wrong verdict.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARDS = ROOT / ".claude/hooks/guard"


def verdict(command: str, guard: str) -> str:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"command": command},
                          "cwd": str(ROOT)})
    result = subprocess.run(["bash", str(GUARDS / f"{guard}.sh")], input=payload, capture_output=True,
                            text=True, timeout=60)
    return "deny" if result.returncode == 2 else "allow"


CASES = [
    # A jq filter with escapes inside quotes is read-only data.
    ("""gh pr view --json url,number,state --jq '"#\\(.number) (\\(.state)): \\(.url)"'""", "local-pr-ref", "allow"),
    ('gh pr view --json number --jq "#\\(.number)"', "destructive-git", "allow"),
    ("""gh pr view --json number --jq '"#" + (.number|tostring)'""", "local-pr-ref", "allow"),
    # A backslash, a quote or an option in front hides no subcommand.
    ("git res\\et --hard", "destructive-git", "deny"),
    ("git -C repo res\\et --hard", "destructive-git", "deny"),
    ("gh pr chec\\kout 12", "local-pr-ref", "deny"),
    ("g\\h pr checkout 12", "local-pr-ref", "deny"),
    ("gh pr 'check'out 12", "local-pr-ref", "deny"),
    ("gh pr -R owner/repo checkout 12", "local-pr-ref", "deny"),
    ("gh pr --repo=owner/repo chec\\kout 12", "local-pr-ref", "deny"),
    ("echo 12 | xargs gh pr co", "local-pr-ref", "deny"),
    ("bash -c 'gh pr chec\\kout 12'", "local-pr-ref", "deny"),
    # Read-only commands stay allowed.
    ("gh pr diff 12", "local-pr-ref", "allow"),
    ("gh pr -R owner/repo view 12", "local-pr-ref", "allow"),
    ('grep "gh" notes.txt', "local-pr-ref", "allow"),
    ("git status", "destructive-git", "allow"),
]


def main() -> int:
    failures = 0
    for command, guard, want in CASES:
        got = verdict(command, guard)
        if got != want:
            failures += 1
        print(f"{'ok  ' if got == want else 'FAIL'} want={want:5} got={got:5} {guard:15} {command[:60]}")
    print("escape-rule: pass" if not failures else f"escape-rule: {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
