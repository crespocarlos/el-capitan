"""Where a verify run learns its gates, always from the BASE branch and never from the PR head.

A PR that edits the workflow it is judged by could weaken its own gates, so the declaration is read
from the base ref (`git show <base>:<path>`). CI workflow `run:` steps are THE source whenever the repo
has CI; a fenced `gates` block in `AGENTS.md` is the fallback for a repo with no CI; `.agent/gates.json`
may ADD gates (never remove or change a CI gate, a clash warns) and is used as is when it is the only
source. The source that answered is returned with the gates and printed by the caller.

A `gates` block holds one gate per line, `<name>: <command>`, and `env: NAME=value` lines for
variables every gate shares. Steps that only set up the machine (`npm ci`, `pip install`) are
skipped and listed, as are steps with an `if:` or a `${{ }}` expression, which cannot be mirrored.
What may never be mirrored (a release workflow, a job with an `if:`, a publish command) is decided by
`task_verify_safety.py` and recorded in `skipped`, so the run is partial.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from lib.git import GitError, blob_at, output, rev_parse
from task_verify_safety import is_ci, job_if, not_mirrored, publishes
from task_verify_yaml import parse

WORKFLOWS = ".github/workflows"
SETUP = re.compile(r"^\s*(npm|pnpm|yarn|bun)\s+(ci|install|i)\b|^\s*(pip3?|python3? -m pip)\s+install\b")
GATES_BLOCK = re.compile(r"^```gates[ \t]*\n(.*?)^```", re.M | re.S)
DECLARED = (f"{WORKFLOWS}/", "AGENTS.md", ".agent/gates.json", ".nvmrc", ".node-version", ".tool-versions")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "gate"


def base_has(root: Path, base: str) -> bool:
    try:
        rev_parse(root, f"{base}^{{commit}}")
    except GitError:
        return False
    return True


def read_at(root: Path, ref: str | None, path: str) -> str | None:
    """A file's text at `ref`, or in the working tree when `ref` is None; None when absent."""
    try:
        return blob_at(root, f"{ref}:{path}") if ref else (root / path).read_text(encoding="utf-8")
    except (GitError, OSError):
        return None


def declared_paths(root: Path, ref: str | None) -> list[str]:
    """The workflow files at `ref` (or in the tree) plus the single-file declarations."""
    if ref:
        try:
            names = output(root, ["ls-tree", "-r", "--name-only", ref, "--", WORKFLOWS]).split()
        except GitError:
            names = []
    else:
        names = [str(p.relative_to(root)) for p in sorted((root / WORKFLOWS).glob("*.y*ml"))]
    return [n for n in names if n.endswith((".yml", ".yaml"))] + list(DECLARED[1:])


def head_changed(root: Path, base: str) -> bool:
    """True when any declaration file differs between the base and HEAD (the PR head)."""
    names = set(declared_paths(root, base)) | set(declared_paths(root, "HEAD"))
    return any(read_at(root, base, n) != read_at(root, "HEAD", n) for n in names)


def drop_setup(command: str) -> str:
    """The command without its leading setup lines; empty when every line is setup (`npm ci && npm test` is not)."""
    lines = command.splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#") or is_setup(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip() if any(l.strip() and not l.lstrip().startswith("#") for l in lines) else ""


def is_setup(line: str) -> bool:
    parts = [part for part in re.split(r"&&|;", line) if part.strip()]
    return bool(parts) and all(SETUP.match(part) for part in parts)


def clean_env(*maps: object) -> dict[str, str]:
    """Merged env maps, dropping any value that needs a `${{ }}` expression to resolve."""
    merged: dict[str, str] = {}
    for item in maps:
        if isinstance(item, dict):
            merged.update({k: v for k, v in item.items() if isinstance(v, str) and "${{" not in v})
    return merged


def step_gate(job_id: str, job: dict, step: dict, top: dict, index: int) -> tuple[dict | None, str]:
    """`(gate, "")` for a `run:` step, or `(None, reason)` when it cannot be mirrored."""
    command = str(step["run"]).strip()
    name = slug(str(step.get("name") or f"{job_id}-{index}"))
    command = drop_setup(command)
    if not command:
        return None, f"{name}: setup step"
    if publishes(command):
        return None, f"{name}: runs a publish or deploy command, not mirrored"
    if step.get("if") or "${{" in command:
        return None, f"{name}: has an if: or a ${{{{ }}}} expression"
    defaults = ((job.get("defaults") or {}).get("run") or {}) if isinstance(job.get("defaults"), dict) else {}
    cwd = step.get("working-directory") or defaults.get("working-directory") or ""
    return {"name": name, "job": job_id, "command": command, "cwd": cwd,
            "env": clean_env(top.get("env"), job.get("env"), step.get("env"))}, ""


def workflow_gates(texts: dict[str, str]) -> tuple[list[dict], list[str]]:
    """The mirrored gates of every CI workflow, in file, job and step order, plus what was skipped."""
    gates: list[dict] = []
    skipped: list[str] = []
    for path in sorted(texts):
        doc = parse(texts[path])
        if not is_ci(doc) or not isinstance(doc.get("jobs"), dict):
            skipped.append(not_mirrored(path, doc))
            continue
        for job_id, job in doc["jobs"].items():
            steps = job.get("steps") if isinstance(job, dict) else None
            if isinstance(job, dict) and job.get("environment"):
                skipped.append(f"{job_id}: job with environment: (deployment), not mirrored")
                continue
            if isinstance(job, dict) and job_if(job_id, job):
                skipped.append(job_if(job_id, job))
                continue
            for index, step in enumerate(steps if isinstance(steps, list) else []):
                if isinstance(step, dict) and "uses" in step:
                    skipped.append(f"uses: {step['uses']}")
                if not isinstance(step, dict) or "run" not in step:
                    continue
                gate, reason = step_gate(job_id, job, step, doc, index)
                if gate is None:
                    skipped.append(reason)
                    continue
                gate["workflow"] = path
                gates.append(gate)
    return unique(gates), skipped


def unique(gates: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for gate in gates:
        seen[gate["name"]] = seen.get(gate["name"], 0) + 1
        if seen[gate["name"]] > 1:
            gate["name"] = f"{gate['name']}-{seen[gate['name']]}"
    return gates


def block_gates(text: str) -> list[dict]:
    """Gates from the fenced `gates` block of AGENTS.md."""
    found = GATES_BLOCK.search(text)
    gates: list[dict] = []
    shared: dict[str, str] = {}
    for line in (found.group(1).splitlines() if found else []):
        name, _, command = line.partition(":")
        if not command.strip():
            continue
        if name.strip() == "env" and "=" in command:
            key, _, value = command.strip().partition("=")
            shared[key.strip()] = value.strip()
        else:
            gates.append({"name": slug(name), "job": "", "command": command.strip(), "cwd": "", "env": shared})
    return gates


def override_gates(text: str) -> list[dict]:
    """Gates from `.agent/gates.json`: `{"schema_version": 1, "env": {}, "gates": [{name, command, env}]}`."""
    try:
        payload = json.loads(text)
        shared = clean_env(payload.get("env"))
        return [{"name": slug(str(g["name"])), "job": "", "command": str(g["command"]),
                 "cwd": str(g.get("cwd") or ""), "env": {**shared, **clean_env(g.get("env"))}}
                for g in payload["gates"]]
    except (ValueError, KeyError, TypeError, AttributeError):
        return []


