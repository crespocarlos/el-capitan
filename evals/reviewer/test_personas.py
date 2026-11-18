#!/usr/bin/env python3
"""Contract checks for the reviewer persona files and the shared reviewer contract.

Every persona is dispatched with the same output contract and read by the same consolidator, so the
parts that contract depends on must exist exactly once. They were copied into five persona files
before, and the copies drifted: `[concern]` was in the tool's allowlist and in `consolidation.md` but
in no persona, the fix field had three spellings (`Fix:`, `Fix/Response:`, `Suggested fix:`), two
personas carried a copy-pasted duplicate line, and one had no output format at all.

The shared contract file is composed into each prompt by `evals/reviewer/run.py` and by the crew
dispatcher, so these checks cover both halves: what the contract must define, and what a persona must
not restate.
"""
from __future__ import annotations

import re
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / ".cursor" / "agents"
CONTRACT = AGENTS / "references" / "reviewer-contract.md"
PERSONAS = [
    "reviewer-adversarial",
    "reviewer-architecture",
    "reviewer-code-quality",
    "reviewer-product-flow",
    "reviewer-prompt-quality",
]
# Labels the tool accepts, from `LABELS` in review-findings.py.
LABELS = ["blocking", "attention", "nit", "needs more info", "concern"]


def flat(text: str) -> str:
    """Collapse wrapping so a check tests wording rather than line breaks."""
    return " ".join(text.split())


def persona(name: str) -> str:
    return (AGENTS / f"{name}.md").read_text()


def load_mcp_servers() -> dict:
    """The MCP allowlist: the authority on which tool ids an agent file may name."""
    import json

    tools_json = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "tools.json"
    return json.loads(tools_json.read_text())["mcp_servers"]


def granted_tools_line(name: str) -> str:
    """The persona's `tools:` frontmatter line, which Claude Code enforces."""
    found = re.search(r"^tools:.*$", persona(name), re.M)
    assert found, f"{name} has no `tools:` frontmatter"
    return found.group(0)


def check_the_contract_defines_every_label() -> None:
    """The contract is the only place labels are defined, so it must define all of them."""
    text = flat(CONTRACT.read_text())
    for label in LABELS:
        assert f"[{label}]" in text, f"the shared contract never names [{label}]"


def check_the_contract_scopes_concern_to_plan_reviews() -> None:
    """`[concern]` replaces `[attention]` only in a spec or idea review."""
    around = re.search(r".{0,300}\[concern\].{0,500}", flat(CONTRACT.read_text()))
    assert around, "the shared contract does not mention [concern]"
    window = around.group(0).lower()
    assert "spec" in window and "idea" in window, "[concern] is not scoped to spec and idea reviews"


def check_the_contract_owns_the_abstention_line() -> None:
    """The orchestrator matches this text exactly; one copy means one wording."""
    text = flat(CONTRACT.read_text())
    assert "Nothing in my lane for this artifact." in text
    assert "### Verdict: no findings" in text


def check_the_contract_owns_the_two_finding_rules() -> None:
    """The rules the corpus showed personas never following unless told, stated once."""
    text = flat(CONTRACT.read_text()).lower()
    assert "one issue per finding" in text, "the contract does not require one issue per finding"
    assert "pre-exist" in text, "the contract does not ask whether the defect pre-exists"


def check_the_contract_fixes_one_spelling_of_the_fix_field() -> None:
    """The consolidator records a `Fix:` field; a different spelling loses the fix."""
    text = flat(CONTRACT.read_text())
    assert "Fix:" in text, "the contract does not define the fix field"
    assert "Hunk: <id>" not in text, "two hunk citation formats exist; keep the (h7) one"


def check_personas_do_not_restate_the_shared_contract() -> None:
    """A copy is what drifts. Personas point at the contract instead of restating it.

    The label list and the abstention wording are the two that drift most, so both are checked by
    their exact phrases rather than by topic.
    """
    restatements = {
        "the abstention sentence": "Nothing in my lane for this artifact.",
        "the verdict line": "### Verdict: no findings",
        "the one-issue rule": "One issue per finding.",
        "the pre-existing rule": "pre-exists this change",
        "[concern] definition": "Replaces `[attention]`",
    }
    for name in PERSONAS:
        text = flat(persona(name))
        for label, phrase in restatements.items():
            assert phrase not in text, f"{name} restates {label}; it belongs in the shared contract"


