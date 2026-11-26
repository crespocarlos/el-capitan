#!/usr/bin/env python3
"""Compare evaluation runs from Elasticsearch score and trace indices (read only); targets Kibana.

Subcommands: `runs`, `compare [COMMIT ...]` (default: the last 3, first as baseline), `detail COMMIT`,
`traces COMMIT`, `diagnose BASELINE CANDIDATE --repo PATH`. COMMIT is a sha prefix. Env: ES_URL,
ES_API_KEY or ES_USER/ES_PASS, ES_SINCE, ES_TRACE_INDEX. Logic: `evals_query`, `evals_report`,
`evals_diagnose`; the helpers `evals/compare_run.py` uses are re-exported here.
"""
from __future__ import annotations

import argparse
import os
import sys

import evals_bootstrap  # noqa: F401

from evals_diagnose import (
    cmd_diagnose,
    sign_test_pvalue,
)
from evals_query import fetch_scores
from evals_report import (
    cmd_compare,
    cmd_detail,
    cmd_runs,
    cmd_traces,
    common_prefix,
    rows,
)
from evals_sources import classify_paths

__all__ = [  # the public names: re-exported for callers and tests that import this command file
    "classify_paths",
    "common_prefix",
    "main",
    "sign_test_pvalue",
]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=os.environ.get("ES_SINCE"),
                        help="ISO time; only scores after it")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("runs")
    compare = sub.add_parser("compare")
    compare.add_argument("commits", nargs="*")
    compare.add_argument("--exp", default="", help="only experiments whose name contains this")
    detail = sub.add_parser("detail")
    detail.add_argument("commit")
    detail.add_argument("--below", type=float, default=1.0)
    detail.add_argument("--chars", type=int, default=420)
    detail.add_argument("--ev", default="", help="only evaluators whose name contains this")
    traces = sub.add_parser("traces")
    traces.add_argument("commit")
    diagnose = sub.add_parser("diagnose")
    diagnose.add_argument("baseline")
    diagnose.add_argument("candidate", nargs="?")
    diagnose.add_argument("--repo", required=True, help="read-only Kibana checkout")
    diagnose.add_argument("--top", type=int, default=3,
                          help="trace examples per regressed evaluator")
    diagnose.add_argument("--json", action="store_true")
    diagnose.add_argument("--single", action="store_true",
                          help="analyze low scores for one commit; no delta claim")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    rs = rows(fetch_scores(args.since))
    if not rs:
        print("no scores found", file=sys.stderr)
        return 1
    {"runs": cmd_runs, "compare": cmd_compare, "detail": cmd_detail,
     "traces": cmd_traces, "diagnose": cmd_diagnose}[args.cmd](rs, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
