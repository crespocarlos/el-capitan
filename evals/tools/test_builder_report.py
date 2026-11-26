#!/usr/bin/env python3
"""The builder's REPORT.md against the gates it ran: `crew-progress.py report-check`.

Reports claimed `knip` clean at exit 1 and `biome` failing at exit 0. The check runs in the same
worker that wrote the report and compares every claim to the JSON `verify` wrote. Both directions
are pinned: a new report is held to the new sections, and a report from before this change, with no
such section and no gates JSON, still parses everywhere. Also pins what `crew-builder.md` says.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
CLI = TASK_TOOLS / "crew-progress.py"
BUILDER = ROOT / ".cursor" / "agents" / "crew-builder.md"
sys.path.insert(0, str(TASK_TOOLS))
sys.path.insert(0, str(TASK_TOOLS.parent))
import task_report_check as rc  # noqa: E402

FAILED: list[str] = []
GATES = {"schema_version": 1, "state": "done", "gates": [
    {"name": "knip", "exit": 1, "command": "npm run knip"}, {"name": "biome", "exit": 0, "command": "npx biome ci ."}]}

REPORT = """## Implementation Report

**Tasks:** 2/2 passed

### Quality gates
```
knip exit=1
biome exit=0
```
- `knip` — {knip} — {why}
- `biome` — pass

### Unverified claims
{claims}

### Report data
```json
{data}
```

