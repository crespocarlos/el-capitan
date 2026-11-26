"""Which gates a verify run has, in what order of trust, and what it could not read.

Order: the CI reader (GitHub Actions workflows, from the BASE ref); when the repo has CI the reader
cannot understand (Buildkite, CircleCI, ...) that is said and the order falls through; then the
fenced `gates` block of `AGENTS.md`; `.agent/gates.json` may only ADD gates. When nothing yields a
runnable gate, the nearest `AGENTS.md` of each touched path may still describe checks in prose: they
are surfaced to the builder (`prose_checks`) and never run. See `task_verify_sources.py` for the
readers and `task_gate_prose.py` for the prose.
"""
from __future__ import annotations

from pathlib import Path

from task_gate_prose import prose_checks, unreadable_ci
from task_node_pin import node_pin
from task_verify_sources import (WORKFLOWS, base_has, block_gates, declared_paths, head_changed, override_gates,
                                 read_at, workflow_gates)


def resolve(root: Path, base: str | None) -> dict:
    """`{source, gates, skipped, pin, notes, ci_unreadable, prose_checks}` from the base ref (or the tree)."""
    notes: list[str] = []
    ref = base if base and base_has(root, base) else None
    if base and ref is None:
        notes.append(f"base {base} not found, reading the working tree")
    elif ref and head_changed(root, ref):
        notes.append("declaration changed in PR head, using base")
    where = f"@{ref}" if ref else " (working tree)"
    texts = {p: read_at(root, ref, p) or "" for p in declared_paths(root, ref) if p.startswith(WORKFLOWS)}
    extra = override_gates(read_at(root, ref, ".agent/gates.json") or "")
    gates, skipped = workflow_gates(texts)
    source, unreadable = f"ci-workflow {WORKFLOWS}{where}", []
    if not gates:
        unreadable = unreadable_ci(root, ref)
        notes += [f"CI not readable here ({name})" for name in unreadable]
        gates = block_gates(read_at(root, ref, "AGENTS.md") or "")
        source = f"AGENTS.md gates block{where}" if gates else "none"
    if gates and extra:
        added, drift = merge_extra(gates, extra)
        notes.extend(drift)
        if added:
            gates, source = gates + added, f"{source} + .agent/gates.json additions{where}"
    elif extra:
        gates, source = extra, f".agent/gates.json only{where}"
    source_pin, required = node_pin(lambda path: read_at(root, ref, path))
    return {"source": source, "gates": gates, "skipped": skipped, "notes": notes, "ci_unreadable": unreadable,
            "pin": {"source": source_pin, "required": required},
            "prose_checks": [] if gates else prose_checks(root, ref)}


def merge_extra(gates: list[dict], extra: list[dict]) -> tuple[list[dict], list[str]]:
    """gates.json may ADD gates; it never removes or changes one: a clash keeps the CI command and warns."""
    known = {g["name"]: g for g in gates}
    added: list[dict] = []
    warnings: list[str] = []
    for gate in extra:
        current = known.get(gate["name"])
        if current is None:
            added.append(gate)
        elif current["command"] != gate["command"]:
            warnings.append(f"warning: gate {gate['name']}: .agent/gates.json redefines the command CI runs "
                            f"(CI: {current['command']!r}; gates.json: {gate['command']!r}); using CI")
    return added, warnings
