"""Gates a repository describes in words, and CI it declares but verify cannot read.

A repo such as Kibana has no GitHub workflow: its CI is Buildkite, and its checks are sentences in
the nearest `AGENTS.md` ("run `node scripts/check.js --scope=local`"). Verify cannot mirror either,
so it names the CI it skipped and surfaces the prose commands to the builder. A prose command is
NEVER run: it is a line a person wrote, not a declaration, so the builder runs it and reports it.

The nearest `AGENTS.md` for a touched path comes from the resolver `crew-agent-context.py` already
owns (loaded from that file, not copied), so verify and the builder read the same guidance.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Callable

from lib.git import GitError, output

CI_FILES = {".buildkite": "buildkite", ".circleci": "circleci", ".gitlab-ci.yml": "gitlab", "Jenkinsfile": "jenkins",
            ".travis.yml": "travis", "azure-pipelines.yml": "azure", "bitbucket-pipelines.yml": "bitbucket",
            ".drone.yml": "drone"}
RUNNERS = ("node", "npm", "npx", "yarn", "pnpm", "bun", "make", "python", "python3", "pytest", "tox", "nox", "cargo",
           "go", "mvn", "gradle", "bash", "sh", "bundle", "rake", "dotnet", "uv", "poetry")
KEYWORDS = ("check", "test", "lint", "type", "verify", "format", "fmt", "ci", "jest", "eslint", "tsc")
GATES_BLOCK = re.compile(r"^```gates[ \t]*\n.*?^```[ \t]*\n?", re.M | re.S)
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
INLINE = re.compile(r"`([^`\n]+)`")
LIMIT = 20


def unreadable_ci(root: Path, ref: str | None) -> list[str]:
    """Names of CI systems the repo declares at the top level that no reader here understands."""
    try:
        names = (output(root, ["ls-tree", "--name-only", ref]).split("\n") if ref
                 else [p.name for p in root.iterdir()])
    except (GitError, OSError):
        return []
    return sorted({CI_FILES[name.strip()] for name in names if name.strip() in CI_FILES})


def is_check(line: str) -> bool:
    words = line.split()
    if not words or not (words[0] in RUNNERS or words[0].startswith("./")):
        return False
    return any(token in KEYWORDS for token in re.split(r"[^a-z0-9]+", line.lower()))


def prose_commands(text: str) -> list[str]:
    """Check-looking commands in fenced blocks and backtick spans, in order, without the `gates` block."""
    text = GATES_BLOCK.sub("", text)
    fenced = [line for block in FENCE.findall(text) for line in block.splitlines()]
    inline = INLINE.findall(FENCE.sub("", text))
    found: list[str] = []
    for raw in fenced + inline:
        line = raw.strip().removeprefix("$ ").strip()
        if not line.startswith("#") and is_check(line) and line not in found:
            found.append(line)
    return found[:LIMIT]


def touched_paths(root: Path, ref: str | None) -> list[str]:
    """Paths changed against the base (or HEAD), plus untracked files; empty when git cannot say."""
    try:
        changed = output(root, ["diff", "--name-only", ref or "HEAD"]).split("\n")
        changed += output(root, ["ls-files", "--others", "--exclude-standard"]).split("\n")
    except GitError:
        return []
    return sorted({path for path in changed if path})


def guidance_resolver() -> Callable[[Path, Path], "list[Path]"]:
    """`guidance_paths` of `crew-agent-context.py`, the resolver the builder's guidance comes from."""
    spec = importlib.util.spec_from_file_location("crew_agent_context", Path(__file__).with_name("crew-agent-context.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.guidance_paths


def prose_checks(root: Path, ref: str | None) -> list[dict]:
    """`{command, from}` for the nearest AGENTS.md of each touched path (the root's when nothing is touched)."""
    resolve = guidance_resolver()
    top = root.resolve()
    nearest: list[Path] = []
    for path in touched_paths(root, ref) or ["."]:
        try:
            files = resolve(top, top / path)
        except ValueError:
            continue
        if files and files[-1] not in nearest:
            nearest.append(files[-1])
    checks: list[dict] = []
    for guidance in nearest:
        text = guidance.read_text(encoding="utf-8", errors="replace")
        checks += [{"command": c, "from": str(guidance.relative_to(top))} for c in prose_commands(text)]
    return checks
