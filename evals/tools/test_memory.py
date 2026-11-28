#!/usr/bin/env python3
"""Memory: session telemetry, the capture review that reaches a human, the inbox, and the scope key.

The telemetry and capture hooks run for real against a throwaway memory root, so the guard/queue
ordering is observed rather than assumed: the review is queued before the guard is written, and a
session that was asked once stays silent. `crew-inbox.py` is the read side. `repo_key` is the memory
scope a checkout resolves to; a key that changes orphans every unit stored under the old one, and
`crew-repo-info.py --field repo_name` must give the same name, because recall scopes by it.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest
from harness_hook import run as run_hook

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "src" / "crew" / "memory" / "crew_inbox.py"
# Both harness shapes, with quotes and non-ASCII in the command and the session id.
TELEMETRY = (
    {"session_id": "claude-✓", "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": 'echo "quotes" é→✓'}},
    {"conversation_id": "cursor-✓", "hook_event_name": "postToolUse", "command": 'echo "quotes" é→✓'},
)
# (case, origin URL or None, the key repo_key must return for a checkout named "checkout")
KEYS = (
    ("https remote", "https://github.com/acme/gadgets.git", "gadgets"),
    ("scp remote", "git@github.com:acme/gizmos.git", "gizmos"),
    ("ssh:// remote", "ssh://git@github.com/acme/sprockets.git", "sprockets"),
    ("ssh-alias remote (no user)", "github-work:acme/cogs.git", "cogs"),
    ("git:// remote", "git://github.com/acme/levers", "levers"),
    ("local-path remote", "/srv/git/widgets.git", "widgets"),
    ("file:// remote", "file:///srv/git/tools.git", "tools"),
    ("no remote", None, "checkout"),
)
DRAFT = ("---\nid: procedure-{id}\ntype: procedure\nscope: global\ntitle: {title}\n"
         "status: active\ncreated: 2026-01-01\nmodified: 2026-01-01\nevidence: [x]\n---\nBody.\n")


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def store(root: Path) -> Path:
    (root / ".inbox").mkdir(parents=True)
    (root / ".sessions").mkdir(parents=True)
    return root


def hook(name: str, root: Path, payload: dict) -> tuple[int, dict]:
    """The payload through crew-hook.py in a throwaway HOME (`name` is the rule the event reaches)."""
    result = run_hook(root.parent / f"home-{name}", payload, env={"CREW_MEMORY_DIR": str(root)})
    try:
        return result.returncode, json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return result.returncode, {"<unparsed>": result.stdout[:200]}


def hashed(session_id: str) -> str:
    """The name both hooks give a session's files: the raw id is never written."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:24]


def queue(root: Path) -> list[dict]:
    path = root / ".sessions" / "review-queue.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def inbox(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(INBOX), *arguments], capture_output=True, text=True,
                          env={**os.environ, "CREW_MEMORY_DIR": str(root)})


def test_telemetry_and_capture_prompt(tmp: Path) -> None:
    """log-tool-use records both shapes; its session name is the one the capture hook reads."""
    root = store(tmp)
    for payload in TELEMETRY:
        code, body = hook("log-tool-use.sh", root, payload)
        check(f"log-tool-use answers {{}} for {payload['hook_event_name']}", (code, body) == (0, {}), (code, body))
    records = [json.loads(line) for path in (root / ".sessions").glob("*.jsonl") for line in path.read_text().splitlines()]
    check("each record carries event, action and target", len(records) == 2 and all(r["event"] and r["action"] and r["target"] for r in records), records)
    for _ in range(2):
        hook("log-tool-use.sh", root, {"session_id": "s-edit", "hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": "/x/a.py"}})
    code, body = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "s-edit"})
    check("a session with edits returns a followup", body.get("decision") == "block" and body.get("reason"), body)
    check("the review is queued before the guard is written",
          len(queue(root)) == 1 and (root / ".sessions" / f"{hashed('s-edit')}.memory-prompted").is_file(), queue(root))
    code, again = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "s-edit"})
    check("a second stop is silent and queues nothing", again == {} and len(queue(root)) == 1, (again, queue(root)))
    code, body = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "no-events"})
    check("a session with no telemetry says nothing", body == {}, body)
    (root / ".sessions" / f"{hashed('quiet')}.jsonl").write_text('{"action": "read", "failure": false}\n', encoding="utf-8")
    code, body = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "quiet"})
    check("a read-only session says nothing, queues nothing and writes no guard",
          body == {} and len(queue(root)) == 1 and not (root / ".sessions" / f"{hashed('quiet')}.memory-prompted").exists(), body)