def check_fix_field_is_the_one_the_gate_accepts() -> None:
    """A spelling the gate rejects is a review whose correct output fails. One spelling, in the contract."""
    contract = CONTRACT.read_text()
    assert "`Fix:`" in contract or "Fix:" in contract, "the contract does not define the fix field"
    for name in PERSONAS:
        text = persona(name)
        assert "Fix/Response:" not in text, f"{name} still documents `Fix/Response:`"
        assert "Suggested fix:" not in text, f"{name} still documents `Suggested fix:`"


def check_no_duplicated_directive_line() -> None:
    """A copy-paste duplicate is the redundancy this pipeline flags in other prompts."""
    for name in PERSONAS:
        lines = [line.strip() for line in persona(name).splitlines() if line.strip()]
        repeated = [line for index, line in enumerate(lines[1:], 1) if line == lines[index - 1]]
        assert not repeated, f"{name} repeats a line back to back: {repeated[0]!r}"


def check_shared_sections_present() -> None:
    """Each persona needs the lens-specific sections the dispatch contract depends on."""
    required = {
        "severity or labels": r"^## Severity|^<severity>",
        "label mapping": r"^## Label mapping",
        "output format": r"^## Output format|^<output_format>",
        "coverage mapping": r"^## Coverage mapping",
        "pointer to the contract": r"reviewer-contract\.md",
    }
    for name in PERSONAS:
        text = persona(name)
        missing = [label for label, pattern in required.items() if not re.search(pattern, text, re.M)]
        assert not missing, f"{name} is missing: {', '.join(missing)}"


def check_every_persona_can_be_composed_by_the_harness() -> None:
    """The harness composes lens + contract; if either half is missing the prompt is incomplete."""
    import importlib.util

    harness = Path(__file__).resolve().parent / "run.py"
    spec = importlib.util.spec_from_file_location("reviewer_run_for_contract", harness)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contract = flat(module.load_shared_contract())
    assert "Nothing in my lane for this artifact." in contract, "composed contract is missing the abstention line"
    for name in PERSONAS:
        composed = flat(module.load_persona_prompt(name)).lower()
        assert "nothing in my lane for this artifact." in composed, f"{name} prompt lacks the contract"
        assert "[concern]" in composed, f"{name} prompt lacks the [concern] label"
        # The rule appears as the `## One issue per finding` heading; assert the wording, not a period.
        assert "one issue per finding" in composed, f"{name} prompt lacks the one-issue rule"
        assert "pre-exists" in composed, f"{name} prompt lacks the pre-existing rule"


def check_budget_matches_the_packaging_contract() -> None:
    """The fetch budget is stated in exactly two places — the contract and context-tiers.md — and
    they must agree. A persona file stating its own number is drift waiting to happen."""
    tiers = flat((AGENTS / "crew-reviewer" / "references" / "context-tiers.md").read_text())
    declared = re.search(r"up to \*\*(\d+) targeted fetch calls\*\*", tiers)
    assert declared, "context-tiers.md no longer states the fetch budget"
    budget = declared.group(1)
    contract = flat(CONTRACT.read_text())
    found = re.search(r"Tool-call budget: ≤(\d+)", contract)
    assert found, "the shared contract has no numeric tool budget"
    assert found.group(1) == budget, f"the contract says ≤{found.group(1)}; context-tiers.md says ≤{budget}"
    for name in PERSONAS:
        assert not re.search(r"Tool-call budget: ≤\d+", persona(name)), (
            f"{name} restates the budget instead of pointing at the contract"
        )


def check_context_package_states_the_hunk_requirement() -> None:
    """Personas cite hunk ids only if told in the package; the citation format must be one format."""
    tiers = flat((AGENTS / "crew-reviewer" / "references" / "context-tiers.md").read_text())
    assert "(h7)" in tiers, "context-tiers.md does not show the hunk citation format"
    assert "Hunk reference" in tiers, "context-tiers.md does not name the hunk reference section"
    orchestrator = (AGENTS / "crew-reviewer.md").read_text()
    assert "## Hunk reference" in orchestrator, "crew-reviewer.md does not name the hunk reference section"
    assert "reviewer-contract.md" in orchestrator, "crew-reviewer.md does not wire the shared contract in"
    assert "Hunk: <id>" not in tiers, "two hunk citation formats exist; keep the (h7) one"


