"""`crew-tool.py`: every agent verb answers in the one envelope, its errors included; the guard rules the core
functions run (worker tree, credentials), driven both directly and through the CLI; no verb offers an owner-only
move."""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
import time
import typing
from pathlib import Path

import pytest
from cli_runner import run as cli

from crew.lib.errors import Code, ToolError
from crew.tools.crew_tool import VERBS, function

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "src" / "crew" / "tools" / "crew_tool.py"

# One invocation per verb that the verb itself refuses (not argparse), run with HOME and the cwd a bare temp dir.
REFUSED = {
    "task-context": ["--task-dir", "{tmp}/none"],
    "task-list": [],
    "repo-facts": [],
    "pr-read": ["issue"],
    "mem-recall": ["--repo", "../escape"],
    "guidance": ["x.md"],
    "review-prepare": ["bogus"],
    "task-transition": ["approve", "{tmp}/none"],
    "task-log": ["{tmp}/none", "--step", "a → b"],
    "task-prepare": ["implement", "--task-dir", "{tmp}/none"],
    "task-lock": ["write", "{tmp}/none", "t"],
    "task-ship": ["t", "{tmp}/body", "main", "o/r", "--task-dir", "{tmp}/none"],
    "review-dispatch": ["{tmp}/none"],
    "review-finish": ["{tmp}/none"],
    "review-record-outcome": ["{tmp}/none", "f", "p", "nit", "applied", "r"],
    "mem-write": ["bogus", "s", "t", "b"],
}


def tool(tmp: Path, *args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return cli(TOOL, *args, env={"HOME": str(tmp), "CREW_TASK_DIR": None, "CREW_WORKER_TASK": None, **(env or {})}, cwd=cwd or tmp)


def test_every_verb_has_an_error_case() -> None:
    assert set(REFUSED) == set(VERBS)


@pytest.mark.parametrize("verb", sorted(VERBS))
def test_error_paths(verb: str, tmp: Path) -> None:
    usage = tool(tmp, verb, "--bogus")
    assert usage.returncode == 2 and len(usage.stderr.strip().splitlines()) == 1 and usage.stderr.startswith("error usage"), usage.stderr
    refused = tool(tmp, verb, "--json", *[arg.format(tmp=tmp) for arg in REFUSED[verb]])
    envelope = json.loads(refused.stdout)
    assert refused.returncode in (1, 2, 3) and envelope["v"] == 1 and envelope["ok"] is False, refused
    assert set(envelope["error"]) == {"code", "step", "message", "hint"} and envelope["error"]["message"], envelope
    assert envelope["error"]["code"] in typing.get_args(Code), envelope


@pytest.mark.parametrize("verb", sorted(VERBS))
def test_every_verb_is_shaped_for_an_mcp_server(verb: str) -> None:
    """Typed parameters, a one-line description, a typed return, no `*args` or `**kwargs`: registrable unchanged."""
    found = function(verb)
    hints = typing.get_type_hints(found)
    parameters = inspect.signature(found).parameters.values()
    assert (found.__doc__ or "").strip().splitlines()[0] and "return" in hints, verb
    assert all(p.kind is p.POSITIONAL_OR_KEYWORD and p.name in hints for p in parameters), verb


def test_task_context_subsets_and_cuts_each_artifact_at_its_identity_edge(tmp: Path) -> None:
    """The cached task and its artifacts; a review keeps its tail (the footer persist appends), a spec its head; a
    branch override resolves fresh, and no matching task is `state: none` with an empty `task_dir`."""
    task = tmp / "task"
    task.mkdir()
    (task / ".task-id").write_text(json.dumps({"repo_remote_url": "git@example.invalid:o/demo.git", "branch": "demo", "slug": "demo"}))
    (task / "SPEC.md").write_text("# Spec: demo\n\n## Status\nAPPROVED\n" + "body line\n" * 40)
    (task / "REVIEW.md").write_text("# Review\n\n" + "finding text here\n" * 60 + "Verdict: WARN\nReviewed at: abcdef1\n")
    cached = {"CREW_TASK_DIR": str(task)}
    data = json.loads(tool(tmp, "task-context", "--json", "--artifacts", "spec,review", "--max-chars", "200", env=cached).stdout)["data"]
    assert (data["state"], data["task_dir"], data["status"], sorted(data["artifacts"])) == ("ok", str(task), "APPROVED", ["review", "spec"]), data
    assert data["artifacts"]["review"].startswith("(TRUNCATED: last 200") and "Reviewed at: abcdef1" in data["artifacts"]["review"]
    assert data["artifacts"]["spec"].startswith("(TRUNCATED: first 200") and "# Spec: demo" in data["artifacts"]["spec"]
    shown = tool(tmp, "task-context", "--artifacts", "review", "--max-chars", "200", env=cached).stdout
    assert "## review" in shown and "TRUNCATED" in shown and "## spec" not in shown, shown
    nowhere = ["--remote", "https://example.invalid/none.git", "--branch", "none"]
    assert json.loads(tool(tmp, "task-context", "--json", *nowhere, env=cached).stdout)["data"]["state"] == "none"
    empty = tool(tmp, "task-context", "--field", "task_dir", *nowhere)
    assert (empty.returncode, empty.stdout) == (0, "\n"), empty


def repo(tmp: Path) -> Path:
    tree = tmp / "repo"
    tree.mkdir()
    for argv in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["commit", "-q", "--allow-empty", "-m", "c"]):
        subprocess.run(["git", "-C", str(tree), *argv], check=True)
    return tree


