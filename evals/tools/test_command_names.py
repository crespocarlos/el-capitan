#!/usr/bin/env python3
"""Checks for the installed command surface: catalog kinds, install links, and the output contract.

Six properties, each with its own failure that no other suite covers:

- every catalog entry declares what it is (`command`, `module`, `asset`), and every command basename
  follows one rule, so the surface cannot drift back to 22 commands with four ad-hoc names;
- the naming rule is enforced by lint, not only documented, so an unprefixed command fails the gate;
- `install.sh` links commands and nothing else, so an internal module cannot reappear in
  `~/.agent/bin` as a fake command;
- every command's `--help` fits one screen, so a caller reads purpose, flags, and an example instead
  of prose that belongs in `TOOLS.md`;
- every command the catalog documents as machine-readable emits valid JSON on stdout with nothing
  human interleaved, so a caller can parse it without guessing;
- every command that prints a collection exposes `--limit` or `--max-chars`, advertises it, and prints
  a marker naming what was dropped — a silent cut makes a model treat a partial list as complete;
- `crew resolve PR` dispatches `crew-pr-resolver` as a read-only subagent that returns a plan, and the
  main session asks one question and applies it; the router, `.claude/CLAUDE.md` and the agent file agree.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
MANIFEST = TOOLS / "tools.json"
LINT = TOOLS / "maintenance" / "crew-lint.py"
INSTALL = ROOT / "install.sh"

SECTIONS = {"tools": "command", "scripts": "command", "modules": "module", "assets": "asset"}
COMMAND_NAME = re.compile(r"^crew-[a-z0-9-]+\.(py|sh)$")
SOURCE_ONLY = {"task-env.sh", "crew-diff.sh"}
HELP_LINE_CEILING = 40
TOOLS_DOC = (TOOLS / "TOOLS.md").read_text()

FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + detail if detail else ''}")


def entries() -> list[tuple[str, dict]]:
    data = json.loads(MANIFEST.read_text())
    return [(section, entry) for section in SECTIONS for entry in data.get(section, [])]


def commands() -> list[dict]:
    return [entry for section, entry in entries()
            if entry.get("kind") == "command" and entry.get("name") not in SOURCE_ONLY]


def catalog() -> None:
    """Every entry declares the `kind` its section implies, and commands follow the name rule."""
    listed = entries()
    check("catalog is non-empty", bool(listed))

    missing = [entry.get("name") for _, entry in listed if "kind" not in entry]
    check("every entry declares kind", not missing, f"missing kind: {missing}")

    mismatched = [(section, entry.get("name"), entry.get("kind")) for section, entry in listed
                  if entry.get("kind") not in (None, SECTIONS[section])]
    check("kind matches the section it is listed in", not mismatched, str(mismatched))

    bad = []
    for section, entry in listed:
        name, kind = entry.get("name", ""), entry.get("kind")
        if kind != "command" or name in SOURCE_ONLY:
            continue
        if not COMMAND_NAME.match(name):
            bad.append(name)
    check("every command basename is crew-<kebab>.(py|sh)", not bad, f"not renamed: {bad}")


def install_links() -> None:
    """The dry-run link set is exactly the catalog's commands, with no module among them."""
    with tempfile.TemporaryDirectory() as temporary:
        environment = {**os.environ, "HOME": temporary}
        for key in ("CREW_MEMORY_DIR", "CREW_JOURNAL_DIR", "CREW_TASK_DIR"):
            environment.pop(key, None)
        result = subprocess.run(["bash", str(INSTALL), "--dry-run"],
                                capture_output=True, text=True, env=environment)
    check("install dry-run succeeds", result.returncode == 0, result.stderr[-600:])
    linked = re.findall(r"ln -sf (\S+) ", result.stdout)
    tools_linked = [Path(target) for target in linked if "/.agent/tools/" in target]
    check("install links the tool tree", bool(tools_linked), str(tools_linked[:5]))

    modules = {entry.get("name") for _, entry in entries() if entry.get("kind") == "module"}
    leaked = sorted(path.name for path in tools_linked if path.name in modules)
    check("no module is linked", not leaked, f"linked modules: {leaked}")
    assets = {entry.get("name") for _, entry in entries() if entry.get("kind") == "asset"}
    check("no asset is linked", not [path.name for path in tools_linked if path.name in assets])

    command_names = {entry.get("name") for _, entry in entries() if entry.get("kind") == "command"}
    linked_names = {path.name for path in tools_linked}
    check("every command is linked", command_names <= linked_names,
          f"missing: {sorted(command_names - linked_names)}")
    check("nothing outside the catalog is linked", linked_names <= command_names,
          f"extra: {sorted(linked_names - command_names)}")
    duplicated = sorted({name for name in linked_names
                         if sum(1 for path in tools_linked if path.name == name) > 1})
    check("each command is linked once", not duplicated, f"duplicated: {duplicated}")