def check_every_declared_mcp_tool_is_named_in_the_contract() -> None:
    """A tool granted in frontmatter but named in no prose is a tool the persona never learns to use.

    All ten MCP tools were granted and named in no persona file. Cursor ignores `tools:` and inherits
    every parent tool, so for a Cursor subagent the frontmatter grants nothing and only prose tells
    it what it holds.
    """
    servers = load_mcp_servers()
    contract = CONTRACT.read_text()
    missing = [
        f"{server}__{tool}"
        for server, tools in servers.items()
        for tool in tools
        if tool not in contract
    ]
    assert not missing, f"declared MCP tools named in no contract prose: {', '.join(missing)}"


def check_granted_tools_match_what_the_prose_tells_them_to_use() -> None:
    """The reverse direction: prose must not name a tool the persona is not granted.

    Claude Code reads `tools:` and enforces it. A contract that says "call `auth_status` when a call
    is rejected" while the persona's frontmatter omits `auth_status` is an instruction to call a tool
    it does not have — a contradiction between two loaded files.
    """
    servers = load_mcp_servers()
    all_tools = {tool for tools in servers.values() for tool in tools}
    for name in PERSONAS:
        granted = set(re.findall(r"mcp__[\w-]+__(\w+)", granted_tools_line(name)))
        absent = sorted(all_tools - granted)
        assert not absent, f"{name} is told to use tools it does not grant: {', '.join(absent)}"
        contract = CONTRACT.read_text()
        named = {tool for tool in granted if tool in contract}
        assert named, f"{name} grants no tool the contract explains"


def check_personas_grant_the_same_toolset() -> None:
    """Five byte-identical `tools:` lines, one drifted set. Same contract, same tools."""
    lines = {name: granted_tools_line(name) for name in PERSONAS}
    first = next(iter(lines.values()))
    differing = [name for name, line in lines.items() if line != first]
    assert not differing, f"{', '.join(differing)} grant a different toolset than the others"


def check_docs_rule_is_available_without_a_trigger() -> None:
    """The docs rule must exist in the contract, not only in the orchestrator's injection sentence.

    The orchestrator injects "this artifact has ES|QL" conditionally. The rule that a persona holds a
    docs server and must verify with it belongs in the contract, or it is absent exactly when a
    persona would need it.
    """
    contract = flat(CONTRACT.read_text())
    assert "search_internal_docs" in contract, "the contract does not name the docs search tool"
    assert "get_internal_document_by_url" in contract, "the contract does not name the docs fetch tool"
    assert "unverified" in contract.lower(), "the contract has no unverifiable-docs fallback"
    orchestrator = flat((AGENTS / "crew-reviewer.md").read_text())
    assert "reviewer-contract.md" in orchestrator, (
        "crew-reviewer.md must point at the contract rather than restating the docs rule alone"
    )


def check_search_order_is_semantic_first_and_harness_neutral() -> None:
    """Semantic search first, and the instruction must not name Cursor-only tools as the only path."""
    contract = flat(CONTRACT.read_text())
    assert "Semantic search first" in contract, "the contract does not put semantic search first"
    assert "map_symbols_by_query" in contract, "the contract does not name the primary symbol lookup"
    assert "harness" in contract.lower(), (
        "the contract has no harness-neutral fallback, so a non-Cursor harness has no instruction"
    )


CHECKS = [
    check_the_contract_defines_every_label,
    check_the_contract_scopes_concern_to_plan_reviews,
    check_the_contract_owns_the_abstention_line,
    check_the_contract_owns_the_two_finding_rules,
    check_the_contract_fixes_one_spelling_of_the_fix_field,
    check_personas_do_not_restate_the_shared_contract,
    check_fix_field_is_the_one_the_gate_accepts,
    check_no_duplicated_directive_line,
    check_shared_sections_present,
    check_every_persona_can_be_composed_by_the_harness,
    check_budget_matches_the_packaging_contract,
    check_context_package_states_the_hunk_requirement,
    check_every_declared_mcp_tool_is_named_in_the_contract,
    check_granted_tools_match_what_the_prose_tells_them_to_use,
    check_personas_grant_the_same_toolset,
    check_docs_rule_is_available_without_a_trigger,
    check_search_order_is_semantic_first_and_harness_neutral,
]


def main() -> int:
    failures = 0
    for check in CHECKS:
        try:
            check()
        except AssertionError as error:
            failures += 1
            print(f"FAIL: {check.__name__}: {error}")
        else:
            print(f"pass: {check.__name__}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
