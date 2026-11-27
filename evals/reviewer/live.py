#!/usr/bin/env python3
"""The live reviewer eval: dispatch each persona on its own lens's cases through the harness, record and score it.

Opt-in and never in CI: without `--yes-spend` it prints what it would dispatch and exits; under `CI` it refuses.
Each dispatch is an isolated `claude -p` (`ISOLATION`: no settings files, hooks, MCP servers or skills; file tools
confined to a scratch root holding only the case) running the persona defined from its source file with Read, Grep
and Glob. A run that touched a path outside the root is recorded as tainted. Replies land in
`recorded/<label>/<persona>/<case>/run-<n>.md`, then `score.py` prints each persona's mean and per-run rates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from score import HERE, PATH_ANCHOR, PERSONAS, Case, load_cases, render, tally

ROOT = HERE.parents[1]
AGENTS_DIR = ROOT / ".cursor" / "agents"
REFERENCES = AGENTS_DIR / "references"
RECORDED = HERE / "recorded"
RUNS = 3
TIMEOUT = 900  # seconds per dispatch
MAX_FAILURES = 3  # consecutive failed dispatches before the run stops (exit 3)
FAILED = "status: failed"
TOOLS = ("Read", "Grep", "Glob")
AGENTS = {persona: persona if persona.startswith("specwriter-") else f"reviewer-{persona}" for persona in PERSONAS}
# `claude --help` documents each: --restricted ignores user, project and local settings files (their hooks and
# plugins with them) and confines the file tools to the working directories; --strict-mcp-config with no
# --mcp-config loads no MCP server; --disable-slash-commands turns skills off; --tools limits the built-in tools;
# --permission-prompts none denies whatever would prompt. --bare is not used: it never reads OAuth or the keychain.
ISOLATION = ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--tools", ",".join(TOOLS),
             "--permission-prompts", "none", "--no-session-persistence", "--output-format", "stream-json",
             "--verbose")
NO_LOOKUPS = "No code index or docs server in this eval; use Read, Grep and Glob on the case files.\n"
MODE = """# Mode

Self review of a code diff. Label vocabulary: `[blocking]`, `[attention]`, `[needs more info]`, `[nit]`.

**Return shape:** reply text only. Do not write files. A flat numbered list of findings, each beginning with its
severity label and carrying a `path:line` anchor. If you have no findings, end your reply with the exact line
`### Findings: none`.
"""
CRITIC_HEAD = """## Critique context