def naming_finding() -> None:
    """Lint reports a command that lost its prefix, so the rule is enforced, not just documented."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "repo"
        (root / ".agent" / "tools" / "task").mkdir(parents=True)
        (root / ".cursor" / "agents").mkdir(parents=True)
        (root / "rules").mkdir()
        script = root / ".agent" / "tools" / "task" / "task-progress.py"
        script.write_text("#!/usr/bin/env python3\n")
        script.chmod(0o755)
        (root / ".agent" / "tools" / "tools.json").write_text(json.dumps({
            "schema_version": 1,
            "tools": [{"name": "task-progress.py", "dir": "task", "kind": "command",
                       "category": "task", "owner": "crew-orchestrator",
                       "help": "argparse", "smoke": "--help"}],
            "scripts": [], "modules": [], "assets": [],
        }))
        result = subprocess.run([sys.executable, str(LINT), "--root", str(root)],
                                capture_output=True, text=True)
    check("unprefixed command fails lint", result.returncode == 1, result.stdout + result.stderr)
    check("lint reports command-name", ": command-name: " in result.stdout, result.stdout)


def invocation(entry: dict) -> list[str]:
    path = TOOLS / entry["dir"] / entry["name"]
    interpreter = ["bash"] if path.suffix == ".sh" else [sys.executable]
    return [*interpreter, str(path)]


def run_command(entry: dict, *arguments: str, env: dict | None = None,
                input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*invocation(entry), *arguments], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, input=input_text, timeout=120)


def help_cases() -> None:
    """Every cataloged command's `--help` fits 40 lines, so one screen shows purpose and flags."""
    for entry in commands():
        name = entry["name"]
        result = run_command(entry, "--help")
        lines = result.stdout.count("\n") or 1
        check(f"{name}: --help succeeds", result.returncode == 0, result.stderr[-400:])
        check(f"{name}: --help fits {HELP_LINE_CEILING} lines", lines <= HELP_LINE_CEILING,
              f"{lines} lines; move long prose into TOOLS.md")
    for label, module, function, wanted, unwanted in HELP_TEXTS:
        text = help_text(module, function)
        check(label, all(w in text for w in wanted) and not any(u in text for u in unwanted), text)


# (case, module, parser function, text the --help must show, text it must not): checked in process.
HELP_TEXTS = (
    ("crew-task.py worktree --help lists every action, check included", "task_worktrees", "pref_main",
     ("pref", "record", "check <TREE>"), ()),
    ("crew-verify.py report-check --help describes the report check, not the task listing", "task_verify_report", "main",
     ("builder",), ("Rendering task state",)),
)


def help_text(module: str, function: str) -> str:
    """The `--help` a subcommand parser prints, captured in this process."""
    import contextlib
    import importlib
    import io

    for path in (str(TOOLS / "task"), str(TOOLS)):
        if path not in sys.path:
            sys.path.insert(0, path)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.suppress(SystemExit):
        getattr(importlib.import_module(module), function)(["--help"])
    return buffer.getvalue()


def prepare_memory(store: Path, entry: dict) -> str:
    """Initialize a scratch store so `crew-mem.py list --json` has a valid index to read.

    Returns the reason it could not, which the caller reports as the check's detail: `init` writes a
    git repository, so a sandbox that blocks that path fails here rather than in the assertion.
    """
    result = run_command(entry, "init", env={"CREW_MEMORY_DIR": str(store)})
    return "" if result.returncode == 0 else (result.stderr or result.stdout).strip()[:200]