def test_inbox(tmp: Path) -> None:
    root = store(tmp)
    empty = inbox(root)
    check("an empty inbox says so and exits 0", (empty.returncode, empty.stdout.strip()) == (0, "inbox: empty"), empty.stdout)
    (root / ".inbox" / "procedure-probe.md").write_text(DRAFT.format(id="probe", title="Probe draft"), encoding="utf-8")
    (root / ".sessions" / "review-queue.jsonl").write_text(json.dumps({"session": "s1", "substantive": 2}) + "\n", encoding="utf-8")
    body = json.loads(inbox(root, "--json").stdout or "{}")
    check("the inbox lists the draft with its title and the queued review",
          [d["title"] for d in body.get("drafts", [])] == ["Probe draft"] and len(body.get("queued_reviews", [])) == 1, body)
    old = root / ".inbox" / "procedure-old.md"
    old.write_text(DRAFT.format(id="old", title="Old draft"), encoding="utf-8")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    scoped = json.loads(inbox(root, "--json", "--since", "2024-01-01T00:00:00Z").stdout or "{}")
    shown = inbox(root, "--since", "2024-01-01T00:00:00Z").stdout
    check("--since lists only the drafts written after it and counts the rest",
          [d["title"] for d in scoped.get("drafts", [])] == ["Probe draft"] and scoped.get("older") == 1
          and "since 2024-01-01T00:00:00Z" in shown and "Old draft" not in shown, (scoped, shown))
    drained = inbox(root, "--drain")
    check("drain clears the ask log and leaves the drafts alone",
          not (root / ".sessions" / "review-queue.jsonl").exists() and (root / ".inbox" / "procedure-probe.md").is_file(), drained.stdout)


def test_add_cite_and_journal_round_trip(tmp: Path) -> None:
    """The write side the prompts use: `add` a unit from stdin, `cite` it, `journal add` an entry."""
    from cli_runner import run as cli

    env = {"CREW_MEMORY_DIR": str(tmp / "memory"), "CREW_JOURNAL_DIR": str(tmp / "journal"), "HOME": str(tmp)}

    def mem(*arguments: str, stdin: str = "") -> subprocess.CompletedProcess:
        return cli(ROOT / "src" / "crew" / "memory" / "crew_mem.py", *arguments, env=env, cwd=tmp, stdin=stdin)

    check("init prepares the store", mem("init").returncode == 0)
    added = mem("add", "--type", "procedure", "--scope", "global", "--title", "Run the hook suite first",
                "--evidence", "x", stdin="Run the hook suite before any guard change.\n")
    check("add writes one unit", added.returncode == 0, added.stderr)
    units = json.loads(mem("list", "--json").stdout)
    unit = units[0] if isinstance(units, list) and units else {}
    check("list shows the unit with its title", unit.get("title") == "Run the hook suite first", units)
    cited = mem("cite", "--outcome", "helped", unit.get("id", "none"))
    check("cite records the outcome on the unit", cited.returncode == 0 and "helped: 1" in next(
        (tmp / "memory").rglob(f"*{unit.get('id', 'none').split('-', 1)[-1]}*.md")).read_text(), cited.stderr)
    journal = mem("journal", "add", "--title", "PR review: probe", "--tags", "probe", "--repo", "demo",
                  stdin="The probe confirmed the guard runs first.\n")
    stored = list((tmp / "memory" / "observations" / "demo").glob("observation-*.md"))
    check("journal add stores the entry as one observation in its repo's scope",
          journal.returncode == 0 and len(stored) == 1, journal.stderr)
    (tmp / "memory" / ".inbox" / "procedure-draft.md").write_text(DRAFT.format(id="draft", title="Draft"), encoding="utf-8")
    (tmp / "memory" / "global" / ".hidden.md").write_text(DRAFT.format(id="hidden", title="Hidden"), encoding="utf-8")
    (tmp / "memory" / "global" / "link.md").symlink_to(stored[0])
    (tmp / "dangling.tar.gz").symlink_to(tmp / "victim.tar.gz")
    check("export refuses a target path that is a link, even a dangling one",
          mem("export", str(tmp / "dangling.tar.gz")).returncode == 2 and not (tmp / "victim.tar.gz").exists())
    exported = mem("export", str(tmp / "units.tar.gz"))
    with tarfile.open(tmp / "units.tar.gz") as bundle:
        members = bundle.getmembers()
    names = sorted(member.name for member in members)
    check("export carries the unit and the observation, not the index, inbox, sessions, a link or a hidden file",
          exported.returncode == 0 and len(names) == 2 and all(n.startswith(("global/", "observations/demo/")) for n in names)
          and "skipped" in exported.stderr and "link.md" in exported.stderr and ".hidden.md" in exported.stderr, (names, exported.stderr))
    check("the export is private and names no owner",
          (tmp / "units.tar.gz").stat().st_mode & 0o777 == 0o600 and all((m.uid, m.gid, m.uname, m.gname) == (0, 0, "", "") for m in members))
    env["CREW_MEMORY_DIR"] = str(tmp / "other")
    mem("init")
    first, again = mem("import", str(tmp / "units.tar.gz")), mem("import", str(tmp / "units.tar.gz"))
    found = json.loads(mem("search", "hook suite", "--repo", "*", "--json").stdout or "[]")
    check("import adds every unit to a new store, indexed; a second import changes nothing",
          (first.returncode, again.returncode) == (0, 0) and [u["id"] for u in found] == [unit.get("id")]
          and "added 0, unchanged 2" in again.stdout, (first.stderr, again.stdout, found))
    # The exported unit by name: `global/` also holds the store's INDEX.md, and glob order differs by filesystem.
    stored_unit = tmp / "other" / next(name for name in names if name.startswith("global/"))
    stored_unit.write_text(stored_unit.read_text() + "Edited here.\n", encoding="utf-8")
    conflict = mem("import", str(tmp / "units.tar.gz"))
    check("a differing stored unit is kept and the import exits 1",
          conflict.returncode == 1 and "Edited here." in stored_unit.read_text(),
          (conflict.returncode, conflict.stdout, conflict.stderr))
    (tmp / "not-a-dir").write_text("x", encoding="utf-8")
    env["CREW_MEMORY_DIR"] = str(tmp / "not-a-dir" / "memory")
    plain, warned = mem("context", "--query", "x"), mem("context", "--query", "x", "--warn-unavailable")
    check("an unavailable store exits 2, or with --warn-unavailable prints none and a warning and exits 0",
          plain.returncode == 2 and (warned.returncode, warned.stdout.strip()) == (0, "none")
          and "warning: memory unavailable" in warned.stderr, (plain.returncode, warned.stdout, warned.stderr))


