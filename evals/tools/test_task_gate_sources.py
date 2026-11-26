#!/usr/bin/env python3
"""`crew-verify.py` in repos that are not this one: the Node pin and the gate sources.

el-capitan is project-agnostic. A Kibana-shaped repo has a `.nvmrc`, Buildkite CI that no reader here
understands, prose gate commands in nested `AGENTS.md` files and no GitHub workflow; a Python-only
repo has no Node at all. The cases pin what verify must do in each: pick the Node by the first pin
found and never force one, say which CI it cannot read, surface the nearest `AGENTS.md`'s prose
commands without running them, and refuse to report a pass when nothing runnable was declared.
Helpers come from `test_task_verify.py`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_task_verify as base
from test_task_verify import check, fake_node, fixture, git, verify, write

FAILED = base.FAILED


def pinned(tmp: Path, name: str, files: dict[str, str]) -> tuple[Path, Path]:
    """A repo with the CI workflow, no `.nvmrc`, and exactly `files` as its Node pin (if any)."""
    root, home = fixture(tmp / name), tmp / f"home-{name}"
    home.mkdir(parents=True)
    git(root, "rm", "-q", ".nvmrc")
    for path, text in files.items():
        write(root, path, text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "pin")
    return root, home


def node_pin_order(tmp: Path) -> None:
    root, home = pinned(tmp, "none", {})
    fake_node(home, "22.1.0")
    _, out, data = verify(root, home)
    check("no pin: it says so and uses the PATH", "no Node pin found, using PATH" in out, out)
    check("no pin: the JSON records it and no Node was forced",
          data["node"]["source"] == "none" and data["node"]["required"] == "" and data["node"]["used"] != "v22.1.0", data["node"])
    root, home = pinned(tmp, "nodever", {".node-version": "20.1\n"})
    fake_node(home, "20.1.0")
    _, out, data = verify(root, home)
    check(".node-version alone selects the Node",
          data["node"] == {"required": "20.1", "used": "v20.1.0", "source": ".node-version"}, data["node"])
    root, home = pinned(tmp, "tool", {".tool-versions": "python 3.11.2\nnodejs 18.2.0\n", "package.json": '{"engines": {"node": "22"}}'})
    fake_node(home, "18.2.0")
    _, out, data = verify(root, home)
    check(".tool-versions (nodejs line) beats engines.node",
          data["node"]["source"] == ".tool-versions" and data["node"]["used"] == "v18.2.0", data["node"])
    root, home = pinned(tmp, "engines", {"package.json": '{"name": "x", "engines": {"node": "^20.3.0"}}'})
    fake_node(home, "20.3.0")
    _, out, data = verify(root, home)
    check("package.json engines.node is the last pin",
          data["node"] == {"required": "20.3.0", "used": "v20.3.0", "source": "package.json engines.node"}, data["node"])
    root, home = pinned(tmp, "nvmrc", {".nvmrc": "v22\n", ".node-version": "20\n"})
    fake_node(home, "22.1.0")
    _, _, data = verify(root, home)
    check(".nvmrc wins over every other pin", data["node"]["source"] == ".nvmrc" and data["node"]["used"] == "v22.1.0", data["node"])


def python_only(tmp: Path) -> None:
    """A Python repo is never forced onto Node: no pin file, even with a Node installed under HOME."""
    root, home = tmp / "py", tmp / "home-py"
    root.mkdir(parents=True)
    home.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, "pyproject.toml", "[project]\nname = 'x'\n")
    write(root, "AGENTS.md", "# Py\n\n```gates\nunit: python3 -c 'print(1)'\n```\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "py")
    fake_node(home, "22.1.0")
    code, out, data = verify(root, home)
    check("a Python-only repo runs its gate with no Node pin", code == 0 and data["gates"][0]["exit"] == 0, out)
    check("it names the PATH and records no pin", "no Node pin found, using PATH" in out and data["node"]["source"] == "none", out)
    check("the Node in HOME is not selected", data["node"]["used"] != "v22.1.0", data["node"])
    check("the version actually used is in the gate record (and so the cache key)",
          data["gates"][0]["node_version"] == data["node"]["used"], data)


KIBANA_ROOT = """# Kibana

