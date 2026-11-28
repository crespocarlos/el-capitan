"""The runs ledger, `~/.agent/state/runs.jsonl`: one JSON line when a review or a PR resolve starts and one when it
ends, so the TUI's Runs tab shows the standalone runs no task records. A line opens with its UTC stamp (`at`), which
`task_gc` prunes after `sessions_days`. Lines of one run share an `id` (a review's directory, or `resolve
owner/repo#N@<stamp>`, whose end lines find it by `open_run`); a later line updates the earlier ones."""

from __future__ import annotations

import json
from pathlib import Path

from crew.lib.clock import utc_stamp


def ledger() -> Path:
    return Path.home() / ".agent" / "state" / "runs.jsonl"


def append_run(run_id: str, event: str, **fields: str) -> None:
    """Append one line (`event` is `start` or `end`); a write that fails never fails the run it records."""
    line, path = json.dumps({"at": utc_stamp(), "id": run_id, "event": event, **fields}, separators=(",", ":")), ledger()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def read_runs(path: Path | None = None) -> list[dict]:
    """Each run once, its lines merged in file order (`started` is its first line's `at`), oldest first."""
    runs: dict[str, dict] = {}
    try:
        lines = (path or ledger()).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("id"):
            run = runs.setdefault(record["id"], {"started": record.get("at", "")})
            run.update(record)
    return list(runs.values())


def open_run(prefix: str) -> str:
    """The id of the newest run started as `<prefix>@<stamp>`, for its end line; `prefix` when none was."""
    ids = [run["id"] for run in read_runs() if run["id"].startswith(prefix + "@")]
    return ids[-1] if ids else prefix
