#!/usr/bin/env python3
"""The one hook contract, asserted per hook rather than per rule.

Three outcomes, each with exactly one observable shape:

- block: Claude `PreToolUse` exits 2 with one line on stderr and nothing on stdout, because a
  permission payload *and* exit 2 in the same run is the combination the docs call ambiguous.
  Cursor's `preToolUse` and `beforeShellExecution` keep their native JSON deny on stdout, the only
  shape that harness reads.
- no objection: exit 0 with empty stdout and empty stderr, so the harness's own permission flow
  decides. A `permission: allow` payload would skip interactive approval.
- cannot judge: one line on stderr and exit 0, so a missing parser or an unreadable payload never
  becomes a blocked tool call. The credential rule is the sole exception: it is registered
  `onFailure: "block"` / `failClosed: true` and blocks here too.

Every hook file must be classified in `BLOCKING` or `SILENT`, so a new hook cannot skip the matrix.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
# Resolved once: the missing-`jq` case replaces PATH, which would otherwise hide `bash` too.
BASH = shutil.which("bash") or "/bin/bash"
STDERR_LINES = 1
SECRET_LINE = "key=AKI" + "AABCDEFGHIJKLMNOP\n"

# Each blocking hook with the payloads that pin both verdicts.
#   shell      — Cursor's `beforeShellExecution` carrying a top-level `command`, rather than
#                `preToolUse` carrying a top-level `file_path`.
#   claude_env — extra environment for the Claude run, where the rule is gated on the executing shell.
#   home       — `real` when the rule compares against the invoking user's `$HOME`.
#   cwd        — which fixture repository the envelope reports, when the rule reads the index.
BLOCKING = {
    "guard/destructive-git.sh": {
        "shell": True,
        "deny": [{"command": "git reset --hard"}, {"command": "git push -f origin main"}],
        "allow": [{"command": "git status"}, {"command": "git push --force-with-lease origin main"}],
    },
    "guard/local-pr-ref.sh": {
        "shell": True,
        "deny": [{"command": "gh pr checkout 12"}, {"command": "git fetch origin refs/pull/5/head"}],
        "allow": [{"command": "gh pr diff 12"}, {"command": "git fetch upstream main"}],
    },
    "guard/zsh-equals.sh": {
        "shell": True,
        # The gate falls back to `$SHELL` because this harness sets no declaration: without that
        # fallback the rule was dead code and `echo =====` went straight through.
        "claude_env": {"SHELL": "/bin/zsh"},
        # Measured with `zsh -c '<cmd>; echo after'`: every unquoted word whose first character is
        # `=` is a command-path lookup that prints `not found` and drops the rest of the line.
        "deny": [{"command": "echo ===="}, {"command": "echo ====="},
                 {"command": "echo x == y"}, {"command": "echo =nonesuch"},
                 {"command": "cat a.md; echo =======DISPATCH; cat b.md"}],
        "allow": [{"command": "echo ="}, {"command": "echo '===='"},
                  {"command": "printf '%s\\n' '---'"}, {"command": 'echo "a=b"'},
                  {"command": "x=1; echo $x"}, {"command": 'rg -n "===" f'},
                  {"command": "jq -n '{a:1}'"}],
    },
    "guard/credentials.sh": {
        "shell": True,
        "fail_closed": True,
        "deny": [{"command": "gh pr create --draft", "cwd": "clean"},
                 {"command": "git commit -m leak", "cwd": "secret"}],
        "allow": [{"command": "git commit -m ok", "cwd": "clean"},
                  {"command": "gh pr create --draft --repo example/upstream", "cwd": "clean"}],
    },
    "check-write-boundary.sh": {
        "home": "real",
        "deny": [{"file_path": "/outside/file"}],
        "allow": [{"file_path": str(ROOT / "README.md")}],
    },
    "guard/source-edit.sh": {
        "shell": True,
        "deny": [{"command": "python3 - <<'PY'\nopen('tracked.txt', 'w').write('x')\nPY", "cwd": "source"}],
        "allow": [{"command": "python3 - <<'PY'\nprint(1)\nPY", "cwd": "source"}],
    },
    "check-task-spec-owner.sh": {
        "deny": [{"file_path": "{tasks}/AAA-other/SPEC.md",
                  "content": "# Spec: Reviewer finding kind axis and confidence"},
                 # A shorter title sharing the leading words is a different task, not this one.
                 {"file_path": "{tasks}/AAA-other/SPEC.md", "content": "# Spec: Align agent"}],
        "allow": [{"file_path": "{tasks}/AAA-other/SPEC.md",
                   "content": "# Spec: Align agent tool frontmatter with the harness"}],
    },
}

# Hooks whose stdout is their product: only failure handling is pinned here.
SILENT = (
    "mode-anchor.sh",
    "memory-context.sh",
    "cursor-memory-context.sh",
    "notify-idle.sh",
    "session-event.sh",
    "log-tool-use.sh",
    "memory-capture-prompt.sh",
    "spec-status-reconcile.sh",
)

FAILURE_INPUTS = (("{not json", "malformed JSON"), ("", "empty input"))


def classified() -> list[str]:
    """Every hook script, including the ones under `guard/`."""
    names = [path.name for path in HOOKS.glob("*.sh")]
    return sorted(names + [f"guard/{path.name}" for path in (HOOKS / "guard").glob("*.sh")])


def repository(path: Path, staged_name: str | None = None, staged: str = "x\n") -> Path:
    """A repository with one commit, and an optional extra file staged under `staged_name`."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=a@b", "-c", "user.name=a",
                    "commit", "-qm", "base"], check=True)
    if staged_name is not None:
        (path / staged_name).write_text(staged, encoding="utf-8")
        subprocess.run(["git", "-C", str(path), "add", staged_name], check=True)
    return path


