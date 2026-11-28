"""Every crew agent, and the skills and rules that do work, reach `references/lookups.md`: by their own
pointer sentence, or through a carrier their dispatch provably delivers (the contract appended to a
reviewer persona or spec critic, the protocol an explorer reads, the rule the main session loads)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".cursor" / "agents"
REFS = ".cursor/agents/references/"
POINTER = re.compile(r"(?m)^Lookups: follow `~/\.cursor/agents/references/lookups\.md` before you search for code")
FENCE = re.compile(r"(?ms)^(`{3,}|~{3,}).*?^\1")
PERSONAS = ("reviewer-adversarial", "reviewer-architecture", "reviewer-code-quality", "reviewer-product-flow",
            "reviewer-prompt-quality")
# Agent -> (carrier holding the pointer, the dispatch or packaging file that delivers it, the text naming it there).
CARRIERS = {
    **{name: (REFS + "reviewer-reads.md", "src/crew/review/assemble_inputs.py", "reviewer-reads.md")
       for name in PERSONAS},
    **{name: (REFS + "critic-contract.md", ".cursor/agents/crew-specwriter.md", "references/critic-contract.md")
       for name in ("specwriter-adversarial", "specwriter-scope")},
    **{name: (REFS + "explorer-protocol.md", f".cursor/agents/{name}.md", "references/explorer-protocol.md")
       for name in ("reviewer-explorer", "specwriter-explorer")},
    # Runs inline in the main session, which loads the router on every start.
    "crew-reviewer": ("rules/crew-router.mdc", ".claude/CLAUDE.md", "rules/crew-router.mdc"),
}
# Skills and rules that do work and carry the pointer themselves.
OWN_POINTER = (".cursor/skills/spec-writing/SKILL.md", "rules/crew-router.mdc", "rules/crew-explorer-conventions.mdc")


def has_pointer(relative: str) -> bool:
    """The pointer sentence outside fenced blocks, where an example would not reach the reader."""
    return bool(POINTER.search(FENCE.sub("", (ROOT / relative).read_text(encoding="utf-8"))))


def test_lookups_reach_every_agent_skill_and_rule() -> None:
    agents = {path.stem for path in AGENTS.glob("*.md")}
    assert not set(CARRIERS) - agents, f"carrier rows for missing agents: {sorted(set(CARRIERS) - agents)}"
    missing = [name for name in sorted(agents - set(CARRIERS)) if not has_pointer(f".cursor/agents/{name}.md")]
    missing += [path for path in OWN_POINTER if not has_pointer(path)]
    for name, (carrier, witness, needle) in sorted(CARRIERS.items()):
        if not has_pointer(carrier):
            missing.append(f"{name} (via {carrier})")
        if needle not in (ROOT / witness).read_text(encoding="utf-8"):
            missing.append(f"{name}: {witness} does not deliver {carrier}")
    assert not missing, f"no lookups pointer: {', '.join(missing)}"
    assert (ROOT / REFS / "lookups.md").is_file()
