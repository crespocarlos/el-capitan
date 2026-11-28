"""The one envelope every agent tool answers in: `{v, ok, data | error:{code, step, message, hint}, warnings}`.

`v` versions the envelope and the records in `data` together; a collection is `{items, returned, total, truncated,
hint}`. Concise text is the default rendering and compact JSON the `--json` one; an argparse error is one line, exit 2.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from crew.lib.errors import ToolError

V = 1


def ok(data: object, warnings: list[str]) -> dict:
    plain = dataclasses.asdict(data) if dataclasses.is_dataclass(data) and not isinstance(data, type) else data
    return {"v": V, "ok": True, "data": json.loads(json.dumps(plain, default=str)), "warnings": warnings}  # a Path is its text


def failed(error: ToolError, warnings: list[str]) -> dict:
    return {"v": V, "ok": False, "error": {"code": error.code, "step": error.step, "message": error.message, "hint": error.hint}, "warnings": warnings}


def text(envelope: dict) -> str:
    """Concise text: `error <code> [<step>]: message (hint)`; a collection one item per line; a record `key: value`
    lines, a multi-line value or a mapping of texts as `## heading` sections. Empty values are left out."""
    if not envelope["ok"]:
        error = envelope["error"]
        step = f" [{error['step']}]" if error["step"] else ""
        return f"error {error['code']}{step}: {error['message']}" + (f" ({error['hint']})" if error["hint"] else "")
    data = envelope["data"]
    if isinstance(data, dict) and "items" in data:  # a collection: one item per line, then the hint
        return "\n".join([line(item) for item in data["items"]] + ([f"... {data['hint']}"] if data.get("hint") else []))
    if not isinstance(data, dict):
        return line(data)
    lines, sections = [], []
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict) and all(isinstance(part, str) for part in value.values()):
            sections += [f"## {name}\n\n{part.rstrip()}" for name, part in value.items() if part]
        elif isinstance(value, str) and "\n" in value:
            sections.append(f"## {key}\n\n{value.rstrip()}")
        elif isinstance(value, list) and all(isinstance(item, str) for item in value) and any(" " in item for item in value):
            sections.append(f"## {key}\n\n" + "\n".join(value))  # sentences, one per line
        elif isinstance(value, list) and isinstance(value[0], dict):
            lines += [line(item) for item in value]
        else:
            lines.append(f"{key}: {line(value)}")
    return "\n\n".join(filter(None, ["\n".join(lines), *sections]))


def line(value: object) -> str:
    """One value on one line: a record's values space-separated, a list of words joined, else compact JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(line(part) for part in value.values() if part not in (None, "", [], {}))
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(value)
    return json.dumps(value, separators=(",", ":"))


class Parser(argparse.ArgumentParser):
    """An argparse error is one line naming the fix, exit 2, instead of the usage block."""

    def error(self, message: str) -> None:  # type: ignore[override]
        print(f"error usage [{self.prog}]: {message} (run {self.prog} --help)", file=sys.stderr)
        raise SystemExit(2)