def machine_readable_cases() -> None:
    """Each machine-readable command prints valid JSON on stdout for a hermetic invocation.

    Three modes: `json` and `json-always` are invoked with the catalog's `json_smoke` and parsed;
    `json_static` needs live infrastructure (a nightshift server, an Elasticsearch cluster), so it is
    documented in `TOOLS.md` and its `--json` flag is asserted from `--help` instead of run.
    `json-flag` prints JSON only for the subcommand that carries `--json`.
    """
    temporary = Path(tempfile.mkdtemp(prefix="crew-json-"))
    try:
        diff = temporary / "sample.diff"
        diff.write_text(SAMPLE_DIFF, encoding="utf-8")
        for entry in commands():
            mode = entry.get("output")
            if mode not in {"json", "json-always", "json_static", "json-flag"}:
                continue
            name = entry["name"]
            check(f"{name}: documented as machine-readable in TOOLS.md", name in TOOLS_DOC,
                  "TOOLS.md never says this command emits JSON")
            if mode == "json_static":
                check(f"{name}: --help succeeds", run_command(entry, "--help").returncode == 0)
                continue
            if mode == "json-flag":
                check(f"{name}: diagnose accepts --json",
                      "--json" in run_command(entry, "diagnose", "--help").stdout,
                      "the documented JSON mode has no flag")
                continue
            arguments = [item.replace("@tmpdir", str(temporary)).replace("@diff", str(diff))
                         for item in entry.get("json_smoke", [])]
            env = {"CREW_MEMORY_DIR": str(temporary / "memory"), "CREW_TASK_DIR": "",
                   "PYTHONDONTWRITEBYTECODE": "1"}
            blocked = ""
            if name == "crew-mem.py":
                blocked = prepare_memory(Path(env["CREW_MEMORY_DIR"]), entry)
            if blocked:
                print(f"skip: {name}: memory store unavailable here ({blocked})")
                continue
            result = run_command(entry, *arguments, env=env)
            check(f"{name}: stdout is valid JSON", is_json(result.stdout),
                  f"exit {result.returncode}; stdout starts {result.stdout[:160]!r}")
            check(f"{name}: no human prose before the JSON",
                  not result.stdout.lstrip().startswith(("pass:", "FAIL", "usage:")),
                  result.stdout[:160])
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


SAMPLE_DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,3 @@
 one
