#!/usr/bin/env python3
"""Normalize review findings and append outcome records without model judgment.

Input finding JSON requires title and label; file, line, persona, evidence,
disposition, reason, and memory_ids are optional. `normalize` fingerprints
file|label-category|normalized-title with SHA-1 and deduplicates exact
fingerprints. `outcome` appends an immutable JSONL record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LABELS = {"blocking", "attention", "nit", "needs more info"}
OUTCOMES = {"fixed", "rejected", "deferred", "skipped"}


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def fingerprint(finding: dict) -> str:
    material = "|".join(
        [
            str(finding.get("file", "")).strip(),
            str(finding.get("label", "")).strip().lower(),
            normalized_title(str(finding["title"])),
        ]
    )
    return hashlib.sha1(material.encode()).hexdigest()


def read_findings(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        raise ValueError("finding input must be a JSON list or an object with a findings list")
    result = []
    for index, finding in enumerate(data, 1):
        if not isinstance(finding, dict) or not isinstance(finding.get("title"), str):
            raise ValueError(f"finding {index} requires a string title")
        label = str(finding.get("label", "")).lower()
        if label not in LABELS:
            raise ValueError(f"finding {index} has invalid label: {label!r}")
        result.append({**finding, "fingerprint": fingerprint(finding)})
    return result


def normalize(args: argparse.Namespace) -> int:
    findings = read_findings(args.input)
    kept, duplicates = {}, []
    for finding in findings:
        existing = kept.get(finding["fingerprint"])
        if existing:
            duplicates.append(
                {"fingerprint": finding["fingerprint"], "duplicate_of": existing["title"], "title": finding["title"]}
            )
        else:
            kept[finding["fingerprint"]] = finding
    payload = {"findings": list(kept.values()), "duplicates": duplicates}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


def outcome(args: argparse.Namespace) -> int:
    if args.outcome not in OUTCOMES:
        raise ValueError(f"invalid outcome: {args.outcome}")
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "review_dir": str(args.review_dir),
        "fingerprint": args.fingerprint,
        "persona": args.persona,
        "label": args.label,
        "outcome": args.outcome,
        "reason": args.reason,
        "memory_ids": args.memory_id,
    }
    target = args.review_dir.parent / "outcomes.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("input", type=Path)
    normalize_parser.add_argument("--output", type=Path)
    outcome_parser = commands.add_parser("outcome")
    outcome_parser.add_argument("--review-dir", required=True, type=Path)
    outcome_parser.add_argument("--fingerprint", required=True)
    outcome_parser.add_argument("--persona", required=True)
    outcome_parser.add_argument("--label", required=True, choices=sorted(LABELS))
    outcome_parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    outcome_parser.add_argument("--reason", required=True)
    outcome_parser.add_argument("--memory-id", action="append", default=[])
    args = parser.parse_args()
    try:
        return normalize(args) if args.command == "normalize" else outcome(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
