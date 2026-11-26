#!/usr/bin/env python3
"""Change attribution for `diagnose`: the sign test, the pairing, and the JSON bundle.

`diagnose` answers "did this commit change the score, and if so which surface explains it". Every
claim it emits is gated on evidence — fewer than three paired examples is `insufficient_evidence`,
not an improvement. Suite discovery and path classification live in `evals_sources.py`.
"""
from __future__ import annotations

import collections
import json
import math
import statistics
from pathlib import Path

from evals_query import spans
from evals_report import commit_order, match, summarize_trace
from evals_rows import EvalRow
from evals_sources import classify_paths, evaluator_sources, git, locate_suite

from lib.cli import fail


def sign_test_pvalue(baseline: list[float], candidate: list[float]) -> tuple[float, int]:
    """Exact two-sided sign-test p-value; ties are excluded."""
    wins = sum(c > b for b, c in zip(baseline, candidate))
    losses = sum(c < b for b, c in zip(baseline, candidate))
    pairs = wins + losses
    if not pairs:
        return 1.0, pairs
    tail = sum(math.comb(pairs, index) for index in range(0, min(wins, losses) + 1)) / (2 ** pairs)
    return min(1.0, 2 * tail), pairs


def trace_summary(trace_id: object) -> dict:
    if not trace_id:
        return {"trace_missing": True}
    found = spans([trace_id])
    if not found:
        return {"trace_missing": True}
    llm, tokens, tools, kinds, cycles, context, grounded, errors = summarize_trace(found)
    return {"llm_calls": llm, "input_tokens": tokens, "tools": tools, "queries": kinds,
            "cycles": cycles, "context_cycles": context, "grounded_cycles": grounded,
            "errors": errors}


def rows_by_commit(rows_: list[EvalRow]) -> dict[str, dict]:
    by_commit: dict[str, dict] = collections.defaultdict(dict)
    for row in rows_:
        by_commit[row.commit][(row.example, row.rep)] = row
    return by_commit


def paired_rows(
    rows_: list[EvalRow], baseline: str, candidate: str
) -> tuple[list[tuple[str, object]], list[EvalRow], list[EvalRow]]:
    """The keys both commits scored, and each commit's row for those keys in order."""
    by_commit = rows_by_commit(rows_)
    paired = sorted(
        key for key in (set(by_commit[baseline]) & set(by_commit[candidate]))
        if by_commit[baseline][key].score is not None
        and by_commit[candidate][key].score is not None
    )
    return (paired, [by_commit[baseline][key] for key in paired],
            [by_commit[candidate][key] for key in paired])


def verdict_for(p_value: float, paired: int, comparable: bool, delta: float | None,
                direction: str) -> tuple[str, str | None]:
    """The verdict and its reason, in the order the thresholds apply."""
    threshold = 0.05
    if not comparable:
        return "not_comparable", "evaluator or dataset source changed between commits"
    if paired < 3:
        return "insufficient_evidence", "fewer than three paired examples"
    if p_value >= threshold:
        return "insufficient_evidence", f"sign-test p={p_value:.3g} is not below {threshold}"
    improved = delta > 0 if direction != "minimize" else delta < 0
    return ("improved" if improved else "regressed"), None


def failing_examples(
    paired: list[tuple[str, object]], baseline: str, candidate: str,
    by_commit: dict[str, dict], direction: str, top: int
) -> list[dict]:
    """The worst regressed pairs, ordered by how much worse the candidate scored."""
    ordered = sorted(
        paired, key=lambda key: (
            by_commit[candidate][key].score - by_commit[baseline][key].score
            if direction != "minimize" else
            by_commit[baseline][key].score - by_commit[candidate][key].score
        )
    )
    failing = []
    for key in ordered[:top]:
        before, after = by_commit[baseline][key], by_commit[candidate][key]
        failing.append({"example": after.example, "repetition": after.rep,
                        "baseline_score": before.score, "candidate_score": after.score,
                        "explanation": after.why,
                        "baseline_trace": trace_summary(before.trace),
                        "candidate_trace": trace_summary(after.trace)})
    return failing