You are reviewing a draft SPEC.md before it is presented to the user.
Find problems — do not suggest rewrites. The specwriter will apply fixes.
"""
PATH_KEYS = ("file_path", "path", "notebook_path")


def agent_definition(lens: str) -> dict:
    """`--agents` JSON for one persona from its source file: its prompt and turn limit, the read tools only."""
    text = (AGENTS_DIR / f"{AGENTS[lens]}.md").read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    fields = dict(re.findall(r"^(\w+):[ \t]*(.*?)[ \t]*$", frontmatter, re.M))
    definition = {"description": fields.get("description", "").strip('"'), "prompt": body.strip(),
                  "tools": list(TOOLS)}
    if fields.get("maxTurns", "").isdigit():
        definition["maxTurns"] = int(fields["maxTurns"])
    return {AGENTS[lens]: definition}


def command(claude: str, case: Case) -> list[str]:
    return [claude, "-p", *ISOLATION, "--agents", json.dumps(agent_definition(case.lens)), "--agent", AGENTS[case.lens]]


def contract(*names: str) -> str:
    """A shared contract (its parts joined as `assemble_inputs.contract_text` joins them) with its lookups paragraph
    replaced by `NO_LOOKUPS`: the eval has no index or docs server."""
    text = "\n".join((REFERENCES / name).read_text(encoding="utf-8") for name in names)
    return re.sub(r"^Lookups: follow .*?(?=\n\n|\Z)", NO_LOOKUPS.strip(), text, flags=re.M | re.S)


def package(case: Case) -> str:
    """The dispatch prompt: what a real review or critique sends this persona, with no lookup servers to use."""
    if case.kind == "spec":
        return (f"{CRITIC_HEAD}\n## Draft spec\n\n{case.text()}\n## Critic contract\n\n"
                f"{contract('critic-contract.md')}\n---\n\n"
                "Produce your critique now, in the shape the contract and your persona define.\n")
    unchanged = ", ".join(f"`{path}`" for path in case.context) or "none"
    return "".join([
        contract("reviewer-contract.md", "reviewer-reads.md"), "\n---\n\n", MODE,
        "\n---\n\n## The change\n\n", case.summary,
        "\n\nThe working directory holds the changed files after the change and these files the diff leaves "
        f"unchanged: {unchanged}.\n\n# Diff\n\n```diff\n", case.text(), "```\n",
    ])


def scratch_tree(case: Case, root: Path) -> None:
    """The files a persona may read: the changed files after the change, the unchanged context, and the spec."""
    files = {**case.context, **case.after}
    if case.kind == "spec":
        files["SPEC.md"] = case.text()
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def outside(path: str, roots: tuple[str, ...]) -> bool:
    """True for an absolute or home path that is not under the scratch root."""
    if not path.startswith(("/", "~")):
        return False
    resolved = os.path.realpath(os.path.expanduser(path))
    return not any(resolved == root or resolved.startswith(root + os.sep) for root in roots)


def relative(value: str, roots: tuple[str, ...]) -> str:
    """A path under the scratch root as a path relative to it, so a recorded call reads the same on every run."""
    for root in roots:
        if value == root:
            return "."
        if value.startswith(root + os.sep):
            return value[len(root) + 1:]
    return value


def audit_call(item: dict, roots: tuple[str, ...]) -> dict:
    """One tool call for the audit trail: its name and the path or pattern it was given."""
    call = {"name": str(item.get("name"))}
    for key, value in item["input"].items():
        if isinstance(value, str) and key == "pattern":
            call["pattern"] = value
        elif isinstance(value, str) and key in PATH_KEYS:
            call["path"] = relative(value, roots)
    return call


def stream_events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def content_items(event: dict, kind: str) -> list[dict]:
    """The `kind` items (`tool_use`, `tool_result`) of an assistant or user message event."""
    content = (event.get("message") or {}).get("content")
    return [item for item in content if isinstance(item, dict) and item.get("type") == kind] \
        if isinstance(content, list) else []


def read_stream(stdout: str, roots: tuple[str, ...]) -> tuple[str, dict]:
    """The final reply from `stream-json` output, and its audit: every tool call (`calls`, with `error` when its
    result was an error), the session's `num_turns`, and the calls whose path leaves the scratch root.

    A call outside the root whose result was an error read nothing (a mistyped or missing path), so it is listed
    under `outside_failed`; every other call outside the root, including one whose result never arrived, is
    `tainted`.
    """
    events = stream_events(stdout)
    failed = {item.get("tool_use_id") for event in events if event.get("type") == "user"
              for item in content_items(event, "tool_result") if item.get("is_error")}
    reply, audit = "", {"tainted": [], "outside_failed": [], "calls": [], "num_turns": None}
    for event in events:
        if event.get("type") == "result":
            reply = str(event.get("result") or "")
            turns = event.get("num_turns")
            audit["num_turns"] = turns if isinstance(turns, int) else None
        for item in content_items(event, "tool_use") if event.get("type") == "assistant" else []:
            if not isinstance(item.get("input"), dict):
                continue
            call, errored = audit_call(item, roots), item.get("id") in failed
            audit["calls"].append({**call, "error": True} if errored else call)
            leaks = [f"{item.get('name')} {value}" for key, value in item["input"].items()
                     if key in PATH_KEYS and isinstance(value, str) and outside(value, roots)]
            audit["outside_failed" if errored else "tainted"] += leaks
    return reply, audit


def dispatch(claude: str, case: Case, timeout: int) -> tuple[str, dict]:
    """One isolated persona run: the reply (or a `status: failed` record keeping any output) and its meta."""
    with tempfile.TemporaryDirectory(prefix=f"reviewer-eval-{case.id}-") as scratch:
        scratch_tree(case, Path(scratch))
        roots = tuple({scratch, os.path.realpath(scratch)})
        env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
        try:
            done = subprocess.run(command(claude, case), input=package(case), cwd=scratch, capture_output=True,
                                  text=True, timeout=timeout, check=False, env=env)
        except subprocess.TimeoutExpired as error:
            partial = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
            _, audit = read_stream(partial, roots)
            return (f"{FAILED} — no reply within {timeout} s\n\n{partial}",
                    {"exit": None, "scratch": Path(scratch).name, **audit})
        except OSError as error:  # FileNotFoundError, PermissionError
            return (f"{FAILED} — could not start {claude}: {error}\n",
                    {"exit": None, "scratch": Path(scratch).name, "tainted": [], "outside_failed": [], "calls": [],
                     "num_turns": None})
        reply, audit = read_stream(done.stdout, roots)
        audit["tainted"] += [f"cited {match.group('path')}" for match in PATH_ANCHOR.finditer(reply)
                             if outside(match.group("path"), roots)]
    # `scratch` names the run's root, so a recorded path outside it can be compared with the real one.
    meta = {"exit": done.returncode, "scratch": Path(scratch).name, **audit}
    if done.returncode or not reply.strip():
        return (f"{FAILED} — exit {done.returncode}: {(done.stderr or '').strip()[:500]}\n\n"
                f"{reply or done.stdout}"), meta
    return reply, meta


def recorded(target: Path) -> bool:
    """A reply already paid for: present and not a failure record."""
    return target.is_file() and not target.read_text(encoding="utf-8", errors="replace").startswith(FAILED)


def selected(cases: list[Case], personas: list[str], ids: list[str]) -> list[Case]:
    return [case for case in cases if (not personas or case.lens in personas) and (not ids or case.id in ids)]


def plan(cases: list[Case], targets: int, todo: int, out: Path) -> str:
    counts = {persona: sum(case.lens == persona for case in cases) for persona in PERSONAS}
    lines = [f"{persona:<24} {count} cases" for persona, count in counts.items() if count]
    return "\n".join([*lines, f"{targets - todo} already recorded, {todo} to dispatch (each a full agent session "
                      "on the harness's model and account)", f"replies go to {out}"])


def run_all(claude: str, timeout: int, todo: list[tuple[Case, Path]]) -> int:
    """Dispatch each target in order; stop with 3 after `MAX_FAILURES` failures in a row."""
    failures = 0
    for case, target in todo:
        reply, meta = dispatch(claude, case, timeout)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(reply, encoding="utf-8")
        target.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        failures = failures + 1 if reply.startswith(FAILED) else 0
        notes = (" (failed)" if failures else "") + (" (tainted)" if meta["tainted"] else "")
        print(f"recorded {target}{notes}", flush=True)
        if failures >= MAX_FAILURES:
            print(f"live: {failures} dispatches failed in a row; stopping. The last record: {target}", file=sys.stderr)
            return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the reviewer personas on the seeded-defect cases (opt-in).")
    parser.add_argument("--yes-spend", action="store_true", help="actually dispatch; without it, print the plan only")
    parser.add_argument("--persona", action="append", default=[], choices=PERSONAS, help="limit to a persona")
    parser.add_argument("--case", action="append", default=[], help="limit to a case id")
    parser.add_argument("--runs", type=int, default=RUNS, help=f"runs per case (default {RUNS})")
    parser.add_argument("--redo", action="store_true", help="dispatch again where a good reply is already recorded")
    parser.add_argument("--label", default=date.today().isoformat(), help="the recorded/<label> directory")
    parser.add_argument("--out", type=Path, default=RECORDED, help="the directory that holds <label>")
    parser.add_argument("--claude", default="claude", help="the Claude Code executable")
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help=f"seconds per dispatch (default {TIMEOUT})")
    args = parser.parse_args(argv)
    cases = selected(load_cases(), args.persona, args.case)
    out = args.out / args.label
    if not cases or args.runs < 1:
        print("live: no case selected", file=sys.stderr)
        return 2
    targets = [(case, out / case.lens / case.id / f"run-{n}.md") for case in cases for n in range(1, args.runs + 1)]
    todo = [(case, target) for case, target in targets if args.redo or not recorded(target)]
    print(plan(cases, len(targets), len(todo), out))
    if not args.yes_spend:
        print("dry run: nothing dispatched. Add --yes-spend to run it.")
        return 0
    if os.environ.get("CI"):
        print("live: refusing to dispatch under CI; the live eval is the owner's run", file=sys.stderr)
        return 2
    if shutil.which(args.claude) is None:
        print(f"live: {args.claude} is not on PATH", file=sys.stderr)
        return 2
    code = run_all(args.claude, args.timeout, todo)
    print(render(tally(out, cases)))
    return code


if __name__ == "__main__":
    sys.exit(main())