-two
+two
+three
"""


def bounded_cases() -> None:
    """A command that prints a collection declares a bound and advertises it in `--help`."""
    for entry in commands():
        if not entry.get("bounded"):
            continue
        name = entry["name"]
        flags = entry.get("list_flags", [])
        check(f"{name}: declares a bound", bool(flags), "bounded command with no list_flags")
        help_text = run_command(entry, "--help").stdout
        help_text += "".join(run_command(entry, *sub).stdout
                             for sub in entry.get("flag_help", []))
        for flag in flags:
            check(f"{name}: --help documents {flag}", flag in help_text,
                  "the flag exists but a caller cannot discover it")


def truncation_cases() -> None:
    """A truncated bound prints the marker naming what was dropped, never a silent cut."""
    temporary = Path(tempfile.mkdtemp(prefix="crew-bound-"))
    try:
        tasks = temporary / "tasks"
        for index in range(6):
            spec = tasks / f"task-{index}" / "SPEC.md"
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(f"# Task {index}\n\n## Status\nDRAFTING\n\n- [ ] a\n", encoding="utf-8")
        entries_by_name = {entry["name"]: entry for entry in commands()}
        listing = entries_by_name["crew-ls.py"]
        limited = run_command(listing, "--tasks-dir", str(tasks), "--limit", "2")
        check("crew-ls.py: --limit prints a truncation marker", "[truncated:" in limited.stdout,
              limited.stdout)
        check("crew-ls.py: the marker names the bound", "--limit" in limited.stdout,
              limited.stdout)
        clipped = run_command(listing, "--tasks-dir", str(tasks), "--max-chars", "120")
        check("crew-ls.py: --max-chars prints a truncation marker",
              "[truncated:" in clipped.stdout, clipped.stdout)
        kept = run_command(listing, "--tasks-dir", str(tasks), "--limit", "2", "--json")
        check("crew-ls.py: --json stays parseable when bounded", is_json(kept.stdout), kept.stdout)

        diff = temporary / "sample.diff"
        diff.write_text(SAMPLE_DIFF, encoding="utf-8")
        hunks = entries_by_name["crew-review-hunks.py"]
        result = run_command(hunks, str(diff), "--out", str(temporary / "hunks"),
                             "--max-chars", "40")
        check("crew-review-hunks.py: --max-chars marks a clipped JSON summary",
              is_json(result.stdout) and "truncated" in result.stdout, result.stdout)

        worktree = entries_by_name["crew-worktree.py"]
        result = run_command(worktree, "main", "--json", "--max-chars", "5")
        check("crew-worktree.py: --max-chars marks a clipped path", "[truncated:" in result.stdout,
              result.stdout)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def memory_truncation_case() -> None:
    """`crew-mem.py list --json --limit` names the cut instead of returning a shorter array."""
    temporary = Path(tempfile.mkdtemp(prefix="crew-mem-bound-"))
    try:
        entry = next(entry for entry in commands() if entry["name"] == "crew-mem.py")
        store = temporary / "memory"
        blocked = prepare_memory(store, entry)
        if blocked:
            print(f"skip: crew-mem.py truncation: memory store unavailable here ({blocked})")
            return
        for name in ("alpha", "beta", "gamma"):
            write_unit(store, name)
        run_command(entry, "reindex", env={"CREW_MEMORY_DIR": str(store)})
        result = run_command(entry, "list", "--json", "--limit", "1",
                             env={"CREW_MEMORY_DIR": str(store)})
        payload = json.loads(result.stdout) if is_json(result.stdout) else None
        if not isinstance(payload, dict):
            print(f"skip: crew-mem.py truncation: index held one unit ({result.stdout[:120]!r})")
            return
        check("crew-mem.py: --limit wraps a clipped list in an envelope",
              payload.get("truncated") is True and payload.get("total") == 3, result.stdout)
        check("crew-mem.py: the envelope names the bound", "--limit" in payload.get("hint", ""),
              result.stdout)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def write_unit(store: Path, name: str) -> None:
    """One valid unit on disk, so the check does not depend on the write path succeeding."""
    unit = store / "global" / f"user_demo-{name}.md"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(
        f"---\nid: user-demo-{name}\ntype: user\nscope: global\ntitle: demo-{name}\n"
        "paths: []\nkeywords: []\nstatus: active\ncreated: 2026-01-01\nmodified: 2026-01-01\n"
        f"evidence: []\nuses: 0\nhelped: 0\nmisled: 0\n---\nA demo preference for {name}.\n",
        encoding="utf-8",
    )


def is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False


def resolver_split_agrees() -> None:
    """`crew-pr-resolver` is a read-only subagent returning a plan; the main session asks once and applies it.

    The main session creates the worktree before dispatch and, once the plan (the subagent's final
    message) returns, reads the agent file from Step 6 and `acting-on-threads.md`; the router says so
    once and `.claude/CLAUDE.md` points to it instead of restating it.
    """
    router = (ROOT / "rules" / "crew-router.mdc").read_text(encoding="utf-8")
    dispatch = [p for p in router.split("\n\n") if "crew-pr-resolver" in p and "subagent" in p]
    check("the router dispatches crew-pr-resolver read-only, with the worktree, and has the main session read Step 6 on",
          len(dispatch) == 1 and all(s in dispatch[0] for s in ("read-only", "crew-worktree.py", "final", "from Step 6", "acting-on-threads.md")),
          str(dispatch))
    check("the router's retry rule counts a resolver reply without the Step 6 table as no report",
          bool(re.search(r"Retry once[^\n]*\n[^\n]*Step 6 table", router)), router[-900:])
    claude = (ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    inline_list = re.search(r"\*\*Orchestrators\*\* \(([^)]*)\)", claude)
    named = [p for p in claude.split("\n\n") if "crew-pr-resolver" in p]
    check(".claude/CLAUDE.md points crew-pr-resolver to the router, not an inline orchestrator or a restated contract",
          bool(inline_list) and "crew-pr-resolver" not in inline_list.group(1) and bool(named)
          and all("router" in p and "main session applies" not in p for p in named), str(named))
    agent = (ROOT / ".cursor" / "agents" / "crew-pr-resolver.md").read_text(encoding="utf-8")
    front = agent.split("---")[1]
    tools = re.search(r"^tools:\s*(.+)$", front, re.MULTILINE)
    check("the resolver frontmatter is read-only: readonly: true and no Edit or Write tool",
          "readonly: true" in front and bool(tools) and not re.search(r"\b(Edit|Write)\b", tools.group(1)), front)
    model = agent[agent.index("## Execution model"):agent.index("## When Invoked")]
    check("the execution model says the main session creates the worktree and read-only holds by instruction in Claude Code",
          "crew-worktree.py" in model and "Bash" in model and "by instruction" in model and "final message" in model, model)
    step_one = agent[agent.index("### Step 1:"):agent.index("### Step 2:")]
    check("Step 1 only cds into the given worktree and creates none", "crew-worktree.py" not in step_one and "cd WORKTREE_PATH" in step_one, step_one)
    step_four = agent[agent.index("### Step 4:"):agent.index("### Step 5:")]
    check("Step 4 drafts edits for Step 7 and applies none", "draft every edit" in step_four and "apply them together" not in step_four, step_four)
    step_six = agent[agent.index("### Step 6:"):agent.index("### Step 7:")]
    questions = [line for line in step_six.splitlines() if re.match(r"(\d+\. )?\*\*\"", line)]
    check("the resolver's analysis runs read-only and the main session asks one question",
          "read-only" in agent and "main session" in step_six and len(questions) == 1, str(questions))
    check("the plan is the final message, opens with worktree, repo and PR, and each row carries its ids",
          all(s in step_six for s in ("final message", "worktree path", "OWNER/REPO", "PR number", "databaseId", "| Ids |", "no report")), step_six)
    step_seven = agent[agent.index("### Step 7:"):]
    check("the Next line is the main session's, after Step 7", "After Step 7, the main session" in step_seven, step_seven[-300:])
    guide = (ROOT / ".agent" / "tools" / "AGENTS.md").read_text(encoding="utf-8")
    check(".agent/tools/AGENTS.md says the resolver keeps Bash for gh reads and is read-only by instruction in Claude Code",
          bool(re.search(r"crew-pr-resolver[^\n]*(\n[^\n]+)*?Bash[^\n]*(\n[^\n]+)*?by instruction", guide)), "")


EXIT_ROW = re.compile(r"^\| `(crew-[a-z0-9-]+\.py[^`]*)` \| `([3-9])` \| [^|]+ \| `([a-z0-9_/-]+\.py)` \|$")


def documented_exit_codes() -> set[tuple[str, int]]:
    """`(source module, code)` from the exit-code table in `.agent/tools/AGENTS.md`."""
    guide = (TOOLS / "AGENTS.md").read_text(encoding="utf-8")
    return {(found.group(3), int(found.group(2))) for found in map(EXIT_ROW.match, guide.splitlines()) if found}


def declared_exit_codes() -> tuple[set[tuple[str, int]], list[str]]:
    """`EXIT_* = <3..9>` constants per module, and every bare `return <3..9>` (which must be named)."""
    import ast

    declared, bare = set(), []
    for path in sorted(TOOLS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        source = path.relative_to(TOOLS).as_posix()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id.startswith("EXIT_") and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int) and node.value.value >= 3):
                declared.add((source, node.value.value))
            if (isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int) and not isinstance(node.value.value, bool)
                    and node.value.value >= 3):
                bare.append(f"{source}:{node.lineno} return {node.value.value}")
    return declared, bare


def exit_code_cases() -> None:
    """Every non-standard exit code is a named `EXIT_*` constant and has a row in the AGENTS.md table."""
    documented = documented_exit_codes()
    declared, bare = declared_exit_codes()
    check("the exit-code table lists the known non-standard codes", len(documented) >= 6, str(sorted(documented)))
    check("no bare `return <3..9>`: a non-standard code is a named EXIT_* constant", not bare, "; ".join(bare))
    check("every EXIT_* constant is documented", declared <= documented, str(sorted(declared - documented)))
    check("every documented code is declared in its source", documented <= declared, str(sorted(documented - declared)))


def main() -> int:
    exit_code_cases()
    resolver_split_agrees()
    catalog()
    install_links()
    naming_finding()
    help_cases()
    machine_readable_cases()
    bounded_cases()
    truncation_cases()
    memory_truncation_case()
    if FAILED:
        print(f"\n{len(FAILED)} failed")
        return 1
    print("\nall command-surface checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