Run `node scripts/check.js --scope=local|staged|branch` before you push.

## Tests

```sh
yarn test:jest --config x.js
node scripts/eslint.js --fix
```

Unrelated prose: use `yarn kbn bootstrap` first.
"""
KIBANA_NESTED = """# Alerting

Run `node scripts/check.js --scope=local` and then `yarn test:jest x-pack/plugins/alerting`.
Type check with `node scripts/type_check.js --project x-pack/plugins/alerting/tsconfig.json`.
"""


def kibana_repo(tmp: Path) -> tuple[Path, Path]:
    root, home = tmp / "kibana", tmp / "home-kibana"
    root.mkdir(parents=True)
    home.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, ".nvmrc", "22.1.0\n")
    write(root, ".buildkite/pipelines/pull_request/base.yml", "steps:\n  - command: .buildkite/scripts/steps/checks.sh\n")
    write(root, "AGENTS.md", KIBANA_ROOT)
    write(root, "x-pack/plugins/alerting/AGENTS.md", KIBANA_NESTED)
    write(root, "x-pack/plugins/alerting/server/index.ts", "export const a = 1;\n")
    write(root, "x-pack/plugins/other/AGENTS.md", "# Other\n\nRun `node scripts/other_check.js`.\n")
    write(root, "x-pack/plugins/other/index.ts", "export const b = 1;\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "feat")
    write(root, "x-pack/plugins/alerting/server/index.ts", "export const a = 2;\n")
    git(root, "commit", "-q", "-am", "touch alerting")
    fake_node(home, "22.1.0")
    return root, home


def kibana_shape(tmp: Path) -> None:
    root, home = kibana_repo(tmp)
    code, out, data = verify(root, home)
    check("Buildkite is named as unreadable CI and verify falls through", "CI not readable here (buildkite)" in out, out)
    check("the JSON records the unreadable CI", data.get("ci_unreadable") == ["buildkite"], data.get("ci_unreadable"))
    check(".nvmrc selects the Node in a repo with no workflows", data["node"]["source"] == ".nvmrc" and data["node"]["used"] == "v22.1.0", data["node"])
    check("the NEAREST AGENTS.md's prose commands are surfaced, marked as not run",
          "repo-declared check, run this: node scripts/check.js --scope=local" in out
          and "repo-declared check, run this: yarn test:jest x-pack/plugins/alerting" in out
          and "repo-declared check, run this: node scripts/type_check.js" in out, out)
    check("the root and the sibling plugin's AGENTS.md are not mixed in",
          "scripts/other_check.js" not in out and "yarn test:jest --config x.js" not in out and "kbn bootstrap" not in out, out)
    check("the prose checks are in the JSON with their file and are never run",
          all(p["from"].endswith("x-pack/plugins/alerting/AGENTS.md") for p in data["prose_checks"]) and len(data["prose_checks"]) == 3
          and data["gates"] == [], data.get("prose_checks"))
    check("no runnable gate: NOT VERIFIED, loudly, and never a pass", "NOT VERIFIED" in out and data.get("verified") is False and code == 3, (code, out))
    code, out, _ = verify(root, home, "--strict")
    check("--strict exits 2 when nothing runnable was declared", code == 2 and "NOT VERIFIED" in out, (code, out))


def prose_only_repo(tmp: Path) -> None:
    """No CI at all, one AGENTS.md at the root with prose commands: surfaced, not run, not a pass."""
    root, home = tmp / "prose", tmp / "home-prose"
    root.mkdir(parents=True)
    home.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, "AGENTS.md", "# Repo\n\nBefore a PR run `make check` and `make lint`.\n")
    write(root, "src/a.py", "a = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "feat")
    write(root, "src/a.py", "a = 2\n")
    git(root, "commit", "-q", "-am", "touch")
    code, out, data = verify(root, home)
    check("a CI-less repo with prose surfaces the commands from the root AGENTS.md",
          "repo-declared check, run this: make check" in out and "repo-declared check, run this: make lint" in out, out)
    check("it did not print the unreadable-CI note (there is no CI)", "CI not readable" not in out, out)
    check("it is not a pass", code == 3 and data.get("verified") is False and "NOT VERIFIED" in out, (code, out))
    bare = tmp / "bare"
    bare.mkdir()
    git(bare, "init", "-q", "-b", "main")
    write(bare, "a.txt", "x\n")
    git(bare, "add", "-A")
    git(bare, "commit", "-q", "-m", "x")
    code, out, _ = verify(bare, home)
    check("nothing declared at all is still an error", code == 2 and "NOT VERIFIED" in out, (code, out))


def workflows_win(tmp: Path) -> None:
    """A repo with workflows: they stay THE source, and prose in AGENTS.md is not even consulted."""
    root, home = fixture(tmp / "wf"), tmp / "home-wf"
    home.mkdir(parents=True)
    write(root, "AGENTS.md", "# Repo\n\nRun `make check`.\n")
    write(root, ".buildkite/pipeline.yml", "steps: []\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "prose and buildkite next to workflows")
    _, out, data = verify(root, home)
    check("workflows are the source; nothing is reported unreadable", "source: ci-workflow" in out and not data.get("ci_unreadable"), out)
    check("prose is not surfaced when real gates exist", "repo-declared check" not in out and data.get("verified") is True, out)
    check("gates.json stays additive: the JSON keeps schema_version 1 and every earlier key",
          data["schema_version"] == 1 and {"source", "gates", "node", "notes", "skipped"} <= set(data), sorted(data))
    block = tmp / "blk"
    root2 = fixture(block, workflow=False)
    write(root2, ".buildkite/pipeline.yml", "steps: []\n")
    write(root2, "AGENTS.md", "# R\n\n```gates\nunit: true\n```\n\nRun `make check`.\n")
    git(root2, "add", "-A")
    git(root2, "commit", "-q", "-m", "block and buildkite")
    code, out, data = verify(root2, home)
    check("unreadable CI falls through to the AGENTS.md gates block", "CI not readable here (buildkite)" in out and code == 0
          and data["source"] == "AGENTS.md gates block@main", (code, out))


def wf(trigger: str, extra: str = "") -> str:
    return f"on:{trigger}\njobs:\n  j:\n{extra}    steps:\n      - name: Gate\n        run: make gate\n"


EVALS_SHAPE = ("on:\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n    inputs:\n      provider:\n"
               "        type: choice\n        options: [openrouter, anthropic]\n")


def triggers(tmp: Path) -> None:
    """A workflow with push or pull_request is mirrored unless a dangerous event is also there; the rest is recorded."""
    from task_verify_sources import workflow_gates
    cases = {
        " push": True, " [push, pull_request]": True, "\n  pull_request:\n  push:\n    branches: [main]": True,
        "\n  - push": True, " pull_request_target": False, "\n  workflow_run:\n    workflows: [CI]": False,
        "\n  release:\n    types: [published]": False, " workflow_dispatch": False, " [push, workflow_dispatch]": True,
        " [push, pull_request, workflow_dispatch]": True, " [pull_request, pull_request_target]": False,
        "\n  push:\n    tags: ['v*']": False, "\n  push:\n    tags: ['v*']\n    branches: [main]": True,
        "\n  push:\n    tags: ['v*']\n  pull_request:": True,
    }
    for trigger, mirrored in cases.items():
        gates, skipped = workflow_gates({"a.yml": wf(trigger)})
        check(f"on:{trigger!r} {'is' if mirrored else 'is not'} mirrored", bool(gates) == mirrored, gates)
        if not mirrored:
            check(f"on:{trigger!r} is recorded in skipped", any(s.startswith(("a.yml: workflow not mirrored (on: ", "a.yml: not CI (on: "))
                                                                for s in skipped), skipped)
    gates, skipped = workflow_gates({"evals.yml": EVALS_SHAPE + "jobs:\n  j:\n    steps:\n      - name: Gate\n        run: make gate\n"})
    check("this repo's evals.yml shape (pull_request + workflow_dispatch) is mirrored", [g["command"] for g in gates] == ["make gate"]
          and not skipped, (gates, skipped))
    gates, skipped = workflow_gates({"nightly.yml": wf(" schedule")})
    check("a workflow with no push or pull_request names its file and triggers as not CI", skipped == ["nightly.yml: not CI (on: schedule)"], skipped)
    gates, skipped = workflow_gates({"a.yml": wf(" push", "    environment: production\n")})
    check("a job with environment: is skipped and says why", not gates and any("environment" in s for s in skipped), skipped)
    gates, _ = workflow_gates({"a.yml": "on:\n  pull_request_target:\njobs:\n  j:\n    steps:\n      - run: npm publish\n"})
    check("npm publish in a pull_request_target workflow never becomes a gate", gates == [], gates)
    root, home = fixture(tmp / "list"), tmp / "home-list"
    home.mkdir(parents=True)
    _, out, _ = verify(root, home)
    check("the workflow files are printed before any gate runs", "workflows: .github/workflows/ci.yml" in out
          and out.index("workflows:") < out.index("exit="), out)


PUBLISH_COMMANDS = ("npm publish", "pnpm publish", "yarn publish", "yarn npm publish", "docker push img:1", "gh release create v1",
                    "gh release upload v1 a.tgz", "gh release edit v1", "twine upload dist/*", "cargo publish", "gem push x.gem",
                    "git push origin HEAD", "npm ci && npm publish", "make build; docker push img", "make build\ngh release create v1",
                    "NPM_TOKEN=x npm publish --access public", "make a || git push")


def publish_paths(tmp: Path) -> None:
    """A tag-gated publish job, a tags-only push and any publish command are never mirrored, and the run is partial."""
    from task_verify_env import is_partial
    from task_verify_sources import workflow_gates
    gated = wf(" push", "    if: startsWith(github.ref, 'refs/tags/')\n").replace("make gate", "npm publish")
    gates, skipped = workflow_gates({"a.yml": gated})
    check("a job with a job-level if: is not mirrored", gates == [] and "j: job with an if:, not mirrored" in skipped, (gates, skipped))
    check("a job-level if: makes the run partial", is_partial(skipped), skipped)
    gates, skipped = workflow_gates({"a.yml": wf("\n  push:\n    tags: ['v*']").replace("make gate", "npm publish")})
    check("a push filtered by tags only is not CI", gates == [] and is_partial(skipped), (gates, skipped))
    for command in PUBLISH_COMMANDS:
        step = "        run: |\n" + "".join(f"          {line}\n" for line in command.splitlines())
        text = f"on: push\njobs:\n  j:\n    steps:\n      - name: Ship\n{step}      - name: Unit\n        run: make unit\n"
        gates, skipped = workflow_gates({"a.yml": text})
        check(f"`{command!r}` is never a gate and is recorded", [g["command"] for g in gates] == ["make unit"]
              and any(s.startswith("ship: runs a publish") for s in skipped) and is_partial(skipped), (gates, skipped))
    for command in ("npm run publish-docs", "echo npm publish", "git pushd", "docker pull img"):
        gates, _ = workflow_gates({"a.yml": wf(" push").replace("make gate", command)})
        check(f"`{command}` is not mistaken for a publish", len(gates) == 1, gates)
    root, home = fixture(tmp / "rel"), tmp / "home-rel"
    home.mkdir(parents=True)
    write(root, ".github/workflows/release.yml", "on:\n  push:\n    tags: ['v*']\njobs:\n  ship:\n    steps:\n      - run: npm publish\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "release workflow")
    _, out, _ = verify(root, home, "--list")
    check("--list never lists the publish command as a gate", ": npm publish" not in out and "unit-tests: sh check.sh" in out, out)
    check("the release workflow is named as not mirrored", ".github/workflows/release.yml: workflow not mirrored (on: push)" in out, out)


WORKFLOW_PARTIAL = ("on: push\njobs:\n  j:\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm ci\n"
                    "      - name: Cond\n        if: github.ref == 'x'\n        run: make deploy\n"
                    "      - name: Unit\n        run: echo unit\n")


def setup_steps(tmp: Path) -> None:
    from task_verify_sources import workflow_gates
    text = ("on: push\njobs:\n  j:\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm ci && npm test\n"
            "      - run: |\n          npm ci\n          npm run lint\n      - run: |\n          npm ci\n          pip install x\n"
            "      - name: Cond\n        if: github.ref == 'x'\n        run: make deploy\n")
    gates, skipped = workflow_gates({"a.yml": text})
    commands = [g["command"] for g in gates]
    check("`npm ci && npm test` keeps its gate", "npm ci && npm test" in commands, commands)
    check("a multiline block drops only its leading setup lines", "npm run lint" in commands, commands)
    check("a step made only of setup lines is skipped", len(gates) == 2 and any("setup step" in s for s in skipped), (commands, skipped))
    root, home = fixture(tmp / "partial"), tmp / "home-partial"
    home.mkdir(parents=True)
    write(root, ".github/workflows/ci.yml", WORKFLOW_PARTIAL)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "partial")
    _, out, data = verify(root, home)
    check("the skipped steps are counted and listed", "skipped: 2 steps" in out and "not mirrored: 1 uses: steps" in out, out)
    check("a skipped non-setup step is a loud warning", "partial mirror" in out and data.get("partial") is True, (out, data.get("partial")))


def partial_mirror_is_not_verified(tmp: Path) -> None:
    root, home = fixture(tmp / "pm"), tmp / "home-pm"
    home.mkdir(parents=True)
    write(root, ".github/workflows/ci.yml", WORKFLOW_PARTIAL)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "partial")
    code, out, data = verify(root, home)
    check("passing gates on a partial mirror are NOT VERIFIED, exit 3", code == 3 and data.get("verified") is False and data.get("partial") is True, (code, out, data.get("verified")))
    check("the NOT VERIFIED line names the skipped count and comes before any gate line",
          "NOT VERIFIED: partial mirror (1 steps skipped)" in out and out.index("NOT VERIFIED") < out.index("exit="), out)
    check("the gates still ran and passed", [g["exit"] for g in data.get("gates", [])] == [0] and data.get("verdict_exit") == 3, data.get("gates"))
    code, _, _ = verify(root, home, "--strict")
    check("--strict makes it exit 2", code == 2, code)
    out_json = root.parent / "gates.json"
    base.cli("--repo", str(root), "--base", "main", "--out", str(out_json), "--background", home=home)
    waited = base.cli("--wait", str(out_json), "--timeout", "60", home=home)
    check("--wait agrees with the foreground path", waited.returncode == 3 and "NOT VERIFIED: partial mirror (1 steps skipped)" in waited.stdout, waited)
    write(root, ".github/workflows/ci.yml", WORKFLOW_PARTIAL.replace("echo unit", "exit 1"))
    git(root, "commit", "-qam", "failing")
    code, out, _ = verify(root, home)
    check("a failed gate still exits 1 on a partial mirror", code == 1, (code, out))


NOT_CI = {  # cebola-fit's workflow shapes: one CI file, the rest scheduled or dispatched by hand
    "ci.yml": "on:\n  pull_request:\n  push:\n    branches: [main]\njobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n"
              "      - run: npm ci\n      - name: Unit\n        run: echo unit\n",
    "generate-workout.yml": "on:\n  schedule:\n    - cron: '0 8 * * *'\n  workflow_dispatch:\n    inputs:\n      dry_run:\n        type: boolean\n",
    "smoke.yml": "on:\n  schedule:\n    - cron: '15 6 * * *'\n",
    "migrate.yml": "on:\n  workflow_dispatch:\n",
    "backup.yml": "on:\n  schedule:\n    - cron: '0 3 * * 0'\n  workflow_dispatch:\n",
    "hook.yml": "on:\n  repository_dispatch:\n    types: [deploy]\n",
}


def non_ci_workflows_are_not_partial(tmp: Path) -> None:
    """Workflows without push or pull_request are listed as not CI; the run reads verified when the CI steps pass."""
    root, home = fixture(tmp / "nc", workflow=False), tmp / "home-nc"
    home.mkdir(parents=True)
    for name, trigger in NOT_CI.items():
        body = "" if name == "ci.yml" else "jobs:\n  run:\n    steps:\n      - name: Deploy\n        run: make deploy\n"
        write(root, f".github/workflows/{name}", trigger + body)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "workflows")
    code, out, data = verify(root, home)
    check("passing CI steps beside schedule- and dispatch-only workflows are verified, exit 0",
          code == 0 and data.get("verified") is True and data.get("partial") is False, (code, out, data.get("partial")))
    check("only the CI workflow's step is a gate", [g.get("command") for g in data.get("gates", [])] == ["echo unit"], data.get("gates"))
    check("each workflow that is not CI is named as such", all(f".github/workflows/{name}: not CI (on: " in out for name in NOT_CI if name != "ci.yml")
          and "NOT VERIFIED" not in out, out)
    write(root, ".github/workflows/ci.yml", NOT_CI["ci.yml"] + "      - name: Cond\n        if: github.ref == 'x'\n        run: make it\n")
    git(root, "commit", "-qam", "conditional step")
    code, out, data = verify(root, home)
    check("a skipped step inside the CI workflow still makes the run partial", code == 3 and data.get("partial") is True, (code, out))


FAKE_YQ = """#!/bin/sh
if [ "$1" = --version ]; then echo "$YQ_VERSION"; exit 0; fi
printf '{"on":{"push":null},"env":{"PYTHON":3.10,"BIG":12345678901234567890,"NODE":22},"jobs":{"j":{"timeout-minutes":5,"steps":[{"run":"echo hi","continue-on-error":true}]}}}'
"""


def parser_chain(tmp: Path) -> None:
    """mikefarah yq reads the workflow when installed (scalars as strings); otherwise the stdlib reader does."""
    import os

    from lib.workflow_yaml import load
    tmp.mkdir(parents=True)
    (tmp / "yq").write_text(FAKE_YQ, encoding="utf-8")
    (tmp / "yq").chmod(0o755)
    saved = dict(os.environ)
    try:
        os.environ.update(PATH=f"{tmp}{os.pathsep}{saved['PATH']}", YQ_VERSION="yq (https://github.com/mikefarah/yq/) version v4.44.1")
        doc, parser = load("on: push\n")
        check("mikefarah yq is the parser when installed", parser == "yq", parser)
        check("its scalars come back as strings as written (3.10 stays 3.10), null as ''", doc == {"on": {"push": ""},
              "env": {"PYTHON": "3.10", "BIG": "12345678901234567890", "NODE": "22"}, "jobs": {"j": {
            "timeout-minutes": "5", "steps": [{"run": "echo hi", "continue-on-error": "true"}]}}}, doc)
        os.environ["YQ_VERSION"] = "yq 3.2.3"
        doc, parser = load("on: push\n")
        check("another yq (the Python wrapper) is not used: the stdlib reader is the fallback",
              parser == "stdlib" and doc == {"on": "push"}, (parser, doc))
    finally:
        os.environ.clear()
        os.environ.update(saved)
    root, home = fixture(tmp / "note"), tmp / "home-note"
    home.mkdir(parents=True)
    _, out, _ = verify(root, home, "--list")
    check("verify names the workflow parser it used", "workflow parser: " in out, out)


def one_gates_fence(tmp: Path) -> None:
    """One pattern describes the `gates` fence: the block it reads is the block prose checks leave out."""
    import task_verify_sources as sources
    fences = sorted(name for name in vars(sources) if name.startswith("GATES_"))
    check("one GATES_* pattern, with the block body as its capture group", fences == ["GATES_FENCE"]
          and sources.GATES_FENCE.groups == 1, fences)
    text = "Run `npm test`.\n\n```gates\nunit: npm run check\n```\n\nThen `npm run lint`.\n"
    check("the block read is the block stripped", [g["command"] for g in sources.block_gates(text)] == ["npm run check"]
          and sources.prose_commands(text) == ["npm test", "npm run lint"], (sources.block_gates(text), sources.prose_commands(text)))


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for case in (node_pin_order, python_only, kibana_shape, prose_only_repo, workflows_win, triggers, publish_paths,
                     setup_steps, partial_mirror_is_not_verified, non_ci_workflows_are_not_partial, parser_chain,
                     one_gates_fence):
            try:
                case(tmp / case.__name__)
            except (RuntimeError, KeyError, IndexError, OSError, ValueError, TypeError) as error:
                check(case.__name__, False, f"{type(error).__name__}: {error}")
    for name in FAILED:
        print(f"failed: {name}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
