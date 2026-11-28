"""`crew-hook.py <harness> <event>`: the one entry point every hook registration runs. The adapter normalises the
payload, each canonical event it serves runs its `contract.json` rules from ~/.agent/hooks (the event on stdin), and
the adapter encodes the first deny, else the first followup, else the context. A `fail: closed` rule that is missing,
fails or times out denies; an open one is skipped with one stderr line; an internal error denies an event with a
closed rule and allows the rest. `--record <dir>|off` saves each payload's structure, values replaced, as
`<dir>/<harness>/<event>.json` for the owner's probe (copied into evals/fixtures/harness).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from crew.harness import adapters

RECORD = Path.home() / ".agent" / "state" / "hook-record"
USAGE = "usage: crew-hook.py <harness> <event> < payload | crew-hook.py --record <dir>|off"


def redacted(value: object) -> object:
    """The same shape with every value replaced: a string by its kind, a number by 0, a list by its first item."""
    if isinstance(value, dict):
        return {key: redacted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(value[0])] if value else []
    if isinstance(value, bool) or value is None:
        return value
    return 0 if isinstance(value, (int, float)) else "<string>"


def record(harness: str, native: str, payload: dict) -> None:
    """While recording is on, the payload's structure for this event and tool, once; a failure never reaches dispatch."""
    try:
        target = Path(RECORD.read_text(encoding="utf-8").strip())
        tool = str(payload.get("tool_name") or "")
        path = target / harness / (f"{native}-{tool}.json" if tool else f"{native}.json")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(redacted(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return


def outcome(stdout: str) -> dict:
    """A rule's answer: a JSON object with `deny`, `followup` or `context`, else its text as context."""
    text = stdout.strip()
    if text.startswith("{"):
        try:
            found = json.loads(text)
        except ValueError:
            found = None
        if isinstance(found, dict):
            return {key: found[key] for key in ("deny", "followup", "context") if isinstance(found.get(key), str) and found[key]}
    return {"context": text} if text else {}


def run_rule(rule: dict, hooks: Path, event: dict, errors: list[str]) -> dict:
    """The rule's answer; when it cannot give one, a deny for a closed rule and nothing (one stderr line) for an open one."""
    script, why, said = hooks / rule["run"], "", ""
    cwd = event["cwd"] if event["cwd"] and Path(event["cwd"]).is_dir() else None
    try:
        if not script.is_file():
            why = f"{script} is missing"
        else:
            done = subprocess.run(["bash", str(script)], input=json.dumps(event), capture_output=True, text=True, timeout=rule["timeout"], cwd=cwd)
            errors.extend(line for line in done.stderr.splitlines() if line.strip())
            why, said = (f"exit {done.returncode}" if done.returncode else ""), done.stdout
    except (OSError, subprocess.TimeoutExpired) as error:
        why = f"did not finish: {type(error).__name__}"
    if not why:
        return outcome(said)
    if rule["fail"] == "closed":
        return {"deny": f"{rule['name']} could not judge this call ({why}); run crew doctor"}
    errors.append(f"crew-hook: rule {rule['name']} skipped ({why})")
    return {}


def dispatch(event: dict, hooks: Path, errors: list[str]) -> dict:
    """Every rule of every canonical event the call serves, in contract order, until one denies. A contract stamped with
    another version than this crew-hook's denies for its closed rules: install wrote them together."""
    contract = adapters.contract(hooks)
    followups: list[str] = []
    contexts: list[str] = []
    for canonical in event["events"]:
        for rule in (rule for rule in contract["rules"] if rule["event"] == canonical):
            if contract.get("version") != adapters.VERSION:
                answer = {"deny": f"the hook rules are version {contract.get('version')}, crew-hook {adapters.VERSION}: re-run install.sh"}
                answer = answer if rule["fail"] == "closed" else {}
            else:
                answer = run_rule(rule, hooks, {**event, "event": canonical, "v": adapters.VERSION}, errors)
            if answer.get("deny"):
                return {"deny": answer["deny"]}
            followups += [answer["followup"]] if answer.get("followup") else []
            contexts += [answer["context"]] if answer.get("context") else []
    return {"followup": followups[0] if followups else "", "context": "\n".join(contexts)}


def guarded(harness: str, native: str) -> bool:
    """Whether a closed rule serves this native event; without a readable contract, every `pre_*` event counts."""
    spec = adapters.manifest(harness)
    try:
        closed = {rule["event"] for rule in adapters.contract(adapters.hooks_dir())["rules"] if rule["fail"] == "closed"}
    except (OSError, ValueError, KeyError, TypeError):
        closed = {event for event in spec["events"] if event.startswith("pre_")}
    return any(native in adapters.natives(spec["events"][event]) for event in closed if event in spec["events"])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if args[:1] == ["--record"] and len(args) == 2:
        if args[1] == "off":
            RECORD.unlink(missing_ok=True)
        else:
            RECORD.parent.mkdir(parents=True, exist_ok=True)
            RECORD.write_text(f"{Path(args[1]).resolve()}\n", encoding="utf-8")
        return 0
    if len(args) != 2 or args[0] not in adapters.IDS:
        print(USAGE, file=sys.stderr)
        return 0
    harness, native = args
    adapter, errors = adapters.adapter(harness), []
    result: dict = {}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        payload = payload if isinstance(payload, dict) else {}
        record(harness, native, payload)
        event = adapter.normalize(native, payload)
        if event is not None:
            result = dispatch(event, adapters.hooks_dir(), errors)
    except Exception as error:  # the harness must get an answer whatever failed here
        result = {"deny": f"crew-hook could not judge this {native} call ({error}); run crew doctor"} if guarded(harness, native) else {}
        errors.append(f"crew-hook: internal error on {native}: {error}")
    stdout, stderr, code = adapter.encode(native, result)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr or "".join(line + "\n" for line in errors))
    return code


if __name__ == "__main__":
    sys.exit(main())
