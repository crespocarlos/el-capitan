#!/usr/bin/env python3
"""Inspect evaluation documents in Elasticsearch. Read-only; exit 2 if unavailable."""
import argparse
import base64
import collections
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")


def search(index, query):
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


def docs(experiment=None, metric=None):
    clauses = []
    if experiment:
        clauses.append({"term": {"experiment_id": experiment}})
    if metric:
        clauses.append({"term": {"evaluator.name": metric}})
    response = search(".evaluation-scores*", {"size": 500, "query": {"bool": {"must": clauses}}})
    return [hit["_source"] for hit in response["hits"]["hits"]]


def failed(experiment):
    return {
        (doc.get("example", {}).get("id"), doc.get("evaluator", {}).get("name"))
        for doc in docs(experiment)
        if doc.get("evaluator", {}).get("score", 1) < 1
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("latest")
    scores = commands.add_parser("scores"); scores.add_argument("experiment")
    failures = commands.add_parser("failures"); failures.add_argument("experiment"); failures.add_argument("--metric")
    trace = commands.add_parser("trace"); trace.add_argument("experiment"); trace.add_argument("example"); trace.add_argument("--metric")
    commands.add_parser("ki")
    flips = commands.add_parser("flips"); flips.add_argument("experiment_a"); flips.add_argument("experiment_b")
    cluster = commands.add_parser("cluster"); cluster.add_argument("experiments", nargs="+")
    args = parser.parse_args()

    if args.command == "latest":
        result = search(".evaluation-scores*", {"size": 30, "sort": [{"@timestamp": "desc"}]})
    elif args.command == "ki":
        result = search(".significant_events-knowledge_indicators", {"size": 200, "query": {"match_all": {}}})
    elif args.command == "scores":
        values = collections.defaultdict(list)
        for document in docs(args.experiment):
            evaluator = document.get("evaluator", {})
            values[evaluator.get("name", "?")].append(evaluator.get("score", 0))
        result = {name: sum(scores) / len(scores) for name, scores in values.items()}
    elif args.command == "failures":
        result = [doc for doc in docs(args.experiment, args.metric) if doc.get("evaluator", {}).get("score", 1) < 1]
    elif args.command == "trace":
        result = [doc for doc in docs(args.experiment, args.metric) if doc.get("example", {}).get("id") == args.example]
    elif args.command == "flips":
        result = {"only_a": sorted(failed(args.experiment_a) - failed(args.experiment_b)),
                  "only_b": sorted(failed(args.experiment_b) - failed(args.experiment_a))}
    else:
        grouped = collections.Counter()
        for experiment in args.experiments:
            for document in docs(experiment):
                evaluator = document.get("evaluator", {})
                if evaluator.get("score", 1) < 1:
                    summary = " ".join(evaluator.get("explanation", "").lower().split()[:8])
                    grouped[(evaluator.get("name", "?"), summary)] += 1
        result = {f"{name}: {summary}": count for (name, summary), count in grouped.items()}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
