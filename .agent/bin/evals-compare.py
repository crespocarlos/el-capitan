#!/usr/bin/env python3
"""Compare sigevents eval runs from the local `.evaluation-scores` index and its traces.

  evals-compare.py runs                       list runs (commit groups), newest first
  evals-compare.py compare [COMMIT ...] [--exp TEXT] [--all]
                                             one table per experiment, one column per commit
  evals-compare.py detail COMMIT [--below 1] [--ev TEXT] [--chars N]
                                             scores under a threshold, with the judge's explanation
  evals-compare.py traces COMMIT              per trace: tools, query targets, prefetched context

Defaults: the last 3 commits for `compare`, the first one as the baseline column. COMMIT is a
sha prefix. Env: ES_URL (http://localhost:9200), ES_USER/ES_PASS (elastic/changeme), ES_SINCE.
Standard library only. Read-only.
"""
import argparse
import base64
import collections
import json
import os
import re
import statistics
import sys
import urllib.request

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
AUTH = base64.b64encode(f"{os.environ.get('ES_USER', 'elastic')}:{os.environ.get('ES_PASS', 'changeme')}".encode()).decode()
TRACES = "traces-generic.otel-default"
COST = ["Input Tokens", "Output Tokens", "Tool Calls", "Latency"]
QUALITY_FIRST = [
    "trajectory", "execute_esql_grounding", "topology_correctness", "grouping_correctness",
    "severity_exact", "severity_calibration", "scenario_criteria", "evidence_description_quality",
    "narrative_fields_quality", "status_correctness", "evidence_collection", "confirmation_alignment",
    "confirmed_evidences", "signal_evidence_consistency", "continuation_routing",
    "continuation_stability", "continuation_severity_stability", "continuation_topology_stability",
    "event_id_provenance",
]
LOW_BETTER = {"Latency"}