def fixture() -> tuple[Path, dict[str, Path]]:
    """A throwaway home with two task directories and the repositories the rules read."""
    home = Path(tempfile.mkdtemp(prefix="hook-contract-"))
    tasks = home / ".agent" / "tasks"
    for name, slug in (("AAA-other", "align-agent-tool-frontmatter"),
                       ("AAA-own", "align-frontmatter")):
        (tasks / name).mkdir(parents=True)
        (tasks / name / ".task-id").write_text(json.dumps({"slug": slug}), encoding="utf-8")
    repos = {
        "clean": repository(home / "clean"),
        "secret": repository(home / "secret", "leak.txt", SECRET_LINE),
        "source": repository(home / "source", "tracked.txt", "one\n"),
    }
    subprocess.run(["git", "-C", str(repos["clean"]), "remote", "add", "upstream",
                    "https://example.test/upstream.git"], check=True)
    return home, repos


def jqless_path() -> str:
    """A complete PATH minus `jq`, so the missing-parser case needs no uninstall.

    Every executable the hooks may legitimately call is linked into one directory and `PATH` is set
    to exactly that, so `command -v jq` fails while `python3`, `git`, and the text tools still work.
    """
    shim = Path(tempfile.mkdtemp(prefix="hook-no-jq-"))
    directories = os.environ.get("PATH", "").split(os.pathsep) + ["/usr/bin", "/bin", "/usr/sbin"]
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for entry in os.listdir(directory):
            if entry == "jq" or entry in os.listdir(shim):
                continue
            target = os.path.join(directory, entry)
            if os.path.isfile(target) and os.access(target, os.X_OK):
                (shim / entry).symlink_to(target)
        if (shim / "python3").exists() and (shim / "git").exists() and (shim / "cat").exists():
            break
    assert (shim / "python3").exists(), "python3 is required to feed a hook its input"
    assert (shim / "cat").exists(), "cat is required to feed a hook its input"
    assert not (shim / "jq").exists(), "the shim must not carry jq"
    return str(shim)


def run(hook: str, stdin: str, home: Path, path: str | None = None,
        extra_env: dict[str, str] | None = None) -> tuple[int, str, str]:
    environment = {**os.environ, "HOME": str(home)}
    environment.pop("CREW_SHELL_IS_ZSH", None)
    environment.update(extra_env or {})
    if path:
        environment["PATH"] = path
    done = subprocess.run([BASH, str(HOOKS / hook)], input=stdin, text=True,
                          capture_output=True, env=environment, timeout=120)
    return done.returncode, done.stdout, done.stderr


def cursor_verdict(stdout: str) -> str | None:
    """The `permission` value Cursor's shape carries, or None when the hook printed nothing."""
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout).get("permission")
    except (json.JSONDecodeError, AttributeError):
        return "unparseable"


def split(case: dict, home: Path, repos: dict[str, Path]) -> tuple[dict, str]:
    """The tool-input fields, and the cwd the envelope reports, with `{tasks}` and `cwd` resolved."""
    tasks = str(home / ".agent" / "tasks")
    fields = {key: value.replace("{tasks}", tasks) for key, value in case.items() if key != "cwd"}
    return fields, str(repos[case.get("cwd", "clean")])


def deny_failures(name: str, spec: dict, home: Path, repos: dict[str, Path]) -> list[str]:
    failures: list[str] = []
    cursor_event = "beforeShellExecution" if spec.get("shell") else "preToolUse"
    for case in spec["deny"]:
        fields, cwd = split(case, home, repos)
        claude = json.dumps({"hook_event_name": "PreToolUse", "cwd": cwd, "tool_input": fields})
        code, out, err = run(name, claude, home, extra_env=spec.get("claude_env"))
        if (code, out) != (2, "") or len(err.strip().splitlines()) != STDERR_LINES:
            failures.append(f"{name}: Claude deny expected exit 2, empty stdout, one stderr line; "
                            f"got exit {code} stdout={out!r} stderr={err!r} for {case}")
        cursor = json.dumps({"hook_event_name": cursor_event, "cwd": cwd, **fields})
        code, out, err = run(name, cursor, home)
        if (code, err, cursor_verdict(out)) != (0, "", "deny"):
            failures.append(f"{name}: Cursor deny expected exit 0 and a JSON deny; got exit {code} "
                            f"stdout={out!r} stderr={err!r} for {case}")
    return failures


