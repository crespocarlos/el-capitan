#!/usr/bin/env python3
"""Elasticsearch access for the evals tools: the HTTP call and the score/trace queries.

Read-only by construction: `es` posts a search body, and nothing here builds an index or document
request. Credentials come from the environment only — `ES_URL`, plus `ES_API_KEY` or
`ES_USER`/`ES_PASS` — so no repository file carries a secret.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request


def es_url() -> str:
    """`ES_URL`, read at call time so a caller's environment for this call is the one used."""
    return os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")


def es(path: str, body: dict) -> dict:
    headers = {"content-type": "application/json"}
    if os.environ.get("ES_API_KEY"):
        headers["authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
    else:
        auth = base64.b64encode(
            f"{os.environ.get('ES_USER', 'elastic')}:{os.environ.get('ES_PASS', 'changeme')}".encode()
        ).decode()
        headers["authorization"] = f"Basic {auth}"
    request = urllib.request.Request(
        f"{es_url()}/{path}", data=json.dumps(body).encode(), method="POST", headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_scores(since: str | None) -> list[dict]:
    """Every score document, paged with `search_after` so a large run is not truncated."""
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


def spans(trace_ids: list[str]) -> list[dict]:
    """The chat and tool-call spans of one trace, oldest first."""
    body = {"size": 5000, "sort": [{"@timestamp": "asc"}],
            "query": {"bool": {"filter": [
                {"terms": {"trace_id": trace_ids}},
                {"terms": {"attributes.gen_ai.operation.name": ["chat", "execute_tool"]}},
            ]}}}
    index = os.environ.get("ES_TRACE_INDEX", "traces-generic.otel-default")
    return [hit["_source"] for hit in es(f"{index}/_search", body)["hits"]["hits"]]
