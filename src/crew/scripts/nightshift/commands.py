#!/usr/bin/env python3
"""The run operations: worktrees, start, status, report, followup, stop, and stack-stop.

Each one is a call plus the shape printed back, kept together because they share the client and
the same PR-key validation. Nightshift's own `error` field is often the first thing that went
wrong (a missing build artifact) rather than the real cause, which is why `status` appends the
dev-stack log's last FATAL line when the run failed and a worktree path was given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crew.lib.output import bounded_json, rows_limit, truncate
from crew.scripts.nightshift.client import base_url, check_key, request

# Nightshift's own rule (prompts/e2e-common-report.md): only these observations, on a check
# that was not skipped, count as end-to-end. `via` is a list there; accept a bare string too.
END_TO_END_VIA = {"ui", "api", "es", "log"}


def tail_fatal(worktree_path: str) -> str:
    """The last FATAL line of a worktree's dev-stack log, which is the failure worth surfacing."""
    log = Path(worktree_path).expanduser() / ".dev-stack" / "kibana.log"
    if not log.is_file():
        return ""
    try:
        fatal = [line for line in log.read_text(errors="replace").splitlines() if "FATAL" in line]
    except OSError:
        return ""
    return fatal[-1] if fatal else ""


def is_end_to_end(entry: dict) -> bool:
    """True when a check observed the behavior through a surface that counts as end-to-end."""
    via = entry.get("via")
    observed = {str(item).lower() for item in (via if isinstance(via, list) else [via])}
    return entry.get("status") != "skipped" and bool(observed & END_TO_END_VIA)


def worktrees(args: argparse.Namespace) -> int:
    """List the designated Kibana worktrees, flagging the one that looks like the main checkout."""
    payload = request("GET", "/api/deploy?scope=designated")
    items = payload.get("worktrees") or []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = {key: item.get(key) for key in ("id", "label", "name", "branch", "kibanaPort", "kibanaRunning", "path")}
        dirty = item.get("dirty")
        entry["dirty"] = dirty if isinstance(dirty, list) else []
        entry["dirtyCount"] = len(entry["dirty"])
        # Port 5601 is the documented convention for the user's own dev checkout (this skill's
        # Known limits say so); a dedicated e2e worktree normally runs elsewhere. A heuristic,
        # not a fact from the API, so it is named as risk, not as a verdict.
        entry["mainRepoRisk"] = entry.get("kibanaPort") == 5601
        result.append(entry)
    shown, marker = rows_limit(result, args.limit)
    text = json.dumps({"worktrees": shown}, indent=2)
    if marker:
        text = bounded_json({"worktrees": shown, "total": len(result), "truncated": True, "hint": marker}, args.max_chars)
    print(truncate(text, args.max_chars, what="worktrees"))
    return 0


def start(args: argparse.Namespace) -> int:
    """Start an e2e run directly; never queued, and never comments on the PR."""
    check_key(args.key)
    body = {"action": "start", "worktree": args.worktree, "deploy": bool(args.deploy)}
    if args.instructions:
        body["instructions"] = args.instructions
    payload = request("POST", f"/api/e2e/{args.key}", body)
    print(json.dumps({"started": payload, "run": f"{base_url()}/pr/{args.key}/e2e"}, indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    """The run's state, with the dev-stack FATAL line when it failed."""
    check_key(args.key)
    payload = request("GET", f"/api/e2e/{args.key}")
    state = (payload.get("status") or {}).get("state")
    result = {
        "key": args.key,
        "state": state,
        "finished": state in {"done", "failed"},
        "outdated": payload.get("outdated"),
        "testedHead": (payload.get("meta") or {}).get("headSha"),
        "error": (payload.get("status") or {}).get("error"),
        "worktree": (payload.get("meta") or {}).get("worktreeLabel") or (payload.get("meta") or {}).get("worktree"),
        "run": f"{base_url()}/pr/{args.key}/e2e",
    }
    # Nightshift's own `error` field is often the first thing that went wrong (a missing build
    # artifact), not the real cause; the dev-stack log's last FATAL line usually is.
    if state == "failed" and args.worktree_path:
        fatal = tail_fatal(args.worktree_path)
        if fatal:
            result["fatal"] = fatal
    print(json.dumps(result, indent=2))
    return 0


def report(args: argparse.Namespace) -> int:
    """The finished report, with each check marked for whether it is end-to-end evidence."""
    check_key(args.key)
    payload = request("GET", f"/api/e2e/{args.key}")
    report_payload = payload.get("report")
    if not report_payload:
        state = (payload.get("status") or {}).get("state") or "unknown"
        print(f"nightshift-e2e: no report yet (state: {state})", file=sys.stderr)
        return 1
    checks = [dict(c, end_to_end=is_end_to_end(c)) for c in report_payload.get("checks") or [] if isinstance(c, dict)]
    print(
        json.dumps(
            {
                "key": args.key,
                "verdict": report_payload.get("verdict"),
                "summary": report_payload.get("summary"),
                "prIntent": report_payload.get("prIntent"),
                "approach": report_payload.get("approach"),
                "uiChanges": report_payload.get("uiChanges"),
                "outdated": payload.get("outdated"),
                "testedHead": (payload.get("meta") or {}).get("headSha") or report_payload.get("headSha"),
                "setup": report_payload.get("setup") or [],
                "checks": checks,
                # A check observed only through a health probe, a unit command or a script is not
                # end-to-end evidence; name them so a green run cannot be read as more than it is.
                "not_end_to_end": [c.get("title") for c in checks if not c["end_to_end"] and c.get("status") != "skipped"],
                "findings": report_payload.get("findings") or [],
                "environmentChanges": report_payload.get("environmentChanges") or [],
                "notCovered": report_payload.get("notCovered") or [],
            },
            indent=2,
        )
    )
    return 0


def followup(args: argparse.Namespace) -> int:
    """Ask the tester a follow-up question; an empty question is a usage error, not a request."""
    check_key(args.key)
    if not args.text.strip():
        print("nightshift-e2e: empty follow-up", file=sys.stderr)
        return 2
    request("POST", f"/api/e2e/{args.key}", {"action": "followup", "question": args.text.strip()})
    print(json.dumps({"followup": args.key, "question": args.text.strip()}))
    return 0


def stop(args: argparse.Namespace) -> int:
    """Stop the run; the worktree and its stack are left alone."""
    check_key(args.key)
    request("POST", f"/api/e2e/{args.key}", {"action": "stop"})
    print(json.dumps({"stopped": args.key}))
    return 0


def stack_stop(args: argparse.Namespace) -> int:
    """Stop the Kibana/ES stack nightshift started in a worktree.

    It does not touch the run or the checkout: `restore` would revert the worktree, so it is
    deliberately not offered here.
    """
    request("POST", "/api/deploy", {"action": "stop-stack", "worktree": args.worktree})
    print(json.dumps({"stack_stopped": args.worktree}))
    return 0
