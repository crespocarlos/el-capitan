#!/usr/bin/env python3
"""Held-out behavioral cases for the prompts, checked structurally and without a model call.

The tools have 8,600 lines of tests and the prompts that steer them had none, so a prompt edit was
unmeasured. This runner closes that: each case under `cases/` names one prompt file, one real
request, the artifact that prompt must produce, and the assertions that decide it. Every assertion
is deterministic — a heading, a required field, a verdict vocabulary, a routing row — because a
model call would make the suite non-hermetic and a score would make a regression arguable.

Each case also carries a `broken` artifact that must fail its own assertions. That is what keeps
the set honest: an assertion that cannot fail a plausible bad output is not measuring anything.

Usage: run.py [--case ID] [--json]
Exit:  0 every case passes and every broken variant is caught; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[1]
CASES = _HERE / "cases"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from assertions import evaluate  # noqa: E402


def load_cases(only: str) -> tuple[list[dict], list[str]]:
    """Every case file, sorted by id, plus the load failures that make a case unusable."""
    cases, problems = [], []
    for path in sorted(CASES.glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            case["_file"] = path.name
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{path.name}: {error}")
            continue
        if only and case.get("id") != only:
            continue
        missing = [key for key in ("id", "prompt", "request", "artifact", "assertions", "broken")
                   if not case.get(key)]
        if missing:
            problems.append(f"{path.name}: missing {', '.join(missing)}")
            continue
        cases.append(case)
    return cases, problems


def check_prompt(case: dict) -> list[str]:
    """The prompt under test exists, and the request is a real request rather than a restatement."""
    prompt = ROOT / case["prompt"]
    problems = [] if prompt.is_file() else [f"prompt file not found: {case['prompt']}"]
    if len(case["request"].split()) < 6:
        problems.append("request is too short to be a held-out case")
    if not case["assertions"]:
        problems.append("no assertions")
    return problems


def run_case(case: dict) -> tuple[bool, list[str]]:
    """A case passes when its artifact satisfies every assertion and its broken twin fails one."""
    problems = check_prompt(case)
    produced = evaluate(case["artifact"], case["assertions"])
    problems.extend(f"artifact: {message}" for message in produced)
    caught = evaluate(case["broken"], case["assertions"])
    if not caught:
        problems.append("broken variant passes every assertion, so the case measures nothing")
    return not problems, problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the held-out prompt cases structurally.")
    parser.add_argument("--case", default="", help="run one case id")
    parser.add_argument("--json", action="store_true", help="print a JSON array of results")
    args = parser.parse_args()

    cases, problems = load_cases(args.case)
    if not cases and not problems:
        print(f"error: no cases under {CASES}", file=sys.stderr)
        return 2
    results, regressions = [], 0
    for case in cases:
        passed, reasons = run_case(case)
        regressions += 0 if passed else 1
        results.append({"id": case["id"], "prompt": case["prompt"], "pass": passed,
                        "problems": reasons})
    if args.json:
        print(json.dumps({"results": results, "cases": len(results),
                          "regressions": regressions + len(problems)}, indent=2))
    else:
        for result in results:
            status = "pass" if result["pass"] else "FAIL"
            print(f"{status}: {result['id']} ({result['prompt']})")
            for reason in result["problems"]:
                print(f"  - {reason}")
        for problem in problems:
            print(f"FAIL: {problem}")
        print(f"cases: {len(results)}")
        print(f"regressions: {regressions + len(problems)}")
    return 0 if regressions == 0 and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
