#!/usr/bin/env python3
"""Comparison rendering: rows from score documents, the tables, and the per-trace summary.

Everything a person reads on stdout lives here, so the shapes are in one place: `common_prefix`
trims a shared experiment-name prefix, `rows` keeps one row per scored cell, and the `cmd_*`
functions print one section each. The row record itself is `evals_rows.EvalRow`, and
`evals_diagnose.py` builds the JSON bundle for machine consumption.
"""
from __future__ import annotations

import collections
import json
import os
import re
import statistics

from evals_query import spans
from evals_rows import EvalRow, to_row

from lib.cli import fail

COST_NAMES = {"Input Tokens", "Output Tokens", "Tool Calls", "Latency",
              "reported_input_tokens", "reported_output_tokens"}


def common_prefix(values: list[str]) -> str:
    """Remove a shared readable prefix only when all selected names have it."""
    if not values:
        return ""
    prefix = os.path.commonprefix(values)
    boundary = max(prefix.rfind(": "), prefix.rfind(" - "), prefix.rfind("("))
    return prefix[:boundary + 2] if boundary >= 0 else ""


def rows(docs: list[dict]) -> list[EvalRow]:
    """One row per (run, example, repetition, evaluator), keyed so a duplicate score is ignored."""
    seen, out = set(), []
    prefix = common_prefix([d.get("experiment_name", "") for d in docs])
    for d in docs:
        key = (d["experiment_id"], d["example"]["id"], d["task"].get("repetition_index"),
               d["evaluator"]["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(to_row(d, prefix))
    return out


def commit_order(rs: list[EvalRow]) -> list[str]:
    first = {}
    for r in rs:
        first[r.commit] = min(first.get(r.commit, r.time), r.time)
    return sorted(first, key=first.get)  # oldest first


def fmt(values: list[float], name: str) -> str:
    if not values:
        return "-"
    mean = statistics.mean(values)
    text = f"{mean:,.0f}" if abs(mean) >= 10 else f"{mean:.2f}".rstrip("0").rstrip(".")
    return f"{text or '0'}({len(values)})"


def match(commit: str, prefix: str) -> bool:
    return commit.startswith(prefix)


def cmd_runs(rs: list[EvalRow], _args) -> None:
    groups = collections.defaultdict(lambda: {"t": [], "exps": collections.defaultdict(set)})
    for r in rs:
        g = groups[r.commit]
        g["t"].append(r.time)
        g["exps"][r.exp].add((r.example, r.rep))
    for commit in reversed(commit_order(rs)):
        g = groups[commit]
        print(f"{commit}  {min(g['t'])[:16]} -> {max(g['t'])[11:16]}")
        for exp, cells in sorted(g["exps"].items()):
            reps = collections.Counter(example for example, _ in cells)
            print(f"    {exp:<18} {len(reps)} example(s), repetitions per example: "
                  f"{sorted(set(reps.values()))}")


def cmd_compare(rs: list[EvalRow], args) -> None:
    order = commit_order(rs)
    picked = ([c for p in args.commits for c in order if match(c, p)] if args.commits
              else order[-3:])
    if not picked:
        fail("no matching commits; run `runs`")
    print("columns:", " | ".join(picked), "   (mean(n) over examples and repetitions)")
    experiments = sorted({r.exp for r in rs
                          if r.commit in picked and args.exp.lower() in r.exp.lower()})
    for exp in experiments:
        by = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in rs:
            if r.exp == exp and r.commit in picked and r.score is not None:
                by[r.ev][r.commit].append(r.score)
        names = sorted(by, key=lambda name: (name not in COST_NAMES, name.lower()))
        if not names:
            continue
        print(f"\n## {exp}")
        print("  " + "evaluator".ljust(34) + "".join(c.rjust(14) for c in picked))
        for name in names:
            cells = [fmt(by[name].get(c), name) for c in picked]
            print("  " + name.ljust(34) + "".join(x.rjust(14) for x in cells))


def cmd_detail(rs: list[EvalRow], args) -> None:
    order = commit_order(rs)
    commit = next((c for c in reversed(order) if match(c, args.commit)), None)
    if not commit:
        fail("unknown commit")
    for r in sorted((r for r in rs if r.commit == commit and r.score is not None
                     and r.score < args.below and r.ev not in COST_NAMES
                     and args.ev in r.ev),
                    key=lambda r: (r.exp, r.example, r.rep or 0, r.ev)):
        print(f"[{r.exp}] {r.example[:34]} rep{r.rep} {r.ev} = {r.score:.2f}\n"
              f"    {r.why[:args.chars]}")


def summarize_trace(spans_: list[dict]) -> tuple[int, int, dict, dict, int, int, int, list[str]]:
    """Per-trace totals: LLM calls, input tokens, tools, query shapes, cycles, errors."""
    tools, kinds, conversations = collections.Counter(), collections.Counter(), {}
    llm = tokens = 0
    errors = []
    for s in spans_:
        a = s.get("attributes", {})
        if a.get("gen_ai.operation.name") == "chat":
            llm += 1
            tokens += int(a.get("gen_ai.usage.input_tokens") or 0)
            conv = a.get("gen_ai.conversation.id")
            inp = a.get("gen_ai.input.messages", "")
            for found in re.findall(r"<tool_result>Error: (.{0,260}?)(?:</tool_result>|\\n\\n)",
                                    inp.replace("\\\\n", "\\n")):
                message = found.replace("\\n", " ").strip()
                if message not in errors:
                    errors.append(message)
            if conv not in conversations:
                conversations[conv] = ("Prefetched context" in inp,
                                       '"grounding":[' in inp.replace('\\"', '"'))
            continue
        name = (a.get("gen_ai.tool.name") or "?").split(".")[-1]
        tools[name] += 1
        if name == "execute_esql":
            try:
                query = json.loads(a.get("gen_ai.tool.call.arguments", "{}")).get("query", "")
            except ValueError:
                continue
            m = re.match(r"\s*FROM\s+(\S+)", query)
            kinds["from $. view" if m and m.group(1).startswith("$.")
                  else f"from other:{m.group(1) if m else '?'}"] += 1
            if "STATS" in query and " total" in query:
                kinds["spread with total"] += 1
            if "Unknown index" in a.get("gen_ai.tool.call.result", ""):
                kinds["UNKNOWN INDEX"] += 1
    ctx = sum(1 for c, _ in conversations.values() if c)
    grounded = sum(1 for _, g in conversations.values() if g)
    return llm, tokens, dict(tools), dict(kinds), len(conversations), ctx, grounded, errors


def cmd_traces(rs: list[EvalRow], args) -> None:
    order = commit_order(rs)
    commit = next((c for c in reversed(order) if match(c, args.commit)), None)
    if not commit:
        fail("unknown commit")
    traces = {}
    for r in rs:
        if r.commit == commit and r.trace:
            traces[(r.exp, r.example, r.rep)] = r.trace
    for (exp, example, rep), trace in sorted(traces.items(),
                                             key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)):
        llm, tokens, tools, kinds, cycles, ctx, grounded, errors = summarize_trace(spans([trace]))
        print(f"[{exp}] {example[:30]} rep{rep}: {cycles} cycle(s), context in {ctx}, "
              f"grounding in {grounded}; {llm} LLM calls, {tokens:,} input tokens summed over "
              f"calls (cached included)\n    tools {tools}\n    queries {kinds}")
        for message in errors[:4]:
            print(f"    tool error: {message[:230]}")
