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
`select` prints the reviewer personas a review must dispatch. `normalize
--strict` rejects emitted blocking/attention findings without `verified` and
`evidence`, and more than MAX_FINDINGS emitted findings. `persist --strict
--personas ...` requires each dispatched persona's `.in.md` and `.out.md`.
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
MAX_FINDINGS = 7
EMITTED = {"patch", "decide"}
EVIDENCE_LOCATION = re.compile(r"^[^:\s][^:]*:\d+(?:@[0-9a-f]{7,40})?$")
SELECT_RULES = {
    "prompt-quality": re.compile(r"(^|/)(agents|skills|evals)/|\.mdc$"),
    "architecture": re.compile(r"router|orchestrator|install|dispatch|tools\.json|(^|/)\.claude/"),
}
DISPOSITIONS = {"patch", "decide", "defer", "dropped", "merged"}


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def canonical_personas(value: object, *, split_commas: bool = True) -> list[str]:
    if not split_commas and isinstance(value, str) and "," in value:
        raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
    raw = value if isinstance(value, list) else str(value or "").split(",")
    result = []
    for item in raw:
        name = re.sub(r"\s+", "-", str(item).strip().lower()).removeprefix("reviewer-")
        if not split_commas and "," in str(item):
            raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
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


def check_strict(findings: list[dict]) -> None:
    emitted = [f for f in findings if f.get("disposition") in EMITTED]
    for f in emitted:
        evidence = f.get("evidence")
        if f["label"] in {"blocking", "attention"} and not (
            f.get("verified") is True
            and isinstance(evidence, str)
            and EVIDENCE_LOCATION.fullmatch(evidence)
        ):
            raise ValueError(
                f"unverified {f['label']} finding {f['title']!r}: set verified=true with evidence as path:line "
                "(or path:line@headSHA), "
                "or downgrade to 'needs more info'"
            )
    if len(emitted) > MAX_FINDINGS:
        raise ValueError(f"{len(emitted)} emitted findings exceed the cap of {MAX_FINDINGS}; drop the lowest severity")


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
    if args.strict:
        check_strict(list(kept.values()))
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
    if args.strict:
        if not args.personas:
            raise ValueError("--strict requires --personas")
        missing = [
            f"{persona}.{kind}.md"
            for persona in canonical_personas(args.personas, split_commas=False)
            for kind in ("in", "out")
            if not (args.review_dir / f"{persona}.{kind}.md").is_file()
        ]
        if missing:
            raise ValueError(f"missing persona artifacts in {args.review_dir}: {', '.join(missing)}")
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


def select(args: argparse.Namespace) -> int:
    required = {}
    if args.mode in CODE_MODES:
        required["code-quality"] = "code review"
        required["adversarial"] = "code review"
        for persona, pattern in SELECT_RULES.items():
            hits = [path for path in args.paths if pattern.search(path)]
            if hits:
                required[persona] = f"paths: {', '.join(hits[:3])}"
        if args.compat:
            required.setdefault("architecture", "--compat")
    if args.contract:
        required["product-flow"] = "--contract"
    print(json.dumps({"required": sorted(required), "reasons": required}, indent=2, sort_keys=True))
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
    normalize_parser.add_argument("--strict", action="store_true")
    persist_parser = commands.add_parser("persist")
    persist_parser.add_argument("--review-dir", required=True, type=Path)
    persist_parser.add_argument("--report", required=True, type=Path)
    persist_parser.add_argument("--findings", type=Path)
    persist_parser.add_argument("--mode", choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    persist_parser.add_argument("--files", nargs="*", default=[])
    persist_parser.add_argument("--strict", action="store_true")
    persist_parser.add_argument("--personas", nargs="*", default=[])
    select_parser = commands.add_parser("select")
    select_parser.add_argument("--mode", required=True, choices=sorted(CODE_MODES | {"spec", "idea"}))
    select_parser.add_argument("--paths", nargs="*", default=[])
    select_parser.add_argument("--contract", action="store_true", help="a spec or PR contract supplies acceptance criteria")
    select_parser.add_argument("--compat", action="store_true", help="the change alters behavior of an existing consumer")
    outcome_parser = commands.add_parser("outcome")
    outcome_parser.add_argument("--review-dir", required=True, type=Path)
    outcome_parser.add_argument("--fingerprint", required=True)
    outcome_parser.add_argument("--persona", required=True)
    outcome_parser.add_argument("--label", required=True, choices=sorted(LABELS))
    outcome_parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    outcome_parser.add_argument("--reason", required=True)
    outcome_parser.add_argument("--memory-id", action="append", default=[])
    args = parser.parse_args()
    handlers = {"normalize": normalize, "persist": persist, "select": select, "outcome": outcome}
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
