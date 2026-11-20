#!/usr/bin/env python3
"""Hermetic checks for crew-pr-actions.py: the mutation guard, the plan, and the query default.

Every case runs the real CLI as a subprocess with a stub `gh` first on PATH, so the tests observe
what the tool actually does to the outside world rather than what an internal function returns.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-pr-actions.py"
WRAPPER = ROOT / ".agent" / "tools" / "review" / "pr-review-actions.py"


def stub_gh(directory):
    """A `gh` that records its argv and prints a JSON body, so a call is observable."""
    log = directory / "gh.calls"
    script = directory / "gh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'echo \'{"data": {"stub": true}}\'\n'
    )
    script.chmod(0o755)
    return log


def run(arguments, bindir):
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(bindir.parent)}
    return subprocess.run([sys.executable, str(TOOL), *arguments],
                          capture_output=True, text=True, env=env)


def install_query_asset(home):
    """The default --query is the installed asset path, so the scratch HOME gets that file."""
    target = home / ".agent" / "bin" / "pr-review-threads.graphql"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((ROOT / ".agent" / "tools" / "review" / "pr-review-threads.graphql").read_text())
    return target


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"pass: {name}")


REPLY = ("reply", "--repo", "owner/repo", "--pr", "7", "--thread-id", "T_1",
         "--comment-id", "123", "--body", "Fixed.")
RESOLVE = ("resolve", "--repo", "owner/repo", "--pr", "7", "--thread-id", "T_1")


def main():
    with tempfile.TemporaryDirectory() as temporary:
        bindir = Path(temporary) / "bin"
        bindir.mkdir()
        log = stub_gh(bindir)
        asset = install_query_asset(bindir.parent)

        # 1. A mutation without --execute plans and never invokes gh.
        result = run(REPLY, bindir)
        check("plan without --execute exits 0", result.returncode == 0, result.stderr)
        check("plan without --execute does not call gh", not log.exists(),
              log.read_text() if log.exists() else "")
        planned = json.loads(result.stdout)["planned"]
        check("plan names the action", planned["action"] == "reply", planned)
        check("plan names the exact gh command",
              planned["command"][:2] == ["gh", "api"]
              and planned["command"][2].endswith("/comments/123/replies"),
              planned["command"])
        check("plan carries the reply body", planned["body"] == "Fixed.", planned)

        # 2. --dry-run forces the plan even when a caller passes it alongside nothing else.
        result = run(REPLY + ("--dry-run",), bindir)
        check("--dry-run exits 0", result.returncode == 0, result.stderr)
        check("--dry-run does not call gh", not log.exists(),
              log.read_text() if log.exists() else "")
        check("--dry-run reports execute false",
              json.loads(result.stdout)["planned"]["execute"] is False, result.stdout)

        # 3. --execute performs the call, and the argv is the one the plan printed.
        result = run(RESOLVE + ("--execute",), bindir)
        check("--execute exits 0", result.returncode == 0, result.stderr)
        check("--execute calls gh once", log.exists() and len(log.read_text().splitlines()) == 1,
              log.read_text() if log.exists() else "no call")
        called = log.read_text().strip()
        check("--execute resolves the thread", "resolveReviewThread" in called, called)
        check("--execute passes the thread id", "threadId=T_1" in called, called)
        check("--execute prints the gh output", "stub" in result.stdout, result.stdout)

        # --execute and --dry-run are contradictory, so combining them is an invocation error.
        result = run(RESOLVE + ("--execute", "--dry-run"), bindir)
        check("rejects --execute with --dry-run", result.returncode == 2, result.stderr)

        # 4. --repo without a slash is rejected before any call.
        result = run(("resolve", "--repo", "nope", "--pr", "7", "--thread-id", "T_1", "--execute"),
                     bindir)
        check("rejects --repo without a slash", result.returncode != 0, result.stdout + result.stderr)
        check("rejected repo does not call gh", len(log.read_text().splitlines()) == 1,
              log.read_text())

        # 5. The default --query resolves to the graphql asset, and fetch plans without calling gh.
        log.unlink()
        result = run(("fetch", "--repo", "owner/repo", "--pr", "7", "--dry-run"), bindir)
        check("fetch --dry-run exits 0", result.returncode == 0, result.stderr)
        check("fetch --dry-run does not call gh", not log.exists(),
              log.read_text() if log.exists() else "")
        command = json.loads(result.stdout)["planned"]["command"]
        check("default query is the graphql asset",
              f"query=@{asset}" in command, command)
        check("fetch plan names the pr", "-F" in command and "pr=7" in command, command)

        # An explicit --query is honored, not silently replaced by the default.
        custom = bindir.parent / "custom.graphql"
        custom.write_text("query { viewer { login } }\n")
        result = run(("fetch", "--repo", "owner/repo", "--pr", "7", "--dry-run",
                      "--query", str(custom)), bindir)
        check("explicit --query is honored", f"query=@{custom}" in
              json.loads(result.stdout)["planned"]["command"], result.stdout)

        # The deprecated name still works and says so once on stderr.
        env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
               "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(bindir.parent)}
        result = subprocess.run([sys.executable, str(WRAPPER), "--help"],
                                capture_output=True, text=True, env=env)
        check("wrapper --help exits 0", result.returncode == 0, result.stderr)
        check("wrapper names its replacement", "crew-pr-actions.py" in result.stderr, result.stderr)
        check("wrapper warns exactly once", result.stderr.count("deprecated") == 1, result.stderr)

    print("all crew-pr-actions checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
