"""Smaller dispatch prompts: guidance ranked per agent kind under a cap, and the readers that measure a dispatch.

Ranking orders sections and only the cap drops anything, so a rule under a generic heading still reaches a lens
whose cap has room; the builder keeps the test, editing and contract rules; every drop is named with its file. The
readers (`dispatch-bytes`, `cache-report`) read a prepared directory and a task's METRIC lines, never real state.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
sys.path.insert(0, str(TOOLS / "task"))
sys.path.insert(0, str(TOOLS))

from task_guidance import collect  # noqa: E402
from task_guidance_kinds import KINDS, RECOVERY, narrow  # noqa: E402
from task_prepare import guidance_for  # noqa: E402

FINDINGS = TOOLS / "review" / "crew-review-findings.py"
CONTEXT = TOOLS / "task" / "crew-agent-context.py"
CONVENTIONS = ("# Repo\n\nintro\n\n## Conventions\n\n### Frontend\nui rules\n\n"
               "### Node\nMigrations are expand-only.\n\n## Hooks\nA hook exits 2 with one stderr line.\n\n"
               "## Project structure\n{tree}\n")


def kept(kind: str, paths: list[str]) -> str:
    files = collect(ROOT, [ROOT / path for path in paths])["files"]
    return "\n".join(narrow(kind, files, paths)[0].values())


def test_each_kind_keeps_its_must_hold_rules_here_and_stays_under_its_cap() -> None:
    tools = [".agent/tools/task/task_prepare.py"]
    prompts = kept("reviewer-prompt-quality", tools)
    assert "## Authoring agent and skill files" in prompts
    assert "load the `prompt-authoring` skill first" in prompts
    builder = kept("builder", tools)
    assert all(rule in builder for rule in ("## Run it, do not guess", "## Editing and tests", "## Tests", "## Hooks"))
    assert "## Editing\n" in builder
    for kind in ("builder", "resolver", "explorer"):
        assert "## Authoring agent and skill files\n" in kept(kind, [*tools, ".cursor/agents/crew-builder.md"]), \
            f"{kind}: a prompt path ranks the authoring rules second"
    files = collect(ROOT, [ROOT / tools[0]])["files"]
    for kind, (_, cap) in KINDS.items():
        size = sum(len(text.encode()) for text in narrow(kind, files)[0].values())
        assert size <= cap + len("[cut at the cap]\n"), kind


def test_a_rule_under_a_generic_heading_is_ranked_not_dropped_and_every_drop_names_its_file() -> None:
    small = {"/r/AGENTS.md": CONVENTIONS.format(tree="src/ holds the code")}
    architecture = narrow("reviewer-architecture", small)[0]["/r/AGENTS.md"]
    assert "Migrations are expand-only." in architecture and "## Conventions" in architecture, \
        "no topic names Conventions > Node, and it still fits under the cap"
    assert "A hook exits 2" in narrow("builder", small)[0]["/r/AGENTS.md"]
    big = {"/r/AGENTS.md": CONVENTIONS.format(tree="\n".join(f"src/{n}.ts" for n in range(3000)))}
    text, said = narrow("reviewer-architecture", big)
    assert "[cut at the cap]" in text["/r/AGENTS.md"] and "AGENTS.md: Project structure (cut)" in said
    assert "AGENTS.md: Conventions > Node" in said and said.endswith(RECOVERY), "the cap drops last-ranked sections"


def test_a_section_naming_the_agents_path_outranks_a_structure_listing_larger_than_the_cap() -> None:
    tree = "\n".join(f"  db/\n    migrate.ts\n    file{n}.ts" for n in range(1500))
    files = {"/r/AGENTS.md": "# Repo\n\n## Project structure\n" + tree + "\n\n## Conventions\n\n### Frontend\nui\n\n"
                             "### Node\n`node db/migrate.ts` applies migrations; they are expand-only.\n"}
    unranked = narrow("reviewer-architecture", files)[0]["/r/AGENTS.md"]
    assert "expand-only" not in unranked, "without the path, the layout listing fills the cap"
    text, said = narrow("reviewer-architecture", files, ["db/migrate.ts"])
    assert "they are expand-only" in text["/r/AGENTS.md"] and "Conventions > Node" not in said, said
    assert "AGENTS.md: Project structure (cut)" in said, "a bare basename in the listing earns no relevance"


def test_builder_paths_skip_an_ambiguous_basename_and_fall_back_to_the_root(tmp: Path) -> None:
    for folder in ("a", "b"):
        (tmp / folder).mkdir()
        (tmp / folder / "index.ts").write_text("x\n")
        (tmp / folder / "AGENTS.md").write_text(f"# {folder} rules\n")
    (tmp / "AGENTS.md").write_text("# Root\n\nroot rule\n")
    for command in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", *command], cwd=tmp, check=True, capture_output=True)
    block, said = guidance_for(tmp, [(1, False, "- [ ] T1: edit `index.ts`.")])
    assert "Ambiguous, not collected: index.ts (2 files)." in said and "a rules" not in block
    assert "Guidance collected for: ." in said and "root rule" in block, "nothing resolved: the root's guidance"
    block, said = guidance_for(tmp, [(1, False, "- [ ] T1: edit `a/index.ts`.")])
    assert "Guidance collected for: a." in said and "a rules" in block
    shown = cli(CONTEXT, "--kind", "resolver", "--root", str(tmp), str(tmp / "a" / "index.ts"))
    assert json.loads(shown.stdout)["kind"] == "resolver", shown


def test_dispatch_bytes_reports_size_guidance_and_the_shared_prefix(tmp: Path) -> None:
    head, guidance = "shared head\n" * 10, '<guidance kind="x" cap="1">\n## From\n</guidance>\n'
    for name in ("adversarial", "architecture"):
        (tmp / f"{name}.in.md").write_text(f"{head}{name}\n{guidance}")
    done = cli(FINDINGS, "dispatch-bytes", str(tmp), "--json")
    result = json.loads(done.stdout)
    assert result["shared_prefix"] == len(head) + 1, result  # the names share their first letter
    assert [row["guidance"] for row in result["rows"]] == [len(guidance)] * 2
    assert cli(FINDINGS, "dispatch-bytes", str(tmp / "empty")).returncode == 1


def end(at: str, persona: str, ident: str, started: str, first_read: int) -> str:
    return (f"[2026-11-28T{at}Z] METRIC: agent_end agent=reviewer-{persona} persona={persona} agent_id={ident} "
            f"tokens=9 input=5 output=1 cache_read=900 cache_write=10 started=2026-11-28T{started}Z first_input=5 "
            f"first_cache_read={first_read} first_cache_write=10 harness=claude-code")


def test_cache_report_counts_one_run_against_the_first_personas_own_cache_read(tmp: Path) -> None:
    lines = [
        end("09:00:00", "adversarial", "old", "08:59:00", 1),
        "[2026-11-28T09:01:00Z] METRIC: review run=20261128100000 in_bytes=1 shared_prefix=9 mapped=0",
        "[2026-11-28T10:00:00Z] METRIC: stage_start stage=review",
        end("10:02:00", "adversarial", "a", "10:00:10", 2893),
        end("10:03:00", "architecture", "b", "10:00:30", 2893),
        "[2026-11-28T10:03:00Z] METRIC: agent_end agent=reviewer-layers persona=layers agent_id=c tokens=9",
        "[2026-11-28T10:04:00Z] METRIC: review run=20261128110000 in_bytes=1 shared_prefix=92719 mapped=0",
    ]
    (tmp / "PROGRESS.md").write_text("\n".join(lines) + "\n")
    result = json.loads(cli(FINDINGS, "cache-report", "--task-dir", str(tmp), "--json").stdout)
    assert [row["persona"] for row in result["agents"]] == ["adversarial", "architecture"], "this run's lenses only"
    assert (result["baseline"], [row["above_baseline"] for row in result["agents"]]) == (2893, [0, 0])
    assert result["wall_s"] == 170 and "bar_met" not in result, result
    earlier = json.loads(cli(FINDINGS, "cache-report", "--task-dir", str(tmp), "--run", "20261128100000",
                             "--json").stdout)
    assert [row["started"] for row in earlier["agents"]] == ["2026-11-28T08:59:00Z"], "its window ends at its line"
