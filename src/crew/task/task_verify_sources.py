"""Which gates a verify run has, read from the BASE branch, and what it must never mirror.

Order of trust: GitHub Actions `run:` steps from the base ref; then the `AGENTS.md` gates block;
`.agent/gates.json` may only add. Setup and `if:` steps are skipped and listed; a release workflow or
publish command is never mirrored and makes the run partial. With no runnable gate, prose checks from
the nearest `AGENTS.md` are surfaced for the builder, never run; unreadable CI (Buildkite) is named.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from crew.lib.git import GitError, blob_at, output, rev_parse
from crew.lib.markdown import FENCED, fenced_blocks
from crew.task.task_guidance import guidance_paths
from crew.task.task_verify_env import node_pin

CI_FILES = {
    ".buildkite": "buildkite",
    ".circleci": "circleci",
    ".gitlab-ci.yml": "gitlab",
    "Jenkinsfile": "jenkins",
    ".travis.yml": "travis",
    "azure-pipelines.yml": "azure",
    "bitbucket-pipelines.yml": "bitbucket",
    ".drone.yml": "drone",
}
RUNNERS = (
    "node",
    "npm",
    "npx",
    "yarn",
    "pnpm",
    "bun",
    "make",
    "python",
    "python3",
    "pytest",
    "tox",
    "nox",
    "cargo",
    "go",
    "mvn",
    "gradle",
    "bash",
    "sh",
    "bundle",
    "rake",
    "dotnet",
    "uv",
    "poetry",
)
KEYWORDS = ("check", "test", "lint", "type", "verify", "format", "fmt", "ci", "jest", "eslint", "tsc")

INLINE = re.compile(r"`([^`\n]+)`")
LIMIT = 20


def unreadable_ci(root: Path, ref: str | None) -> list[str]:
    """Names of CI systems the repo declares at the top level that no reader here understands."""
    try:
        names = output(root, ["ls-tree", "--name-only", ref]).split("\n") if ref else [p.name for p in root.iterdir()]
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
    fenced = [line for tag, body in FENCED.findall(text) if tag.strip() != "gates" for line in body.splitlines()]
    inline = INLINE.findall(FENCED.sub("", text))
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


def prose_checks(root: Path, ref: str | None) -> list[dict]:
    """`{command, from}` for the nearest AGENTS.md of each touched path (the root's when nothing is touched).

    The resolver is `crew-agent-context.py`'s (`task_guidance.guidance_paths`), the one the builder's guidance
    comes from."""
    resolve = guidance_paths
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


WORKFLOWS = ".github/workflows"
SETUP = re.compile(r"^\s*(npm|pnpm|yarn|bun)\s+(ci|install|i)\b|^\s*(pip3?|python3? -m pip)\s+install\b")
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
    return {"name": name, "job": job_id, "command": command, "cwd": cwd, "env": clean_env(top.get("env"), job.get("env"), step.get("env"))}, ""


def workflow(text: str) -> dict:
    """A workflow as nested dicts, lists and strings, every scalar as written (`3.10` stays `3.10`); {} when unreadable."""
    try:
        doc = yaml.load(text, Loader=yaml.BaseLoader)  # noqa: S506  (BaseLoader builds strings only)
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def workflow_gates(texts: dict[str, str]) -> tuple[list[dict], list[str]]:
    """The mirrored gates of every CI workflow, in file, job and step order, plus what was skipped."""
    gates: list[dict] = []
    skipped: list[str] = []
    for path in sorted(texts):
        doc = workflow(texts[path])
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
    found = fenced_blocks(text, "gates")
    gates: list[dict] = []
    shared: dict[str, str] = {}
    for line in found[0].splitlines() if found else []:
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
        return [
            {
                "name": slug(str(g["name"])),
                "job": "",
                "command": str(g["command"]),
                "cwd": str(g.get("cwd") or ""),
                "env": {**shared, **clean_env(g.get("env"))},
            }
            for g in payload["gates"]
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        return []


def resolve(root: Path, base: str | None) -> dict:
    """`{source, gates, skipped, pin, notes, ci_unreadable, prose_checks}` from the base ref (or the tree)."""
    notes: list[str] = []
    ref = base if base and base_has(root, base) else None
    if base and ref is None:
        notes.append(f"base {base} not found, reading the working tree")
    elif ref and head_changed(root, ref):
        notes.append("declaration changed in PR head, using base")
    where = f"@{ref}" if ref else " (working tree)"
    texts = {p: read_at(root, ref, p) or "" for p in declared_paths(root, ref) if p.startswith(WORKFLOWS)}
    extra = override_gates(read_at(root, ref, ".agent/gates.json") or "")
    gates, skipped = workflow_gates(texts)
    source, unreadable = f"ci-workflow {WORKFLOWS}{where}", []
    if not gates:
        unreadable = unreadable_ci(root, ref)
        notes += [f"CI not readable here ({name})" for name in unreadable]
        gates = block_gates(read_at(root, ref, "AGENTS.md") or "")
        source = f"AGENTS.md gates block{where}" if gates else "none"
    if gates and extra:
        added, drift = merge_extra(gates, extra)
        notes.extend(drift)
        if added:
            gates, source = gates + added, f"{source} + .agent/gates.json additions{where}"
    elif extra:
        gates, source = extra, f".agent/gates.json only{where}"
    source_pin, required = node_pin(lambda path: read_at(root, ref, path))
    return {
        "source": source,
        "gates": gates,
        "skipped": skipped,
        "notes": notes,
        "ci_unreadable": unreadable,
        "pin": {"source": source_pin, "required": required},
        "prose_checks": [] if gates else prose_checks(root, ref),
    }


def merge_extra(gates: list[dict], extra: list[dict]) -> tuple[list[dict], list[str]]:
    """gates.json may ADD gates; it never removes or changes one: a clash keeps the CI command and warns."""
    known = {g["name"]: g for g in gates}
    added: list[dict] = []
    warnings: list[str] = []
    for gate in extra:
        current = known.get(gate["name"])
        if current is None:
            added.append(gate)
        elif current["command"] != gate["command"]:
            warnings.append(
                f"warning: gate {gate['name']}: .agent/gates.json redefines the command CI runs (CI: {current['command']!r}; gates.json: {gate['command']!r}); using CI"
            )
    return added, warnings


DANGEROUS = {"pull_request_target", "workflow_run", "release"}
PUBLISH = re.compile(
    r"^(?:\w+=\S*\s+)*(?:sudo\s+)?(?:(?:npm|pnpm)\s+publish|yarn\s+(?:npm\s+)?publish|docker\s+push"
    r"|gh\s+release\s+(?:create|upload|edit)|twine\s+upload|cargo\s+publish|gem\s+push|git\s+push)\b"
)


def trigger_map(doc: dict) -> dict[str, object]:
    """`{event: filter}` of a workflow's `on:`, written as a string, a list or a map (and the YAML 1.1 `True` key)."""
    on = doc.get("on", doc.get(True))
    if isinstance(on, dict):
        return {str(key): value for key, value in on.items()}
    if isinstance(on, list):
        return {str(item): None for item in on}
    return {part.strip(): None for part in str(on or "").strip("[] ").split(",") if part.strip()}


def tags_only(value: object) -> bool:
    """True for a `push` filter that names `tags` and no branch filter: it runs on a release tag."""
    return isinstance(value, dict) and ("tags" in value or "tags-ignore" in value) and not ({"branches", "branches-ignore"} & set(value))


def is_ci(doc: dict) -> bool:
    """True when push (not tags-only) or pull_request is present and no dangerous event is."""
    found = trigger_map(doc)
    if DANGEROUS & set(found):
        return False
    return "pull_request" in found or ("push" in found and not tags_only(found["push"]))


def has_ci_trigger(doc: dict) -> bool:
    """True when the workflow runs on `push` or `pull_request` at all; without either it is not CI."""
    return bool({"push", "pull_request"} & set(trigger_map(doc)))


def not_mirrored(path: str, doc: dict) -> str:
    """The skipped entry of a workflow left out: `not CI` when it has no CI trigger, else `workflow not mirrored`."""
    kind = "workflow not mirrored" if has_ci_trigger(doc) else "not CI"
    return f"{path}: {kind} (on: {', '.join(trigger_map(doc)) or 'none'})"


def job_if(job_id: str, job: dict) -> str:
    """The skipped entry of a job gated by a job-level `if:`, or ''."""
    return f"{job_id}: job with an if:, not mirrored" if job.get("if") else ""


def publishes(command: str) -> bool:
    """True when any line or any `&&`, `;`, `||` segment of the command starts a publish or deploy command."""
    return any(PUBLISH.match(part.strip()) for line in command.splitlines() for part in re.split(r"&&|\|\||;", line))