def allow_failures(name: str, spec: dict, home: Path, repos: dict[str, Path]) -> list[str]:
    """Claude allows silently; a Cursor hook that fails closed has to say so explicitly."""
    failures: list[str] = []
    cursor_event = "beforeShellExecution" if spec.get("shell") else "preToolUse"
    for case in spec["allow"]:
        fields, cwd = split(case, home, repos)
        claude = {"hook_event_name": "PreToolUse", "cwd": cwd, "tool_input": fields}
        code, out, err = run(name, json.dumps(claude), home, extra_env=spec.get("claude_env"))
        if (code, out, err) != (0, "", ""):
            failures.append(f"{name}: Claude allow expected exit 0 and no output; got exit {code} "
                            f"stdout={out!r} stderr={err!r} for {case}")
        cursor = {"hook_event_name": cursor_event, "cwd": cwd, **fields}
        code, out, err = run(name, json.dumps(cursor), home)
        # Cursor's `failClosed: true` reads "no output at all" as a crash, so that one registration
        # answers `{}` — an empty decision, which grants nothing and skips no approval. Every other
        # Cursor run is silent, like Claude.
        if spec.get("fail_closed"):
            try:
                decision: object = json.loads(out) if out.strip() else None
            except json.JSONDecodeError:
                decision = out
            expected_label, ok = "{}", decision == {}
        else:
            expected_label, ok = "no output", out == ""
        if (code, err, ok) != (0, "", True):
            failures.append(f"{name}: Cursor allow expected exit 0 and {expected_label}; "
                            f"got exit {code} stdout={out!r} stderr={err!r} for {case}")
        del expected_label
    return failures


def unreadable_failures(name: str, spec: dict, home: Path, bare: str) -> list[str]:
    """A hook that cannot read its input reports one line and gets out of the way."""
    failures: list[str] = []
    expected = 2 if spec.get("fail_closed") else 0
    for payload, label in FAILURE_INPUTS:
        code, out, err = run(name, payload, home)
        if (code, out) != (expected, "") or len(err.strip().splitlines()) != STDERR_LINES:
            failures.append(f"{name}: {label} expected exit {expected}, empty stdout, one stderr "
                            f"line; got exit {code} stdout={out!r} stderr={err!r}")
    probe = json.dumps({"hook_event_name": "PreToolUse", "cwd": str(home),
                        "tool_input": spec["deny"][0]})
    code, out, err = run(name, probe, home, path=bare)
    if (code, out) != (expected, "") or len(err.strip().splitlines()) != STDERR_LINES:
        failures.append(f"{name}: missing jq expected exit {expected}, empty stdout, one stderr "
                        f"line; got exit {code} stdout={out!r} stderr={err!r}")
    return failures


def silent_failures(name: str, home: Path, bare: str) -> list[str]:
    failures: list[str] = []
    for payload, label in FAILURE_INPUTS:
        code, out, err = run(name, payload, home)
        if code != 0 or len(err.strip().splitlines()) > STDERR_LINES:
            failures.append(f"{name}: {label} expected exit 0 and at most one stderr line; got "
                            f"exit {code} stdout={out!r} stderr={err!r}")
    code, out, err = run(name, "{}", home, path=bare)
    if code != 0 or len(err.strip().splitlines()) > STDERR_LINES:
        failures.append(f"{name}: missing jq expected exit 0 and at most one stderr line; got "
                        f"exit {code} stdout={out!r} stderr={err!r}")
    return failures


def main() -> int:
    home, repos = fixture()
    bare = jqless_path()
    present = classified()
    failures = [f"unclassified hook: {name}" for name in present
                if name not in set(BLOCKING) | set(SILENT)]
    expected = set(BLOCKING).union(SILENT)
    failures += [f"missing hook: {name}" for name in sorted(expected - set(present))]
    for name, spec in sorted(BLOCKING.items()):
        if name not in present:
            continue
        hook_home = Path.home() if spec.get("home") == "real" else home
        failures += deny_failures(name, spec, hook_home, repos)
        failures += allow_failures(name, spec, hook_home, repos)
        failures += unreadable_failures(name, spec, hook_home, bare)
    for name in SILENT:
        if name in present:
            failures += silent_failures(name, home, bare)
    for line in failures:
        print(f"error: {line}")
    if failures:
        print(f"fail: {len(failures)} contract violation(s)")
        return 1
    print(f"pass: {len(BLOCKING)} blocking and {len(SILENT)} other hook(s) hold the contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
