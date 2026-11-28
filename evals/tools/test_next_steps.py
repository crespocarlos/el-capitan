#!/usr/bin/env python3
"""The next-step table: every completed stage answers with one step, and no key is a dead end.

The table exists because the answer to "what runs next" was prose in fourteen files and had drifted
into six shapes. A table only fixes that if it is complete and every command in it is one the router
knows, so this suite pins both directions: a missing key fails as loudly as a wrong command, and a
skill's trailer must name something the table also answers.

The fixture trees are written on disk rather than passed as strings, so each case exercises the same
load-and-resolve path `review_render.footer` takes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from crew.lib.next_steps import known_stages, load_table, resolve, sentence  # noqa: E402
from crew.scripts.maintenance.lint_references import routing_commands  # noqa: E402

TABLE = ROOT / "src" / "crew" / "core" / "task" / "next-steps.json"
ROUTER = ROOT / "rules" / "crew-router.mdc"


def table() -> dict:
    return load_table(TABLE)


def test_every_rule_states_one_outcome_and_a_reason() -> None:
    """A rule with no reason is unreviewable, and one with two outcomes is ambiguous."""
    for key, rule in table().items():
        outcomes = [name for name in ("command", "human", "decide") if rule.get(name)]
        assert len(outcomes) == 1, f"{key} names {outcomes}"
        assert rule["why"].strip(), f"{key} has no reason"


def test_every_command_is_one_the_router_knows() -> None:
    """A next step naming a command the router cannot route sends a session into a dead end."""
    verbs = routing_commands(ROUTER.read_text(encoding="utf-8"))
    for key, rule in table().items():
        command = rule.get("command")
        if not command:
            continue
        verb = command.split()[1]
        assert verb in verbs, f"{key} names `{command}`, which crew-router.mdc does not route"


def test_every_key_has_three_parts_and_a_known_workflow() -> None:
    for key in table():
        assert len(key.split(".")) == 3, key
        assert key.split(".")[0] in ("build", "respond"), key


def test_a_bare_stage_resolves_when_one_workflow_holds_it() -> None:
    assert sentence(resolve(table(), "review.block")) == "run `crew review address` to continue"


def test_an_ambiguous_stage_names_the_candidates() -> None:
    """A stage two workflows both answer must refuse the short form rather than pick one."""
    rules = dict(table())
    rules["respond.review.block"] = {"command": "crew commit", "why": "test fixture"}
    try:
        resolve(rules, "review.block")
    except ValueError as error:
        assert "ambiguous" in str(error), error
    else:
        raise AssertionError("an ambiguous short key resolved instead of failing")


def test_an_unknown_stage_lists_what_the_table_answers() -> None:
    try:
        resolve(table(), "deploy.done")
    except ValueError as error:
        message = str(error)
        assert "no rule for deploy.done" in message, message
        assert "review.block" in message, message
    else:
        raise AssertionError("an unknown key resolved")


def test_the_review_stage_answers_every_derived_verdict() -> None:
    """The footer keys on the verdict it derived, so every verdict needs a row."""
    keys = set(table())
    for verdict in ("pass", "warn", "block"):
        assert f"build.review.{verdict}" in keys, f"no next step for a {verdict.upper()} review"


def test_the_pr_stage_is_a_human_action_not_a_command() -> None:
    """A PR review posts nothing, so its next step must not read as a crew command."""
    rule = table()["build.review.pr"]
    assert rule.get("human"), rule
    assert "command" not in rule, rule


def test_all_three_outcome_kinds_render_sentences() -> None:
    assert sentence({"command": "crew commit", "why": "x"}) == "run `crew commit` to continue"
    assert sentence({"human": "paste it", "why": "x"}) == "paste it"
    assert sentence({"decide": "retry or stop", "why": "x"}) == "decide: retry or stop"


def test_a_malformed_table_is_refused_with_the_offending_key(tmp: Path) -> None:
    """A table error must name its key, or the fixer has to diff the whole file to find it."""
    for broken, needle in (
        ({"rules": {"review": {"command": "crew commit", "why": "x"}}}, "<workflow>.<stage>.<outcome>"),
        ({"rules": {"build.review.pass": {"command": "crew commit"}}}, "why"),
        ({"rules": {"build.review.pass": {"command": "crew commit", "why": "x",
                                          "human": "also this"}}}, "one of"),
        ({"rules": {"deploy.review.pass": {"command": "crew commit", "why": "x"}}}, "workflow"),
        ({"rules": {}}, "non-empty"),
    ):
        path = tmp / "next-steps.json"
        path.write_text(json.dumps(broken))
        try:
            load_table(path)
        except ValueError as error:
            assert needle in str(error), (needle, error)
        else:
            raise AssertionError(f"{broken} was accepted")


def test_known_stages_are_short_keys_a_skill_can_quote() -> None:
    """A skill quotes `<stage>.<outcome>`; a stage list that needed the workflow would not resolve."""
    stages = known_stages(table())
    assert "review.block" in stages, stages
    assert all(len(stage.split(".")) == 2 for stage in stages), stages
