#!/usr/bin/env python3
"""Compare evaluation runs from Elasticsearch score and trace indices.

  evals-compare.py runs                       list runs (commit groups), newest first
  evals-compare.py compare [COMMIT ...] [--exp TEXT]
                                             one table per experiment, one column per commit
  evals-compare.py detail COMMIT [--below 1] [--ev TEXT] [--chars N]
                                             scores under a threshold, with the judge's explanation
  evals-compare.py traces COMMIT              per trace: tools, query targets, prefetched context
  evals-compare.py diagnose BASELINE CANDIDATE --repo PATH [--json]
                                             read-only change attribution and regression evidence

Defaults: the last 3 commits for `compare`, the first one as the baseline column. COMMIT is a
sha prefix. Generic behavior includes every evaluator. Suite metadata is derived from
score documents and the suite source under --repo. Env: ES_URL (http://localhost:9200),
ES_API_KEY or ES_USER/ES_PASS, ES_SINCE, ES_TRACE_INDEX. Standard library only. Read-only.
"""
import argparse
import base64
import collections
import json
import math
import os
import re
import statistics
import subprocess
import sys
import urllib.request
from pathlib import Path

ES_URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")
TRACE_INDEX = os.environ.get("ES_TRACE_INDEX", "traces-generic.otel-default")
COST_NAMES = {"Input Tokens", "Output Tokens", "Tool Calls", "Latency",
              "reported_input_tokens", "reported_output_tokens"}


