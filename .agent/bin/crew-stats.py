#!/usr/bin/env python3
"""Report recent crew telemetry and persistent-memory statistics."""
import argparse
import datetime as dt
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def cutoff(value: str) -> dt.datetime:
    unit, amount = value[-1], value[:-1]
    if unit not in {"d", "h"} or not amount.isdigit():
        raise ValueError("--since must use whole days or hours, e.g. 7d or 24h")
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(**({"days": int(amount)} if unit == "d" else {"hours": int(amount)}))


parser = argparse.ArgumentParser()
parser.add_argument("--since", default="7d")
args = parser.parse_args()
try:
    since = cutoff(args.since)
except ValueError as error:
    parser.error(str(error))

telemetry, invalid, legacy = Counter(), 0, 0
telemetry_dir = Path.home() / ".agent" / "telemetry"
for path in telemetry_dir.glob("*.jsonl"):
    for line in path.read_text(errors="ignore").splitlines():
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                invalid += 1
                continue
            timestamp = record.get("ts")
            if not timestamp:
                legacy += 1
                continue
            parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed >= since:
                telemetry[record.get("event") or record.get("tool") or "unknown"] += 1
        except (json.JSONDecodeError, ValueError):
            invalid += 1

print(json.dumps({"since": args.since, "events": telemetry, "invalid": invalid, "legacy_without_ts": legacy}, sort_keys=True))
subprocess.run([sys.executable, str(Path(__file__).with_name("mem.py")), "stats"], check=False)
