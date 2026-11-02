#!/usr/bin/env python3
"""Normalize review findings, persist review reports, and append outcome records.

Input finding JSON requires title and label; file, line, persona, evidence,
disposition, reason, and memory_ids are optional. `normalize` canonicalizes
persona names, fingerprints file|label-category|normalized-title with SHA-1,
and deduplicates exact fingerprints. `persist` writes the consolidated report
to the review directory and to the task-level REVIEW.md (self, changes, pr) or
REVIEW.<mode>.md (spec, idea) so code verdicts that crew-commit and
crew-address-review read are never overwritten, and appends deferred findings to DEFERRED.md.
`outcome` appends an immutable JSONL record whose `persona` is a list of
canonical names. `persist` requires `--review-dir` to be `<task>/review/<ts>`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
OUTCOMES = {"fixed", "rejected", "deferred", "skipped"}
PERSONAS = {"adversarial", "architecture", "code-quality", "product-flow", "prompt-quality", "explorer"}
LEGACY_PERSONAS = {"fresh-eyes"}  # removed persona; kept so old review dirs still normalize
CODE_MODES = {"self", "changes", "pr"}
DISPOSITIONS = {"patch", "decide", "defer", "dropped", "merged"}


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def canonical_personas(value: object) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").split(",")
    result = []
    for item in raw:
        name = re.sub(r"\s+", "-", str(item).strip().lower()).removeprefix("reviewer-")
        if not name:
            continue
        if name not in PERSONAS | LEGACY_PERSONAS:
            raise ValueError(f"unknown persona: {item!r} (expected one of {sorted(PERSONAS)})")
        if name not in result:
            result.append(name)
    return result


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
        disposition = finding.get("disposition")
        if disposition is not None and disposition not in DISPOSITIONS:
            raise ValueError(f"finding {index} has invalid disposition: {disposition!r}")
        normalized = {**finding, "label": label}
        if "persona" in finding or "personas" in finding:
            normalized.pop("personas", None)
            normalized["persona"] = canonical_personas(finding.get("persona", finding.get("personas")))
        result.append({**normalized, "fingerprint": fingerprint(normalized)})
    return result


def normalize(args: argparse.Namespace) -> int:
    findings = read_findings(args.input)
    kept, duplicates = {}, []
    for finding in findings:
        existing = kept.get(finding["fingerprint"])
        if existing:
            for persona in finding.get("persona", []):
                if persona not in existing.setdefault("persona", []):
                    existing["persona"].append(persona)
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


def persist(args: argparse.Namespace) -> int:
    args.review_dir = args.review_dir.resolve()
    if args.review_dir.parent.name != "review":
        raise ValueError(f"--review-dir must be <task>/review/<timestamp>, got {args.review_dir}")
    report = args.report.read_text()
    if args.files:
        report = report.rstrip() + "\n\n### Files reviewed\n" + "".join(f"- `{name}`\n" for name in args.files)
    rows = []
    if args.findings:
        rows = [f for f in read_findings(args.findings) if f.get("disposition") == "defer"]
    args.review_dir.mkdir(parents=True, exist_ok=True)
    (args.review_dir / "REVIEW.md").write_text(report)
    owner = args.review_dir.parent.parent
    task_report = "REVIEW.md" if args.mode in CODE_MODES else f"REVIEW.{args.mode}.md"
    (owner / task_report).write_text(report)
    deferred = len(rows)
    if rows:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = owner / "DEFERRED.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        with path.open("a", encoding="utf-8") as handle:
            for f in rows:
                where = f"{f.get('file', '')}:{f.get('line', '')}".strip(":")
                reason = f.get("reason", "pre-existing or out of scope")
                if f"[{f['label']}] {f['title']} — `{where}`" in existing:
                    continue
                handle.write(f"- [{stamp}] [{f['label']}] {f['title']} — `{where}` — {reason}\n")
    print(json.dumps({"review": str(owner / task_report), "deferred": deferred}))
    return 0


def outcome(args: argparse.Namespace) -> int:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "review_dir": str(args.review_dir),
        "fingerprint": args.fingerprint,
        "persona": canonical_personas(args.persona),
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
    persist_parser = commands.add_parser("persist")
    persist_parser.add_argument("--review-dir", required=True, type=Path)
    persist_parser.add_argument("--report", required=True, type=Path)
    persist_parser.add_argument("--findings", type=Path)
    persist_parser.add_argument("--mode", choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    persist_parser.add_argument("--files", nargs="*", default=[])
    outcome_parser = commands.add_parser("outcome")
    outcome_parser.add_argument("--review-dir", required=True, type=Path)
    outcome_parser.add_argument("--fingerprint", required=True)
    outcome_parser.add_argument("--persona", required=True)
    outcome_parser.add_argument("--label", required=True, choices=sorted(LABELS))
    outcome_parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    outcome_parser.add_argument("--reason", required=True)
    outcome_parser.add_argument("--memory-id", action="append", default=[])
    args = parser.parse_args()
    handlers = {"normalize": normalize, "persist": persist, "outcome": outcome}
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
