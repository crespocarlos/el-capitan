"""The escaped-command rule must fire on a disguised subcommand, not on a backslash in a quoted arg.

The rule denied `gh pr view --jq '"#\\(.number)"'` because it scanned the raw command, where a
backslash inside quoted content looked like an escape. It now blanks quoted content first, so a quoted
backslash is invisible while `git res\\et` still denies.
"""
import json
import pathlib
import subprocess

ROOT = pathlib.Path("/Users/ccrespo/Documents/dev/el-capitan")
HOOK = ROOT / ".claude/hooks/guard/destructive-git.sh"


def verdict(command: str) -> str:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"command": command},
                          "cwd": str(ROOT)})
    result = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True)
    return "deny" if result.returncode == 2 else "allow"


cases = [
    # The reported command: a jq filter with escapes inside single quotes. Read-only, must allow.
    ("""gh pr view --json url,number,state --jq '"#\\(.number) (\\(.state)): \\(.url)"'""", "allow"),
    # A backslash inside plain double quotes. Read-only, must allow.
    ('gh pr view --json number --jq "#\\(.number)"', "allow"),
    # A jq filter with no escapes at all, for contrast.
    ("""gh pr view --json number --jq '"#" + (.number|tostring)'""", "allow"),
    # The form the rule exists for: a backslash hides the subcommand from pattern matching.
    ("git res\\et --hard", "deny"),
    ("gh pr chec\\kout 12", "deny"),
    ("git -C repo res\\et --hard", "deny"),
    # Unrelated read-only commands stay allowed.
    ("gh pr diff 12", "allow"),
    ("git status", "allow"),
]

failures = 0
for command, want in cases:
    got = verdict(command)
    mark = "ok  " if got == want else "FAIL"
    if got != want:
        failures += 1
    print(f"{mark} want={want:6} got={got:6} {command[:70]}")

print("all escape-rule checks passed" if not failures else f"escape-rule: {failures} failed")