def unit_text(ident: str, scope: str = "global", unit_type: str = "procedure", status: str = "active") -> str:
    return (f"---\nid: {ident}\ntype: {unit_type}\nscope: {scope}\ntitle: Title {ident}\nstatus: {status}\n"
            f"created: 2026-01-01\nmodified: 2026-01-01\nevidence: [x]\n---\nBody of {ident}.\n")


# (case, archive members, a regular file put in the store first or None, module caps patched) -> refused, exit 2, nothing written
REFUSED = (
    ("a path outside the unit layout", {"global/ok.md": unit_text("procedure-ok"), "repos/../escape.md": unit_text("procedure-esc")}, None, {}),
    ("no frontmatter", {"global/ok.md": unit_text("procedure-ok"), "global/bad.md": "no frontmatter\n"}, None, {}),
    ("an unknown type", {"global/ok.md": unit_text("procedure-ok"), "global/odd.md": unit_text("odd-x", unit_type="rumour")}, None, {}),
    ("an unknown status", {"global/ok.md": unit_text("procedure-ok"), "global/odd.md": unit_text("procedure-x", status="lost")}, None, {}),
    ("a declared scope other than its path's", {"global/sc.md": unit_text("procedure-sc", scope="repos/victim")}, None, {}),
    ("a repo unit claiming global", {"repos/x/sc.md": unit_text("procedure-sc", scope="global")}, None, {}),
    ("names equal after casefold", {"global/Case.md": unit_text("procedure-a"), "global/case.md": unit_text("procedure-b")}, None, {}),
    ("one id twice", {"global/a.md": unit_text("procedure-same"), "global/b.md": unit_text("procedure-same")}, None, {}),
    ("an id already stored under another path", {"global/zz-other.md": unit_text("procedure-orig")}, None, {}),
    ("a member over the size cap", {"global/big.md": unit_text("procedure-big") + "a" * 300_000}, None, {}),
    ("more members than the cap", {f"global/m{i}.md": unit_text(f"procedure-m{i}") for i in range(3)}, None, {"MAX_MEMBERS": 2}),
    ("more bytes than the total cap", {f"global/m{i}.md": unit_text(f"procedure-m{i}") for i in range(3)}, None, {"MAX_TOTAL_BYTES": 400}),
    ("a write failing partway", {"repos/aaa/one.md": unit_text("procedure-one", "aaa"), "repos/zzz/two.md": unit_text("procedure-two", "zzz")},
     "repos/zzz", {}),
)


