#!/usr/bin/env python3
"""Inspect evaluation documents in Elasticsearch. Read-only; exits 2 when ES is unavailable.

Subcommands: `latest`, `scores <experiment>`, `failures <experiment>`, `trace <experiment>
<example>`, `ki`, `flips <a> <b>`, `cluster <experiment>...`. Every subcommand prints JSON on stdout
and diagnostics on stderr, so it is the machine-readable half of the evals tooling.
"""
from __future__ import annotations

import argparse
import base64
import collections
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.output import DEFAULT_MAX_CHARS, bounded_json  # noqa: E402

URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")
MAX_DOCS = 500


def search(index: str, query: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if os.environ.get("ES_API_KEY"):
        headers["Authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
    elif os.environ.get("ES_USER"):
        token = base64.b64encode(
            f"{os.environ['ES_USER']}:{os.environ.get('ES_PASS', '')}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(
        f"{URL}/{index}/_search", data=json.dumps(query).encode(), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
        print(f"Elasticsearch unavailable: {error}", file=sys.stderr)
        raise SystemExit(2)


def docs(experiment: str | None = None, metric: str | None = None) -> list[dict]:
    clauses = []
    if experiment:
        clauses.append({"term": {"experiment_id": experiment}})
    if metric:
        clauses.append({"term": {"evaluator.name": metric}})
    response = search(".evaluation-scores*", {"size": MAX_DOCS, "query": {"bool": {"must": clauses}}})
    return [hit["_source"] for hit in response["hits"]["hits"]]


def failed(experiment: str) -> set[tuple[str | None, str | None]]:
    return {
        (doc.get("example", {}).get("id"), doc.get("evaluator", {}).get("name"))
        for doc in docs(experiment)
        if doc.get("evaluator", {}).get("score", 1) < 1
    }


def add_common(parser: argparse.ArgumentParser) -> None:
    """The output bounds every subcommand shares, so a large result cannot flood a caller."""
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"bound the JSON (default {DEFAULT_MAX_CHARS})")
    parser.add_argument("--limit", type=int, default=None, help="show at most N result rows")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("latest", "most recent score documents"),
                            ("ki", "knowledge-indicator events")):
        add_common(commands.add_parser(name, help=help_text))
    scores = commands.add_parser("scores", help="mean score per evaluator")
    scores.add_argument("experiment")
    add_common(scores)
    failures = commands.add_parser("failures", help="documents scoring below 1")
    failures.add_argument("experiment")
    failures.add_argument("--metric")
    add_common(failures)
    trace = commands.add_parser("trace", help="one example's documents")
    trace.add_argument("experiment")
    trace.add_argument("example")
    trace.add_argument("--metric")
    add_common(trace)
    flips = commands.add_parser("flips", help="failures present in only one experiment")
    flips.add_argument("experiment_a")
    flips.add_argument("experiment_b")
    add_common(flips)
    cluster = commands.add_parser("cluster", help="group failures by evaluator and explanation")
    cluster.add_argument("experiments", nargs="+")
    add_common(cluster)
    return parser


def run(args: argparse.Namespace) -> object:
    """The subcommand's result payload, unrendered."""
    if args.command == "latest":
        return search(".evaluation-scores*", {"size": 30, "sort": [{"@timestamp": "desc"}]})
    if args.command == "ki":
        return search(".significant_events-knowledge_indicators", {"size": 200, "query": {"match_all": {}}})
    if args.command == "scores":
        values = collections.defaultdict(list)
        for document in docs(args.experiment):
            evaluator = document.get("evaluator", {})
            values[evaluator.get("name", "?")].append(evaluator.get("score", 0))
        return {name: sum(scores) / len(scores) for name, scores in values.items()}
    if args.command == "failures":
        return [doc for doc in docs(args.experiment, args.metric)
                if doc.get("evaluator", {}).get("score", 1) < 1]
    if args.command == "trace":
        return [doc for doc in docs(args.experiment, args.metric)
                if doc.get("example", {}).get("id") == args.example]
    if args.command == "flips":
        return {"only_a": sorted(failed(args.experiment_a) - failed(args.experiment_b)),
                "only_b": sorted(failed(args.experiment_b) - failed(args.experiment_a))}
    grouped = collections.Counter()
    for experiment in args.experiments:
        for document in docs(experiment):
            evaluator = document.get("evaluator", {})
            if evaluator.get("score", 1) < 1:
                summary = " ".join(evaluator.get("explanation", "").lower().split()[:8])
                grouped[(evaluator.get("name", "?"), summary)] += 1
    return {f"{name}: {summary}": count for (name, summary), count in grouped.items()}


def limited(payload: object, limit: int | None) -> object:
    """A list payload cut to `limit`, as an envelope naming the total so a caller sees the cut."""
    if limit is None or not isinstance(payload, list) or limit >= len(payload):
        return payload
    return {"items": payload[:limit], "returned": limit, "total": len(payload),
            "truncated": True, "hint": "raise --limit to see the rest"}


def main() -> int:
    args = build_parser().parse_args()
    if args.max_chars < 1:
        print("error: --max-chars must be at least 1", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("error: --limit must be at least 1", file=sys.stderr)
        return 2
    print(bounded_json(limited(run(args), args.limit), args.max_chars, what=args.command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
