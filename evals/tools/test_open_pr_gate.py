#!/usr/bin/env python3
"""The stack gate in `crew open pr`: the skill text defaults BASE to the default branch.

The skill is prose, so the contract is its text: a non-default base prints one line and asks once,
an autonomous run stops with that line and opens nothing. The rule lives in the skill, never in an
always-on rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".cursor" / "skills" / "crew-open-pr" / "SKILL.md"
FAILURES: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILURES.append(name)


def main() -> int:
    text = SKILL.read_text(encoding="utf-8")
    check("old stacking question is gone", "Does this branch stack on another branch? If so, name it" not in text)
    check("BASE defaults to the default branch and the parent comes from SPEC.md `## Base:`",
          "the value resolved above" in text and "unless SPEC.md `## Base:` names a parent branch" in text)
    check("the stack gate names one source for the default branch (not crew-default-branch.sh)",
          "crew-default-branch.sh" not in text.split("**Stack gate.**")[1].split("\n\n")[0])
    line = "Base is X, not <default>. Merging this lands the change in X only.{order} Reply `stack` to open it or `<default>` to retarget."
    check("one-line stack message", line.format(order="") in text or line.format(order=" Merge order: #a -> #b -> <default>.") in text)
    check("the merge-order clause lists only existing PRs, else it is omitted",
          "only PRs that exist" in text and "omit the clause" in text)
    check("asks once", "asks once" in text or "ask once" in text)
    check("autonomous run stops and opens nothing", "autonomous" in text and "opens nothing" in text and "top of the final message" in text)
    check("gate repeated where the PR is created, exempting landing bases", "Step 3" in text
          and "neither the default branch nor a landing base" in text.split("### Step 3")[1])
    # A repo with release branches declares `landing_bases`; a matching base is normal (task 15).
    check("a landing_bases match is a normal base: no stack message, no question",
          "landing_bases" in text and "normal base" in text and "no stack message" in text)
    check("landing_bases keeps the default unchanged and matches the whole branch name",
          "default branch only" in text and "whole branch name" in text)
    for rule in sorted((ROOT / "rules").glob("*.mdc")):
        check(f"{rule.name} does not carry the gate", "Reply `stack`" not in rule.read_text(encoding="utf-8"))
    # Message routing: the user's message goes to the worker, so the next reply says so (task 6).
    routing = "Your message reached worker <id>, not me; I will re-apply it at the next stage"
    dispatch = (ROOT / ".cursor" / "skills" / "crew-implement" / "references" / "worker-dispatch.md").read_text(encoding="utf-8")
    check("worker-dispatch.md owns the routing sentence, defines <id> and when to say it",
          routing in dispatch and "agent id the harness reported" in dispatch and "run in flight" in dispatch)
    for stage in (ROOT / ".cursor" / "skills" / "crew-implement" / "SKILL.md",
                  ROOT / ".cursor" / "agents" / "crew-reviewer.md",
                  ROOT / ".cursor" / "skills" / "crew-open-pr" / "SKILL.md"):
        stage_text = stage.read_text(encoding="utf-8")
        if stage.parent.name == "crew-implement":
            check("crew-implement points at worker-dispatch.md for lock, blocked, cost and routing, restating none",
                  "Lock, blocked line, cost line and message routing: [worker dispatch]" in stage_text
                  and "lock write" not in stage_text and "lock remove" not in stage_text
                  and 'crew-task.py blocked "$TASK_DIR"' in dispatch)
        else:
            check(f"{stage.name} documents the BLOCKED call", 'crew-task.py blocked "$TASK_DIR"' in stage_text)
        check(f"{stage.name} writes no INBOX file for it", "INBOX" not in stage_text)
        check(f"{stage.name} does not copy the routing sentence", routing not in stage_text)
        if stage.parent.name != "crew-open-pr":
            check(f"{stage.name} points at worker-dispatch.md for it", "worker-dispatch.md" in stage_text)
    for rule in sorted((ROOT / "rules").glob("*.mdc")):
        check(f"{rule.name} does not carry the routing line", routing not in rule.read_text(encoding="utf-8"))
    # Review calls crew-e2e for a frontend diff; the spec template asks for one golden-path e2e (task 11).
    reviewer = (ROOT / ".cursor" / "agents" / "crew-reviewer.md").read_text(encoding="utf-8")
    rules = (ROOT / ".cursor" / "agents" / "references" / "stage-rules.md").read_text(encoding="utf-8")
    template = (ROOT / ".cursor" / "skills" / "spec-writing" / "references" / "spec-template.md").read_text(encoding="utf-8")
    check("crew-reviewer.md calls crew-e2e for a frontend diff only when AGENTS.md has an `e2e:` line",
          "crew-e2e" in reviewer and "frontend" in reviewer and "`e2e:` line" in reviewer)
    check("the e2e rule names the declared line, the artifacts hand-off and the skip",
          "`e2e:` line" in rules and "artifacts path" in rules and "product-flow" in rules and "skip this" in rules)
    check("the e2e rule never guesses a script from job names", "never guess" in rules and "`ui` job" not in rules)
    check("the e2e step runs before Step 5 and falls back to `### Reviewers` with no product-flow persona",
          "before Step 5" in reviewer and "no product-flow persona" in rules and "`### Reviewers`" in rules)
    step6 = reviewer.split("## Step 6")[1].split("## Step 7")[0]
    check("the e2e call is no longer after dispatch", "crew-e2e" not in step6)
    step4 = reviewer.split("## Step 4")[1].split("## Step 5")[0]
    check("Step 4 states the skip precedence and where a judged Prompt Quality goes",
          "records its skip" in step4 and "names it" in step4 and "assemble.json" in step4 and "`selected`" in step4
          and "not allowed" not in step4)
    check("Step 7 links the consolidate commands in one line", "consolidate-run.md" in reviewer.split("## Step 7")[1].split("## Step 8")[0])
    run_text = (ROOT / ".cursor" / "agents" / "references" / "consolidate-run.md").read_text(encoding="utf-8") \
        if (ROOT / ".cursor" / "agents" / "references" / "consolidate-run.md").is_file() else ""
    check("the consolidate-run reference names consolidate, normalize --repo --head and consolidate --render",
          "consolidate --review-dir" in run_text and "normalize" in run_text and "--repo" in run_text and "--head" in run_text
          and "--render" in run_text)
    outcomes = ROOT / ".cursor" / "skills" / "crew-implement" / "references" / "verify-outcomes.md"
    body = outcomes.read_text(encoding="utf-8") if outcomes.is_file() else ""
    check("the verify outcomes are keyed on the exit code alone, with a row for verify itself failing",
          all(row in body for row in ("| 0 |", "| 1 |", "| 2 or 3 |", "| 4 |", "| anything else"))
          and "NOT VERIFIED" in body and "Verify itself failed" in body and "show its stderr" in body.lower()
          and "--wait" in body and "hand off / commit" in body)
    commit = (ROOT / ".cursor" / "skills" / "crew-commit" / "SKILL.md").read_text(encoding="utf-8")
    check("crew-commit pauses when verify exited nonzero",
          "verify exited nonzero (Step 2c)" in commit.split("**Pause for approval**")[1].split("\n\n")[0])
    check("the crew-reviewer degraded rule is one pointer to dispatch.md, with no report edit",
          "**Degraded fallback:** see [saving replies]" in reviewer and "open the report with" not in reviewer)
    for skill in ("crew-implement", "crew-commit"):
        skill_text = (ROOT / ".cursor" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        check(f"{skill} points at the verify outcomes in one line", "verify-outcomes.md" in skill_text)
        check(f"{skill} no longer says any nonzero exit is a failed gate", "any nonzero exit" not in skill_text.lower()
              and "a nonzero exit means a failed gate" not in skill_text.lower())
    exits = (ROOT / ".agent" / "tools" / "AGENTS.md").read_text(encoding="utf-8").split("## Exit codes")[1].split("\n## ")[0]
    rows = {(line.split("|")[1].strip(), line.split("|")[2].strip()) for line in exits.splitlines()
            if line.startswith(("| `crew-verify.py", "| `crew-task.py"))}
    check("the exit-code table has rows for verify 3, 4 and worktree check 4, 5 (test_command_names checks all)",
          {("`crew-verify.py`", "`3`"), ("`crew-verify.py --wait`", "`4`"),
           ("`crew-task.py worktree check`", "`4`"), ("`crew-task.py worktree check`", "`5`")} <= rows)
    check("the e2e line format is documented for repo owners",
          "e2e: " in (ROOT / ".agent" / "tools" / "AGENTS.md").read_text(encoding="utf-8"))
    check("spec template asks for one golden-path e2e from the first group",
          "one golden-path e2e from the first group" in template)
    delta = (ROOT / ".cursor" / "skills" / "crew-implement" / "SKILL.md").read_text(encoding="utf-8")
    check("crew-implement passes the task delta and the builder path, never pasted rules",
          "task delta" in delta and "400 words" in delta and "crew-builder.md" in delta and "never paste rules" in delta)
    check("the cost line is wired in both stages (implement through worker-dispatch.md)",
          "stage_end" in dispatch and "cost line" in delta and "stage_end" in reviewer and "stage_start stage=implement" in delta)
    for failure in FAILURES:
        print(f"failed: {failure}", file=sys.stderr)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