@pytest.mark.parametrize("case,members,blocker,caps", REFUSED, ids=[case for case, *_ in REFUSED])
def test_import_refuses_an_archive_whole(case: str, members: dict[str, str], blocker: str | None, caps: dict[str, int],
                                         tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every member is checked before anything is written; a write that fails partway leaves nothing behind."""

    from cli_runner import run as cli

    from crew.memory import memory_transfer

    for name, value in caps.items():
        monkeypatch.setattr(memory_transfer, name, value)
    env = {"CREW_MEMORY_DIR": str(tmp / "memory"), "CREW_JOURNAL_DIR": str(tmp / "journal"), "HOME": str(tmp)}

    def mem(*arguments: str, stdin: str = "") -> subprocess.CompletedProcess:
        return cli(ROOT / "src" / "crew" / "memory" / "crew_mem.py", *arguments, env=env, cwd=tmp, stdin=stdin)

    mem("init")
    (tmp / "memory" / "global" / "orig.md").write_text(unit_text("procedure-orig"), encoding="utf-8")
    if blocker:
        (tmp / "memory" / blocker).parent.mkdir(parents=True, exist_ok=True)
        (tmp / "memory" / blocker).write_text("not a directory\n", encoding="utf-8")
    before = sorted(p.relative_to(tmp / "memory").as_posix() for p in (tmp / "memory").rglob("*.md"))
    with tarfile.open(tmp / "in.tar.gz", "w:gz") as bundle:
        for name, text in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(text.encode())
            bundle.addfile(info, io.BytesIO(text.encode()))
    result = mem("import", str(tmp / "in.tar.gz"))
    after = sorted(p.relative_to(tmp / "memory").as_posix() for p in (tmp / "memory").rglob("*.md"))
    listed = mem("list", "--json")
    assert (result.returncode, after, listed.returncode) == (2, before, 0), (result.stdout, result.stderr, after, listed.stderr)


def test_mutate_restores_when_the_index_cannot_parse_a_write(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    from crew.memory import memory_maintenance, memory_store
    monkeypatch.setenv("CREW_MEMORY_DIR", str(tmp / "memory"))
    monkeypatch.setenv("HOME", str(tmp))
    memory_maintenance.init_store()
    bad = tmp / "memory" / "global" / "bad.md"

    def change() -> list:
        bad.write_text("no frontmatter\n", encoding="utf-8")
        return [(bad, None)]

    with pytest.raises(ValueError):
        memory_store.mutate("mem: bad", change)
    check("a unit the refresh cannot parse is removed again", not bad.exists())


def test_primary_remote() -> None:

    from crew.task import task_repo_facts
    check("a checkout with neither upstream nor origin reports its first remote",
          task_repo_facts.primary_remote(["fork", "mirror"]) == "fork")
    check("upstream wins over origin, whatever the order", task_repo_facts.primary_remote(["origin", "upstream"]) == "upstream")


@pytest.mark.parametrize("case,url,expected", KEYS)
def test_repo_key(case: str, url: str | None, expected: str, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    from crew.memory import memory_paths
    from crew.task import task_repo_facts
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    checkout = tmp / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    if url:
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", url], check=True)
    monkeypatch.chdir(checkout)
    check(f"{case}: key is {expected}", memory_paths.repo_key() == expected, memory_paths.repo_key())
    if url:
        with contextlib.redirect_stderr(io.StringIO()):  # an unborn HEAD is reported, and is not the case
            named = task_repo_facts.collect(argparse.Namespace(root=None, remote=None, network=False))["repo_name"]
        check(f"{case}: crew-repo-info's repo_name is the same {expected}", named == expected, named)


# (case, the reason import-claude gives) for each entry it leaves to the owner's decision.
CLAUDE_REVIEW = (("unresolved", "does not resolve"), ("other repo", "names the repo gadgets"),
                 ("index text", "MEMORY.md holds text"), ("symlink", ": symlink"), ("nested", ": nested"),
                 ("ambiguous", "matches 2 directories"))


def git(*arguments: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    *arguments], check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})


def claude_entry(config: Path, checkout: Path | str, name: str, text: str) -> Path:
    """One auto-memory file under the project folder Claude Code would name for `checkout`."""
    folder = config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(checkout)) / "memory"
    (folder / name).parent.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder / name


def claude_store(tmp: Path) -> dict[str, Path]:
    """A config dir whose entries cover each type, a dashed repo, a worktree, and each case left for review."""
    cebola, gadget, worktree, config = tmp / "code" / "cebola-fit", tmp / "code" / "gadget", tmp / "code" / "wt", tmp / "cfg"
    for checkout, url in ((cebola, "https://github.com/acme/cebola-fit.git"), (gadget, "git@github.com:acme/gadgets.git")):
        git("init", "-q", str(checkout))
        git("-C", str(checkout), "remote", "add", "origin", url)
        git("-C", str(checkout), "commit", "-q", "--allow-empty", "-m", "x")
    git("-C", str(gadget), "worktree", "add", "-q", str(worktree))
    entry = "---\nname: n\ndescription: d\ntype: {kind}\n---\n{body}\n"
    paths = {kind: claude_entry(config, cebola, f"{kind}_{kind}-note.md",
                                entry.format(kind=kind, body=f"Remember the {kind} rule number {i}."))
             for i, kind in enumerate(("user", "feedback", "project"))}
    paths["worktree"] = claude_entry(config, worktree, "reference_dashboard.md",
                                     entry.format(kind="reference", body="Dashboards live in grafana."))
    paths["injected"] = claude_entry(config, cebola, "feedback_injected.md",
                                     "---\ntype: feedback\nscope: global\nid: evil\nstatus: superseded\n"
                                     "source_identity: claude-memory:/elsewhere\n---\nKeep the migrations expand only.\n")
    paths["unresolved"] = claude_entry(config, "/no/such/checkout-anywhere", "feedback_gone.md",
                                       entry.format(kind="feedback", body="Gone folder."))
    paths["other repo"] = claude_entry(config, cebola, "feedback_other.md",
                                       entry.format(kind="feedback", body="In gadgets, renames drop the old name."))
    paths["duplicate"] = claude_entry(config, cebola, "project_dup.md",
                                      entry.format(kind="project", body="Stored before the import."))
    # Naming its own repo as well as another is not a misfiled entry.
    paths["both repos"] = claude_entry(config, cebola, "feedback_both.md",
                                       entry.format(kind="feedback", body="cebola-fit follows the gadgets naming."))
    # A heading is index structure, not a fact.
    (paths["user"].parent / "MEMORY.md").write_text(
        "# Memory Index\n\n- [u](user_user-note.md) — a note\n- [o](feedback_other.md)\n", encoding="utf-8")
    (paths["worktree"].parent / "MEMORY.md").write_text("- [d](reference_dashboard.md)\n", encoding="utf-8")
    paths["index text"] = claude_entry(config, gadget, "MEMORY.md", "A fact written inline, in no entry.\n")
    (tmp / "elsewhere.md").write_text(entry.format(kind="feedback", body="Linked in."), encoding="utf-8")
    paths["symlink"] = paths["user"].parent / "feedback_link.md"
    paths["symlink"].symlink_to(tmp / "elsewhere.md")
    paths["nested"] = claude_entry(config, cebola, "sub/feedback_nested.md", entry.format(kind="feedback", body="Deep."))
    for ambiguous in (tmp / "code" / "my-repo", tmp / "code" / "my" / "repo"):
        ambiguous.mkdir(parents=True)
    paths["ambiguous"] = claude_entry(config, tmp / "code" / "my-repo", "feedback_which.md",
                                      entry.format(kind="feedback", body="Which repo is this?"))
    return {**paths, "config": config}


def test_import_claude(tmp: Path) -> None:
    """Auto-memory entries become inbox drafts that import; review cases are listed; archive moves only imported ones."""
    from cli_runner import run as cli

    paths = claude_store(tmp)
    env = {"CREW_MEMORY_DIR": str(tmp / "memory"), "HOME": str(tmp / "home"), "CLAUDE_CONFIG_DIR": None}

    def mem(*arguments: str, stdin: str = "") -> subprocess.CompletedProcess:
        return cli(ROOT / "src" / "crew" / "memory" / "crew_mem.py", *arguments, env=env, cwd=tmp, stdin=stdin)

    mem("init")
    stored = mem("add", "--type", "project", "--scope", "cebola-fit", "--title", "Stored", stdin="Stored before the import.\n")
    claude = ("import-claude", "--config-dir", str(paths["config"]))
    dry = mem(*claude, "--dry-run")
    check("the dry run names six drafts and writes none",
          (stored.returncode, dry.stdout.count("would draft"), list((tmp / "memory" / ".inbox").glob("*.md"))) == (0, 6, []),
          dry.stdout)
    done = mem(*claude)
    drafts = [path.read_text(encoding="utf-8") for path in (tmp / "memory" / ".inbox").glob("*.md")]
    by_source = {text.split("source_identity: claude-memory:")[1].split("\n")[0]: text for text in drafts}
    for kind in ("user", "feedback", "project"):
        check(f"a {kind} entry becomes a {kind} draft in the dashed repo's scope",
              f"type: {kind}\nscope: repo:cebola-fit\n" in by_source.get(str(paths[kind]), ""), by_source.keys())
    check("an entry naming its own repo and another stays in its own scope",
          "scope: repo:cebola-fit\n" in by_source.get(str(paths["both repos"]), ""), done.stdout)
    check("a worktree's folder resolves to its repo's remote name",
          "type: reference\nscope: repo:gadgets\n" in by_source.get(str(paths["worktree"]), ""), done.stdout)
    injected = by_source.get(str(paths["injected"]), "")
    check("injected frontmatter is ignored: scope, id, status and source identity are the import's own",
          "scope: repo:cebola-fit" in injected and "status: active" in injected and "evil" not in injected
          and "/elsewhere" not in injected, injected)
    check("each draft id carries the 8-character hash of its source, and records the source hash",
          all(re.search(r"^id: [a-z]+-[a-z0-9-]+-[0-9a-f]{8}$", text, re.M) and re.search(
              r"^source_sha256: [0-9a-f]{64}$", text, re.M) for text in drafts), drafts)
    lines = done.stdout.splitlines()
    for case, reason in CLAUDE_REVIEW + (("duplicate", "already stored as project-stored"),):
        check(f"{case}: listed, not drafted", str(paths[case]) not in by_source
              and any(str(paths[case]) in line and reason in line for line in lines), done.stdout)
    again = mem(*claude)
    imported = mem("import-inbox", "--all")
    check("a second run drafts nothing; every draft passes import-inbox",
          "drafted " not in again.stdout and again.stdout.count("already drafted") == 6
          and (imported.returncode, len(imported.stdout.split())) == (0, 6), (again.stdout, imported.stdout, imported.stderr))
    check_claude_archive(tmp, mem, claude, paths)


def check_claude_archive(tmp: Path, mem: Callable[..., subprocess.CompletedProcess], claude: tuple[str, ...],
                         paths: dict[str, Path]) -> None:
    """`--check` counts review entries and edited imports; `--archive` moves imported and already-stored entries
    only, and a link-only MEMORY.md once all it lists went."""
    paths["user"].write_text(paths["user"].read_text(encoding="utf-8") + "Edited after the import.\n", encoding="utf-8")
    left = mem(*claude, "--check")
    reviews = [line for line in left.stdout.splitlines() if line.startswith("review ")]
    check("--check names each review entry with its way out, the edited import too, and exits 1",
          left.returncode == 1 and len(reviews) == len(CLAUDE_REVIEW) + 1 and "not imported:" not in left.stdout
          and all("delete or move the file" in line for line in reviews)
          and any(str(paths["user"]) in line and "edited since its import" in line for line in reviews), left.stdout)
    dry = mem(*claude, "--archive", "--dry-run")
    check("an archive dry run moves nothing", "would archive" in dry.stdout and all(os.path.lexists(p) for p in paths.values()),
          dry.stdout)
    done = mem(*claude, "--archive")
    names = sorted(p.name for p in (tmp / "home" / ".agent" / "archive").rglob("*.md"))
    moved = ("feedback", "project", "worktree", "injected", "duplicate", "both repos")
    check("archive moves imported and already-stored entries and a link-only MEMORY.md; it keeps the rest, saying why",
          names == sorted(["MEMORY.md", *(paths[k].name for k in moved)])
          and all(os.path.lexists(paths[k]) for k in ("user", *(case for case, _ in CLAUDE_REVIEW)))
          and f"kept {paths['user']}: edited since its import" in done.stdout
          and (paths["user"].parent / "MEMORY.md").exists() and not (paths["worktree"].parent / "MEMORY.md").exists(),
          (names, done.stdout))