def evaluator_report(
    key: tuple[str, str], rows_: list[EvalRow], baseline: str, candidate: str,
    sources: dict, comparable: bool, top: int,
) -> dict:
    """One experiment/evaluator pair: its pairing, verdict, and any regressed examples."""
    experiment, evaluator = key
    paired, before_rows, after_rows = paired_rows(rows_, baseline, candidate)
    baseline_scores = [row.score for row in before_rows]
    candidate_scores = [row.score for row in after_rows]
    direction = next((row.direction for row in rows_ if row.direction), "maximize")
    p_value, non_tie_pairs = sign_test_pvalue(baseline_scores, candidate_scores)
    delta = (statistics.mean(candidate_scores) - statistics.mean(baseline_scores)) if paired else None
    verdict, reason = verdict_for(p_value, len(paired), comparable, delta, direction)
    by_commit = rows_by_commit(rows_)
    failing = ([] if verdict != "regressed"
               else failing_examples(paired, baseline, candidate, by_commit, direction, top))
    return {"experiment": experiment, "evaluator": evaluator,
            "evaluator_source": sources.get(evaluator), "direction": direction,
            "comparable": comparable, "reason": reason, "verdict": verdict,
            "test": "exact_two_sided_sign_test", "p_value": p_value,
            "paired": len(paired), "non_tie_pairs": non_tie_pairs,
            "unpaired_baseline": len(by_commit[baseline]) - len(paired),
            "unpaired_candidate": len(by_commit[candidate]) - len(paired),
            "baseline_mean": statistics.mean(baseline_scores) if paired else None,
            "candidate_mean": statistics.mean(candidate_scores) if paired else None,
            "delta": delta, "failing_examples": failing}


def diagnose_single(rs: list[EvalRow], args) -> int:
    """One commit's lowest scores, with a trace summary per score; makes no delta claim."""
    candidate = next((commit for commit in commit_order(rs) if match(commit, args.baseline)), None)
    if not candidate:
        fail("unknown candidate commit; run `runs`")
    selected = [row for row in rs if row.commit == candidate and row.score is not None]
    bundle = {
        "candidate": candidate,
        "mode": "single",
        "low_scores": [
            {"experiment": row.exp_full, "evaluator": row.ev, "example": row.example,
             "repetition": row.rep, "score": row.score, "direction": row.direction,
             "explanation": row.why, "trace": trace_summary(row.trace)}
            for row in sorted(
                selected,
                key=lambda row: row.score if row.direction != "minimize" else -row.score,
            )[:args.top]
        ],
    }
    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


def compare_commit(rs: list[EvalRow], args) -> tuple[str, str]:
    """The baseline and candidate commits `diagnose` compares, or SystemExit naming the gap."""
    if not args.candidate:
        fail("diagnose requires BASELINE CANDIDATE, or CANDIDATE --single")
    baseline = next((commit for commit in commit_order(rs) if match(commit, args.baseline)), None)
    candidate = next((commit for commit in commit_order(rs) if match(commit, args.candidate)), None)
    if not baseline or not candidate:
        fail("unknown baseline or candidate commit; run `runs`")
    return baseline, candidate


def cmd_diagnose(rs: list[EvalRow], args) -> None:
    """Attribute a score change between two commits, or describe one commit's low scores."""
    if args.single:
        diagnose_single(rs, args)
        return
    baseline, candidate = compare_commit(rs, args)
    selected = [row for row in rs if row.commit in {baseline, candidate}]
    suites = {row.suite for row in selected if row.suite}
    if len(suites) != 1:
        fail(f"diagnose requires one suite, found: {sorted(suites) or 'none'}")
    repo = Path(args.repo).expanduser().resolve()
    suite = locate_suite(repo, next(iter(suites)))
    sources = evaluator_sources(suite)
    changed = git(repo, "diff", "--name-only", baseline, candidate).splitlines()
    source_paths = set()
    for path in sources.values():
        try:
            source_paths.add(str(Path(path).resolve().relative_to(repo)))
        except ValueError:
            continue
    surfaces = classify_paths(changed, suite, source_paths)
    prompt_diff = git(repo, "diff", "--unified=3", baseline, candidate, "--", *surfaces["prompt"])
    grouped = collections.defaultdict(list)
    for row in selected:
        grouped[(row.exp_full, row.ev)].append(row)
    comparable = not surfaces["evaluator"] and not surfaces["dataset"]
    reports = [evaluator_report(key, rows_, baseline, candidate, sources, comparable, args.top)
               for key, rows_ in sorted(grouped.items())]
    bundle = {"baseline": baseline, "candidate": candidate, "suite_id": next(iter(suites)),
              "suite_path": str(suite), "change_surface": surfaces,
              "prompt_diff": prompt_diff, "evaluators": reports}
    print(json.dumps(bundle, indent=2, sort_keys=True))