def es(path, body):
    request = urllib.request.Request(
        f"{ES_URL}/{path}", data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json", "authorization": f"Basic {AUTH}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def short_experiment(name):
    name = name.replace("sigevents: ", "")
    for needle, label in (("same rules", "CONT same-rules"), ("topology-related", "CONT topology"), ("inactive", "CONT inactive")):
        if "continuation" in name and needle in name:
            return label
    return "DISCOVERY" if name.startswith("Discovery (") else name[:34]


def fetch_scores(since):
    query = {"range": {"@timestamp": {"gte": since}}} if since else {"match_all": {}}
    out, after = [], None
    while True:
        body = {
            "size": 5000, "query": query, "sort": [{"@timestamp": "asc"}, {"_doc": "asc"}],
            "_source": ["@timestamp", "experiment_id", "experiment_name", "metadata.git.commit_sha",
                        "example.id", "task.repetition_index", "task.trace_id",
                        "evaluator.name", "evaluator.score", "evaluator.explanation"],
        }
        if after:
            body["search_after"] = after
        hits = es(".evaluation-scores*/_search", body)["hits"]["hits"]
        if not hits:
            return out
        out += [hit["_source"] for hit in hits]
        after = hits[-1]["sort"]
        if len(hits) < 5000:
            return out


def rows(docs):
    seen, out = set(), []
    for d in docs:
        key = (d["experiment_id"], d["example"]["id"], d["task"].get("repetition_index"), d["evaluator"]["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "commit": d["metadata"]["git"]["commit_sha"][:8],
            "time": d["@timestamp"],
            "run": d["experiment_id"],
            "exp": short_experiment(d["experiment_name"]),
            "example": d["example"]["id"],
            "rep": d["task"].get("repetition_index"),
            "trace": d["task"].get("trace_id"),
            "ev": d["evaluator"]["name"],
            "score": d["evaluator"].get("score"),
            "why": (d["evaluator"].get("explanation") or "").replace("\n", " "),
        })
    return out


def commit_order(rs):
    first = {}
    for r in rs:
        first[r["commit"]] = min(first.get(r["commit"], r["time"]), r["time"])
    return sorted(first, key=first.get)  # oldest first


def fmt(values, name):
    if not values:
        return "-"
    mean = statistics.mean(values)
    text = f"{mean:,.0f}" if abs(mean) >= 10 else f"{mean:.2f}".rstrip("0").rstrip(".")
    return f"{text or '0'}({len(values)})"


def match(commit, prefix):
    return commit.startswith(prefix)


def cmd_runs(rs, _args):
    groups = collections.defaultdict(lambda: {"t": [], "exps": collections.defaultdict(set)})
    for r in rs:
        g = groups[r["commit"]]
        g["t"].append(r["time"])
        g["exps"][r["exp"]].add((r["example"], r["rep"]))
    for commit in reversed(commit_order(rs)):
        g = groups[commit]
        print(f"{commit}  {min(g['t'])[:16]} -> {max(g['t'])[11:16]}")
        for exp, cells in sorted(g["exps"].items()):
            reps = collections.Counter(example for example, _ in cells)
            print(f"    {exp:<18} {len(reps)} example(s), repetitions per example: {sorted(set(reps.values()))}")


def cmd_compare(rs, args):
    order = commit_order(rs)
    picked = [c for p in args.commits for c in order if match(c, p)] if args.commits else order[-3:]
    if not picked:
        sys.exit("no matching commits; run `runs`")
    print("columns:", " | ".join(picked), "   (mean(n) over examples and repetitions)")
    experiments = sorted({r["exp"] for r in rs if r["commit"] in picked and args.exp.lower() in r["exp"].lower()})
    for exp in experiments:
        by = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in rs:
            if r["exp"] == exp and r["commit"] in picked and r["score"] is not None:
                by[r["ev"]][r["commit"]].append(r["score"])
        names = [n for n in COST + QUALITY_FIRST if n in by]
        names += sorted(n for n in by if n not in names) if args.all else []
        if not names:
            continue
        print(f"\n## {exp}")
        print("  " + "evaluator".ljust(34) + "".join(c.rjust(14) for c in picked))
        for name in names:
            cells = [fmt(by[name].get(c), name) for c in picked]
            print("  " + name.ljust(34) + "".join(x.rjust(14) for x in cells))


def cmd_detail(rs, args):
    order = commit_order(rs)
    commit = next((c for c in reversed(order) if match(c, args.commit)), None)
    if not commit:
        sys.exit("unknown commit")
    for r in sorted((r for r in rs if r["commit"] == commit and r["score"] is not None and r["score"] < args.below
                     and r["ev"] not in COST and args.ev in r["ev"]), key=lambda r: (r["exp"], r["example"], r["rep"] or 0, r["ev"])):
        print(f"[{r['exp']}] {r['example'][:34]} rep{r['rep']} {r['ev']} = {r['score']:.2f}\n    {r['why'][:args.chars]}")


def spans(trace_ids):
    body = {"size": 5000, "sort": [{"@timestamp": "asc"}],
            "query": {"bool": {"filter": [{"terms": {"trace_id": trace_ids}},
                                          {"terms": {"attributes.gen_ai.operation.name": ["chat", "execute_tool"]}}]}}}
    return [h["_source"] for h in es(f"{TRACES}/_search", body)["hits"]["hits"]]


def summarize_trace(spans_):
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
            for found in re.findall(r"<tool_result>Error: (.{0,260}?)(?:</tool_result>|\\n\\n)", inp.replace("\\\\n", "\\n")):
                message = found.replace("\\n", " ").strip()
                if message not in errors:
                    errors.append(message)
            if conv not in conversations:
                conversations[conv] = ("Prefetched context" in inp, '"grounding":[' in inp.replace('\\"', '"'))
            continue
        name = (a.get("gen_ai.tool.name") or "?").split(".")[-1]
        tools[name] += 1
        if name == "execute_esql":
            try:
                query = json.loads(a.get("gen_ai.tool.call.arguments", "{}")).get("query", "")
            except ValueError:
                continue
            m = re.match(r"\s*FROM\s+(\S+)", query)
            kinds["from $. view" if m and m.group(1).startswith("$.") else f"from other:{m.group(1) if m else '?'}"] += 1
            if "STATS" in query and " total" in query:
                kinds["spread with total"] += 1
            if "Unknown index" in a.get("gen_ai.tool.call.result", ""):
                kinds["UNKNOWN INDEX"] += 1
    ctx = sum(1 for c, _ in conversations.values() if c)
    grounded = sum(1 for _, g in conversations.values() if g)
    return llm, tokens, dict(tools), dict(kinds), len(conversations), ctx, grounded, errors


def cmd_traces(rs, args):
    order = commit_order(rs)
    commit = next((c for c in reversed(order) if match(c, args.commit)), None)
    if not commit:
        sys.exit("unknown commit")
    traces = {}
    for r in rs:
        if r["commit"] == commit and r["trace"]:
            traces[(r["exp"], r["example"], r["rep"])] = r["trace"]
    for (exp, example, rep), trace in sorted(traces.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)):
        llm, tokens, tools, kinds, cycles, ctx, grounded, errors = summarize_trace(spans([trace]))
        print(f"[{exp}] {example[:30]} rep{rep}: {cycles} cycle(s), context in {ctx}, grounding in {grounded}; "
              f"{llm} LLM calls, {tokens:,} input tokens summed over calls (cached included)\n    tools {tools}\n    queries {kinds}")
        for message in errors[:4]:
            print(f"    tool error: {message[:230]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=os.environ.get("ES_SINCE"), help="ISO time; only scores after it")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("runs")
    p = sub.add_parser("compare"); p.add_argument("commits", nargs="*"); p.add_argument("--all", action="store_true"); p.add_argument("--exp", default="", help="only experiments whose name contains this")
    p = sub.add_parser("detail"); p.add_argument("commit"); p.add_argument("--below", type=float, default=1.0); p.add_argument("--chars", type=int, default=420); p.add_argument("--ev", default="", help="only evaluators whose name contains this")
    p = sub.add_parser("traces"); p.add_argument("commit")
    args = parser.parse_args()
    rs = rows(fetch_scores(args.since))
    if not rs:
        sys.exit("no scores found")
    {"runs": cmd_runs, "compare": cmd_compare, "detail": cmd_detail, "traces": cmd_traces}[args.cmd](rs, args)


if __name__ == "__main__":
    main()
