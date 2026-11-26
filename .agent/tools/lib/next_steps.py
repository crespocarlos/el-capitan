#!/usr/bin/env python3
"""The next-step table: one answer per completed stage, shared by the CLI and the report footer.

The table is `task/next-steps.json`, keyed by `<workflow>.<stage>.<outcome>`: which command runs
after a stage. `crew-next.py` and `review_render.footer` both read it here, so the report's
`> Next:` line and the command never disagree. A skill's own trailer is prose (`lint_handoff`).
"""
from __future__ import annotations

import json
from pathlib import Path

# Beside `transitions.json`, which is the other asset the pipeline reads as data rather than prose.
STEP_TABLE = Path(__file__).resolve().parent.parent / "task" / "next-steps.json"
# The workflows `crew-orchestrator.mdc` declares. A key may omit the workflow when exactly one holds
# the stage, which is how a `crew review` caller names `review.block` without repeating `build`.
WORKFLOWS = ("build", "lightweight", "respond")


def load_table(path: Path = STEP_TABLE) -> dict:
    """The validated rule table: every key three-part, every value naming an outcome and a reason."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {path.name}: {error}") from None
    rules = data.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise ValueError(f"{path.name} needs a non-empty `rules` object")
    for key, rule in rules.items():
        if len(key.split(".")) != 3:
            raise ValueError(f"{key}: a rule key is <workflow>.<stage>.<outcome>")
        workflow, stage, outcome = key.split(".")
        if workflow not in WORKFLOWS:
            raise ValueError(f"{key}: workflow must be one of {', '.join(WORKFLOWS)}")
        if not stage or not outcome:
            raise ValueError(f"{key}: stage and outcome cannot be empty")
        if not isinstance(rule, dict) or not rule.get("why"):
            raise ValueError(f"{key}: a rule needs a `why`")
        outcomes = [name for name in ("command", "human", "decide") if rule.get(name)]
        if not outcomes:
            raise ValueError(f"{key}: a rule needs one of command, human, or decide")
        if len(outcomes) > 1:
            raise ValueError(f"{key}: a rule names {outcomes}; keep one of command, human, or decide")
    return rules


def resolve(rules: dict, key: str) -> dict:
    """The rule for `key`, or ValueError naming what would have matched the stage."""
    if key in rules:
        return rules[key]
    if key.count(".") == 1:
        matches = [candidate for candidate in rules if candidate.endswith(f".{key}")]
        if len(matches) == 1:
            return rules[matches[0]]
        if matches:
            raise ValueError(f"{key} is ambiguous; name the workflow: {', '.join(sorted(matches))}")
        raise ValueError(f"no rule for {key}; known stages: {', '.join(known_stages(rules))}")
    raise ValueError(f"no rule for {key}; known keys: {', '.join(sorted(rules))}")


def known_stages(rules: dict) -> list[str]:
    """Every `<stage>.<outcome>` the table answers, without its workflow."""
    return sorted({".".join(candidate.split(".")[1:]) for candidate in rules})


def sentence(rule: dict) -> str:
    """The text a reply prints for this rule: a command, a person's action, or a decision."""
    if rule.get("command"):
        return f"run `{rule['command']}` to continue"
    if rule.get("human"):
        return str(rule["human"])
    return f"decide: {rule['decide']}"


def next_sentence(key: str) -> str:
    """The sentence for `key` from the shipped table; ValueError when the table has no answer."""
    return sentence(resolve(load_table(), key))