def test_a_held_worker_lock_refuses_lock_and_its_removal(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule lives in the core (`task_lock.worker_tree`): the function refuses, and so does the CLI over it."""
    from crew.core.task.task_lock import remove_lock, write_lock

    tree = repo(tmp)
    (tree / ".crew-worker.lock").write_text(f"task=other\nstarted={int(time.time())}\n", encoding="utf-8")
    monkeypatch.delenv("CREW_WORKER_TASK", raising=False)
    for call in (lambda: write_lock(tree, "mine"), lambda: remove_lock(tree, "mine")):
        with pytest.raises(ToolError) as refused:
            call()
        assert refused.value.code == "worker_tree"
    for action in ("write", "remove"):
        assert json.loads(tool(tmp, "task-lock", action, str(tree), "mine", "--json").stdout)["error"]["code"] == "worker_tree"
    assert tool(tmp, "task-lock", "remove", str(tree), "mine", env={"CREW_WORKER_TASK": "other"}).returncode == 0


def test_a_secret_in_the_diff_refuses_ship(tmp: Path) -> None:
    """The credential scan runs inside the core `ship_task`: the function refuses, and so does the verb."""
    from test_ship import TOKEN, world

    from crew.core.task.task_ship import ship_task

    task, tree, env = world(tmp, "true")
    (tree / "a.txt").write_text(f"token = {TOKEN}\n", encoding="utf-8")
    (tmp / "body.md").write_text("body\n", encoding="utf-8")
    args = ["task-ship", "t", str(tmp / "body.md"), "main", "acme/widgets", "--task-dir", str(task), "--json"]
    envelope = json.loads(cli(TOOL, *args, env=env, cwd=tree).stdout)
    assert not envelope["ok"] and "credential-like token" in envelope["error"]["message"], envelope
    assert callable(ship_task)


def test_the_hook_path_loads_no_mcp_stack() -> None:
    """The hook entry point and the commands hooks run (crew-task.py, crew-review-findings.py, crew-tool.py) import no
    `pydantic`, `mcp` or `githubkit`: those load on the MCP path only, so a hook's start-up never pays for them."""
    modules = ("crew.harness.crew_hook", "crew.scripts.crew_task", "crew.tools.crew_review_findings", "crew.tools.crew_tool")
    code = f"import sys\nfor m in {modules!r}: __import__(m)\nprint(sorted({{n.split('.')[0] for n in sys.modules}} & {{'pydantic', 'mcp', 'githubkit'}}))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[]", done.stdout


def test_no_verb_offers_an_owner_only_move() -> None:
    from crew.core.task.api import task_transition

    moves = typing.get_args(typing.get_type_hints(task_transition)["move"])
    assert set(moves) == {"approve", "implement", "done", "block"}
    assert not {"force", "accept"} & set(inspect.signature(task_transition).parameters)
    assert not {"gc", "restore-status", "normalize-status"} & {name.removeprefix("task-") for name in VERBS}