def es(path, body):
    headers = {"content-type": "application/json"}
    if os.environ.get("ES_API_KEY"):
        headers["authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
    else:
        auth = base64.b64encode(
            f"{os.environ.get('ES_USER', 'elastic')}:{os.environ.get('ES_PASS', 'changeme')}".encode()
        ).decode()
        headers["authorization"] = f"Basic {auth}"
    request = urllib.request.Request(
        f"{ES_URL}/{path}", data=json.dumps(body).encode(), method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def common_prefix(values):
    """Remove a shared readable prefix only when all selected names have it."""
    if not values:
        return ""
    prefix = os.path.commonprefix(values)
    boundary = max(prefix.rfind(": "), prefix.rfind(" - "), prefix.rfind("("))
    return prefix[:boundary + 2] if boundary >= 0 else ""


def fetch_scores(since):
    query = {"range": {"@timestamp": {"gte": since}}} if since else {"match_all": {}}
    out, after = [], None
    while True:
        body = {
            "size": 5000, "query": query, "sort": [{"@timestamp": "asc"}, {"_doc": "asc"}],
            "_source": ["@timestamp", "experiment_id", "experiment_name", "metadata.git.commit_sha",
                        "example.id", "task.repetition_index", "task.trace_id",
                        "evaluator.name", "evaluator.score", "evaluator.explanation",
                        "evaluator.direction", "metadata.suite_id", "metadata.total_repetitions"],
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
    prefix = common_prefix([d.get("experiment_name", "") for d in docs])
    for d in docs:
        key = (d["experiment_id"], d["example"]["id"], d["task"].get("repetition_index"), d["evaluator"]["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "commit": d["metadata"]["git"]["commit_sha"][:8],
            "time": d["@timestamp"],
            "run": d["experiment_id"],
            "exp": d.get("experiment_name", d["experiment_id"]).removeprefix(prefix)[:34],
            "exp_full": d.get("experiment_name", d["experiment_id"]),
            "example": d["example"]["id"],
            "rep": d["task"].get("repetition_index"),
            "trace": d["task"].get("trace_id"),
            "ev": d["evaluator"]["name"],
            "score": d["evaluator"].get("score"),
            "why": (d["evaluator"].get("explanation") or "").replace("\n", " "),
            "direction": d["evaluator"].get("direction", "maximize"),
            "suite": d.get("metadata", {}).get("suite_id"),
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
        names = sorted(by, key=lambda name: (name not in COST_NAMES, name.lower()))
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
                     and r["ev"] not in COST_NAMES and args.ev in r["ev"]), key=lambda r: (r["exp"], r["example"], r["rep"] or 0, r["ev"])):
        print(f"[{r['exp']}] {r['example'][:34]} rep{r['rep']} {r['ev']} = {r['score']:.2f}\n    {r['why'][:args.chars]}")


def spans(trace_ids):
    body = {"size": 5000, "sort": [{"@timestamp": "asc"}],
            "query": {"bool": {"filter": [{"terms": {"trace_id": trace_ids}},
                                          {"terms": {"attributes.gen_ai.operation.name": ["chat", "execute_tool"]}}]}}}
    return [h["_source"] for h in es(f"{TRACE_INDEX}/_search", body)["hits"]["hits"]]


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


def git(repo, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise SystemExit(f"repository unavailable: {message}")


def locate_suite(repo, suite_id):
    expected = f"@kbn/evals-suite-{suite_id}"
    for manifest in repo.rglob("kibana.jsonc"):
        try:
            text = manifest.read_text()
            identifier = re.search(r'''["']id["']\s*:\s*["']([^"']+)["']''', text)
            if identifier and identifier.group(1) == expected:
                return manifest.parent
        except OSError:
            continue
    raise SystemExit(f"suite source unavailable: {expected} was not found below {repo}")


def evaluator_sources(suite):
    sources = {}
    for path in (suite / "src" / "evaluators").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        try:
            for name in re.findall(r"""name\s*:\s*['"]([^'"]+)['"]""", path.read_text()):
                sources[name] = str(path)
        except OSError:
            continue
    return sources


def classify_paths(paths, suite, evaluator_paths):
    result = {kind: [] for kind in ("prompt", "tool", "retrieval", "evaluator", "dataset", "other")}
    suite_text = str(suite)
    for path in paths:
        lower = path.lower()
        absolute = str((suite.parent.parent.parent.parent / path).resolve())
        if path in evaluator_paths or lower.startswith("src/evaluators/") or "/src/evaluators/" in lower:
            kind = "evaluator"
        elif lower.startswith("src/datasets/") or "/src/datasets/" in lower:
            kind = "dataset"
        elif lower.endswith(".md.text") or any(token in lower for token in ("/instructions", "/prompt", "/skills/")):
            kind = "prompt"
        elif "/tools/" in lower:
            kind = "tool"
        elif any(token in lower for token in ("/retrieval/", "indicator_", "search_embedding")):
            kind = "retrieval"
        elif absolute.startswith(suite_text):
            kind = "other"
        else:
            kind = "other"
        result[kind].append(path)
    return result


def sign_test_pvalue(baseline, candidate):
    """Exact two-sided sign-test p-value; ties are excluded."""
    wins = sum(c > b for b, c in zip(baseline, candidate))
    losses = sum(c < b for b, c in zip(baseline, candidate))
    pairs = wins + losses
    if not pairs:
        return 1.0, pairs
    tail = sum(math.comb(pairs, index) for index in range(0, min(wins, losses) + 1)) / (2 ** pairs)
    return min(1.0, 2 * tail), pairs


def trace_summary(trace_id):
    if not trace_id:
        return {"trace_missing": True}
    found = spans([trace_id])
    if not found:
        return {"trace_missing": True}
    llm, tokens, tools, kinds, cycles, context, grounded, errors = summarize_trace(found)
    return {"llm_calls": llm, "input_tokens": tokens, "tools": tools, "queries": kinds,
            "cycles": cycles, "context_cycles": context, "grounded_cycles": grounded, "errors": errors}


def cmd_diagnose(rs, args):
    if args.single:
        candidate = next((commit for commit in commit_order(rs) if match(commit, args.baseline)), None)
        if not candidate:
            raise SystemExit("unknown candidate commit; run `runs`")
        selected = [row for row in rs if row["commit"] == candidate and row["score"] is not None]
        bundle = {
            "candidate": candidate,
            "mode": "single",
            "low_scores": [
                {"experiment": row["exp_full"], "evaluator": row["ev"], "example": row["example"],
                 "repetition": row["rep"], "score": row["score"], "direction": row["direction"],
                 "explanation": row["why"], "trace": trace_summary(row["trace"])}
                for row in sorted(
                    selected,
                    key=lambda row: row["score"] if row["direction"] != "minimize" else -row["score"],
                )[:args.top]
            ],
        }
        print(json.dumps(bundle, indent=2, sort_keys=True))
        return
    if not args.candidate:
        raise SystemExit("diagnose requires BASELINE CANDIDATE, or CANDIDATE --single")
    baseline = next((commit for commit in commit_order(rs) if match(commit, args.baseline)), None)
    candidate = next((commit for commit in commit_order(rs) if match(commit, args.candidate)), None)
    if not baseline or not candidate:
        raise SystemExit("unknown baseline or candidate commit; run `runs`")
    selected = [row for row in rs if row["commit"] in {baseline, candidate}]
    suites = {row["suite"] for row in selected if row["suite"]}
    if len(suites) != 1:
        raise SystemExit(f"diagnose requires one suite, found: {sorted(suites) or 'none'}")
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
        grouped[(row["exp_full"], row["ev"])].append(row)
    reports = []
    evaluator_changed = bool(surfaces["evaluator"])
    dataset_changed = bool(surfaces["dataset"])
    for (experiment, evaluator), rows_ in sorted(grouped.items()):
        by_commit = collections.defaultdict(dict)
        for row in rows_:
            by_commit[row["commit"]][(row["example"], row["rep"])] = row
        paired = sorted(
            key for key in (set(by_commit[baseline]) & set(by_commit[candidate]))
            if by_commit[baseline][key]["score"] is not None
            and by_commit[candidate][key]["score"] is not None
        )
        baseline_scores = [by_commit[baseline][key]["score"] for key in paired]
        candidate_scores = [by_commit[candidate][key]["score"] for key in paired]
        direction = next((row["direction"] for row in rows_ if row["direction"]), "maximize")
        comparable = not evaluator_changed and not dataset_changed
        p_value, non_tie_pairs = sign_test_pvalue(baseline_scores, candidate_scores)
        delta = (statistics.mean(candidate_scores) - statistics.mean(baseline_scores)) if paired else None
        threshold = 0.05
        if not comparable:
            verdict = "not_comparable"
            reason = "evaluator or dataset source changed between commits"
        elif len(paired) < 3:
            verdict = "insufficient_evidence"
            reason = "fewer than three paired examples"
        elif p_value >= threshold:
            verdict = "insufficient_evidence"
            reason = f"sign-test p={p_value:.3g} is not below {threshold}"
        else:
            improved = delta > 0 if direction != "minimize" else delta < 0
            verdict = "improved" if improved else "regressed"
            reason = None
        failing = []
        if verdict == "regressed":
            ordered = sorted(
                paired, key=lambda key: (
                    by_commit[candidate][key]["score"] - by_commit[baseline][key]["score"]
                    if direction != "minimize" else
                    by_commit[baseline][key]["score"] - by_commit[candidate][key]["score"]
                )
            )
            for key in ordered[:args.top]:
                before, after = by_commit[baseline][key], by_commit[candidate][key]
                failing.append({"example": after["example"], "repetition": after["rep"],
                                "baseline_score": before["score"], "candidate_score": after["score"],
                                "explanation": after["why"], "baseline_trace": trace_summary(before["trace"]),
                                "candidate_trace": trace_summary(after["trace"])})
        reports.append({"experiment": experiment, "evaluator": evaluator,
                        "evaluator_source": sources.get(evaluator), "direction": direction,
                        "comparable": comparable, "reason": reason, "verdict": verdict,
                        "test": "exact_two_sided_sign_test", "p_value": p_value,
                        "paired": len(paired), "non_tie_pairs": non_tie_pairs,
                        "unpaired_baseline": len(by_commit[baseline]) - len(paired),
                        "unpaired_candidate": len(by_commit[candidate]) - len(paired),
                        "baseline_mean": statistics.mean(baseline_scores) if paired else None,
                        "candidate_mean": statistics.mean(candidate_scores) if paired else None,
                        "delta": delta, "failing_examples": failing})
    bundle = {"baseline": baseline, "candidate": candidate, "suite_id": next(iter(suites)),
              "suite_path": str(suite), "change_surface": surfaces,
              "prompt_diff": prompt_diff, "evaluators": reports}
    print(json.dumps(bundle, indent=2, sort_keys=True) if args.json else json.dumps(bundle, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=os.environ.get("ES_SINCE"), help="ISO time; only scores after it")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("runs")
    p = sub.add_parser("compare"); p.add_argument("commits", nargs="*"); p.add_argument("--exp", default="", help="only experiments whose name contains this")
    p = sub.add_parser("detail"); p.add_argument("commit"); p.add_argument("--below", type=float, default=1.0); p.add_argument("--chars", type=int, default=420); p.add_argument("--ev", default="", help="only evaluators whose name contains this")
    p = sub.add_parser("traces"); p.add_argument("commit")
    p = sub.add_parser("diagnose"); p.add_argument("baseline"); p.add_argument("candidate", nargs="?")
    p.add_argument("--repo", required=True, help="read-only Kibana checkout")
    p.add_argument("--top", type=int, default=3, help="trace examples per regressed evaluator")
    p.add_argument("--json", action="store_true")
    p.add_argument("--single", action="store_true", help="analyze low scores for one commit; no delta claim")
    args = parser.parse_args()
    rs = rows(fetch_scores(args.since))
    if not rs:
        sys.exit("no scores found")
    {"runs": cmd_runs, "compare": cmd_compare, "detail": cmd_detail,
     "traces": cmd_traces, "diagnose": cmd_diagnose}[args.cmd](rs, args)


if __name__ == "__main__":
    main()