### Files Changed
a.py
"""
DATA = json.dumps({"schema_version": 1, "gates": [{"name": "knip", "exit": 1}, {"name": "biome", "exit": 0}]})
CLAIM = "- the hook runs under Cursor — verify: `bash .claude/hooks/fixtures/run.sh`"
OLD = "## Implementation Report\n\n**Tasks:** 1/1 passed\n\n### Quality gates\n- `npm test` — pass\n\n### Files Changed\na.py\n"


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def report(knip: str = "fail", claims: str = CLAIM, data: str = DATA) -> str:
    return REPORT.format(knip=knip, why="exit 1", claims=claims, data=data)


def cli(tmp: Path, text: str, *extra: str, gates: dict | None = GATES) -> tuple[int, str]:
    (tmp / "REPORT.md").write_text(text, encoding="utf-8")
    arguments = [str(tmp / "REPORT.md"), *extra]
    if gates is not None:
        (tmp / "gates.json").write_text(json.dumps(gates), encoding="utf-8")
        arguments += ["--gates", str(tmp / "gates.json")]
    done = subprocess.run([sys.executable, str(CLI), "report-check", *arguments], capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def comparison(tmp: Path) -> None:
    code, out = cli(tmp / "a", report(knip="pass"))
    check("a claim `knip: pass` against exit=1 fails", code == 1 and "contradicts exit=1" in out, out)
    code, out = cli(tmp / "b", report())
    check("a verbatim copy with honest claims passes", code == 0 and "report-check: ok" in out, out)
    swapped = report().replace("knip exit=1", "knip exit=0")
    code, out = cli(tmp / "c", swapped)
    check("a copied line that differs from the JSON fails", code == 1 and "report says exit=0, verify says exit=1" in out, out)
    code, out = cli(tmp / "d", report().replace("knip exit=1\n", ""))
    check("a gate missing from the verbatim copy fails", code == 1 and "gate knip (exit=1) is not copied" in out, out)
    code, out = cli(tmp / "e", report(data=DATA.replace('"exit": 1', '"exit": 0')))
    check("Report data that disagrees with the JSON fails", code == 1 and "Report data gates differ" in out, out)
    cheat = REPORT.format(knip="fail", why="x", claims="none", data=DATA).replace("- `biome` — pass", "- `biome` — fail")
    code, out = cli(tmp / "f", cheat)
    check("a `fail` claim against exit=0 fails too", code == 1 and "biome: fail" in out, out)
    code, out = cli(tmp / "g", report(knip="skipped"))
    check("a `skipped` claim for a gate verify ran at exit=1 fails", code == 1 and "knip: skipped" in out, out)
    code, out = cli(tmp / "h", REPORT.format(knip="fail", why="x", claims="none", data=DATA).replace("- `biome` — pass", "- `biome` — skipped"))
    check("a `skipped` claim for a gate verify ran at exit=0 fails too", code == 1 and "biome: skipped" in out, out)
    claim_words(tmp)


def claim_words(tmp: Path) -> None:
    """One claim per gate, worded pass, fail or skipped; `passed`, `clean`, `ok`, `green` are problems."""
    for word in ("passed", "clean", "ok", "green", "failed"):
        (tmp / f"w-{word}").mkdir()
        code, out = cli(tmp / f"w-{word}", report(knip=word))
        check(f"a `knip — {word}` claim at exit=1 fails and names the word", code == 1 and f"`{word}`" in out and "knip" in out, out)
    for name in ("w-none", "w-two"):
        (tmp / name).mkdir()
    code, out = cli(tmp / "w-none", report().replace("- `knip` — fail — exit 1\n", ""))
    check("a gate with no claim line fails", code == 1 and "no claim line for gate knip" in out, out)
    code, out = cli(tmp / "w-two", report().replace("- `biome` — pass", "- `biome` — pass\n- `biome` — pass"))
    check("two claim lines for one gate fail", code == 1 and "2 claim lines for gate biome" in out, out)


def structure(tmp: Path) -> None:
    code, out = cli(tmp / "a", report(claims="none"))
    check("`none` is a valid Unverified claims section", code == 0, out)
    code, out = cli(tmp / "b", report(claims="- the hook runs under Cursor"))
    check("an unverified claim with no verify command fails", code == 1 and "without" in out, out)
    code, out = cli(tmp / "c", OLD, gates=None)
    check("a new-format check rejects a report with no new sections", code == 1 and "missing section: ### Unverified claims" in out, out)
    code, out = cli(tmp / "d", report(data="not json"))
    check("a Report data block that is not JSON fails", code == 1 and "schema_version" in out, out)
    code, out = cli(tmp / "e", report(data=json.dumps({"tasks": 1})))
    check("a Report data block without schema_version 1 fails", code == 1, out)


def old_reports(tmp: Path) -> None:
    code, out = cli(tmp / "a", OLD, "--lenient", gates=None)
    check("a report from before this change parses in lenient mode", code == 0, out)
    check("every parser returns empty for it", rc.sections(OLD).get("Unverified claims") is None
          and rc.unverified_claims(OLD) == [] and rc.report_data(OLD) is None and rc.gate_exits(OLD) == {})
    check("an unreadable gates file is not a crash", rc.load_gates(tmp / "missing.json") is None)
    check("a report with no sections at all parses", rc.unverified_claims("just prose\n") == [] and rc.problems("x", None, True) == [])
    code, out = cli(tmp / "b", OLD, "--lenient")
    check("a gates JSON that exists is compared even in a lenient run", code == 1 and "not copied" in out, out)
    code, out = cli(tmp / "c", OLD, "--lenient", gates={"gates": []})
    check("claims about commands that are not gates are not compared", code == 0, out)


def capped(tmp: Path) -> None:
    claims = "\n".join(f"- claim {i} — verify: `cmd {i}`" for i in range(8))
    lines = rc.capped(report(claims=claims), 5)
    check("the list shown at confirmation is capped at five with a pointer", len(lines) == 6 and lines[-1] == "(+3 more in REPORT.md)", lines)
    code, out = cli(tmp / "a", report(claims=claims), "--unverified", "5")
    check("--unverified prints the capped list", code == 0 and out.count("verify:") == 5 and "+3 more" in out, out)
    check("no section prints nothing", rc.capped(OLD, 5) == [])


def prompt_text() -> None:
    text = BUILDER.read_text(encoding="utf-8")
    for needle in ("crew-progress.py verify", "crew-progress.py report-check", "### Unverified claims", "schema_version", "verbatim"):
        check(f"crew-builder.md says `{needle}`", needle in text)
    for skill in ("crew-implement", "crew-commit"):
        body = (ROOT / ".cursor" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        check(f"{skill} runs the verify step", "crew-progress.py verify" in body)
    pr = (ROOT / ".cursor" / "skills" / "crew-open-pr" / "SKILL.md").read_text(encoding="utf-8")
    check("crew open pr shows the capped unverified list", "report-check" in pr and "--unverified 5" in pr)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for name in ("comparison", "structure", "old_reports", "capped"):
            (tmp / name).mkdir()
            for sub in "abcdefgh":
                (tmp / name / sub).mkdir()
        comparison(tmp / "comparison")
        structure(tmp / "structure")
        old_reports(tmp / "old_reports")
        capped(tmp / "capped")
    prompt_text()
    for name in FAILED:
        print(f"failed: {name}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
