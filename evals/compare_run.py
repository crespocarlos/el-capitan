#!/usr/bin/env python3
"""Deterministic checks for evals-compare helpers; no Elasticsearch required."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evals_compare", ROOT / ".agent/bin/evals-compare.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main():
    p_value, pairs = MODULE.sign_test_pvalue([0, 0, 0], [1, 1, 1])
    checks = {
        "common_prefix": MODULE.common_prefix(["suite: A", "suite: B"]) == "suite: ",
        "no_unsafe_prefix": MODULE.common_prefix(["A", "B"]) == "",
        "all_ties": MODULE.sign_test_pvalue([1, 1], [1, 1]) == (1.0, 0),
        "small_sample_not_significant": pairs == 3 and p_value > 0.05,
        "path_conventions": MODULE.classify_paths(
            [
                "x/agent_builder/agents/a/instructions.md.text",
                "x/agent_builder/tools/a/tool.ts",
                "x/lib/indicator_searcher.ts",
                "src/evaluators/a.ts",
                "src/datasets/a.ts",
                "x/other.ts",
            ],
            Path("/tmp/suite"),
            {"src/evaluators/a.ts"},
        ) == {
            "prompt": ["x/agent_builder/agents/a/instructions.md.text"],
            "tool": ["x/agent_builder/tools/a/tool.ts"],
            "retrieval": ["x/lib/indicator_searcher.ts"],
            "evaluator": ["src/evaluators/a.ts"],
            "dataset": ["src/datasets/a.ts"],
            "other": ["x/other.ts"],
        },
    }
    for name, passed in checks.items():
        print(f"{name}: {'pass' if passed else 'fail'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
