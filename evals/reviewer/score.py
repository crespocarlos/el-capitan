#!/usr/bin/env python3
"""Score reviewer replies against the seeded-defect cases in `evals/reviewer/cases/`; offline, no model call.

Usage: score.py <recorded run dir> [--against <baseline run dir>] [--json]. A run dir holds
`<persona>/<case id>/run-<n>.md` (and `run-<n>.meta.json`), as `live.py` writes them. A run catches a case when one
finding anchors within `WINDOW` lines of a defect location (or, for a spec, names one of the case's `refs`) and its
prose, code removed, matches every keyword group. A tainted run (it read outside its case) counts as a miss.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"
# Every lens the eval measures: the five review personas and the two spec critics.
PERSONAS = ("adversarial", "code-quality", "architecture", "product-flow", "prompt-quality",
            "specwriter-adversarial", "specwriter-scope")
MIN_CASES = 3  # per persona
WINDOW = 5  # lines between a finding's anchor and the defect; a range wider than 2 * WINDOW locates nothing
# Words any finding can contain; a keyword group made of them would credit an unrelated finding at the right spot.
GENERIC_TERMS = frozenset({"every", "any", "all", "before", "after", "not yet", "status", "first", "another", "files",
                           "instead of", "default"})
RUN_FILE = re.compile(r"^run-(\d+)\.md$")
NOISE_GROWTH = 1.5  # unmatched findings per reply may grow by at most 50% unless recall rises with them ...
NOISE_FLOOR = 0.5  # ... or by this many per reply, whichever allows more
SEVERITY = r"(?:blocking|attention|concern|nit|needs more info)"
BULLET = r"[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]*)?"
# A finding starts at a severity label (the reviewer contract) or a bold reference followed by a dash (the critic
# contract); the text before the first one (the assessment, notes) is not a finding.
# The bold reference may hold `*` (a quoted glob such as `**/api/**`): it ends at the first `**` followed by a dash,
# or by a colon, a variant critics write; the scorer only measures, so it reads both.
FINDING_START = re.compile(rf"^{BULLET}(?:\*\*[ \t]*)?\[{SEVERITY}\b|^{BULLET}\*\*[^\n]+?\*\*[ \t]*[—–:-]", re.I | re.M)
# The last finding ends at the blank line after its `Fix:` paragraph, or at a closing line that is not a finding.
FIX_LINE = re.compile(r"^(?:\*\*)?(?:Suggested fix|Fix/Response|Fix)\b", re.M)
# A reviewer's one-line handoff to another lens follows its findings and is not part of the last one.
CLOSING_LINE = re.compile(r"^(?:Verdict:|#{1,6} |Files\b|---\s*$|Handoff to )", re.M)
PATH_ANCHOR = re.compile(r"(?P<path>[\w.~/@+-]*\w)(?::|#L)(?P<start>\d+)(?:\s*[-–]\s*L?(?P<end>\d+))?")
LINE_ANCHOR = re.compile(r"\b(?:lines?|L)\s*(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?", re.I)
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$", re.M | re.S)
INLINE_CODE = re.compile(r"(`+)[^`\n]*?\1")


@dataclass(frozen=True)
class Case:
    """One seeded defect: what the persona reviews and what counts as catching it."""

    id: str
    lens: str
    kind: str  # "diff" or "spec"
    locations: tuple[tuple[str, int], ...]
    refs: tuple[str, ...]
    keywords: tuple[tuple[str, ...], ...]
    hand_seeded: bool
    source: str
    summary: str
    defect: str
    context: dict
    after: dict
    directory: Path
    # A design case (hand-seeded, its defect names an approach): the reply names the better mechanism in code
    # spans, so its keywords also match inside code. Set in `case.json` as `"match_code": true`.
    match_code: bool = False

    def text(self) -> str:
        """The diff, or the spec, the persona reviews."""
        return (self.directory / ("change.diff" if self.kind == "diff" else "spec.md")).read_text(encoding="utf-8")


def load_case(directory: Path) -> Case:
    data = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    return Case(id=data["id"], lens=data["lens"], kind=data.get("kind", "diff"),
                locations=tuple((item["file"], int(item["line"])) for item in data["locations"]),
                refs=tuple(data.get("refs") or ()), keywords=tuple(tuple(group) for group in data["keywords"]),
                hand_seeded=bool(data.get("hand_seeded")), source=data["source"], summary=data["summary"],
                defect=data["defect"], context=data.get("context") or {}, after=data.get("after") or {},
                directory=directory, match_code=bool(data.get("match_code")))


def load_cases(root: Path = CASES_DIR) -> list[Case]:
    """Every case under `root`, sorted by lens then id."""
    cases = [load_case(path.parent) for path in root.glob("*/case.json")]
    return sorted(cases, key=lambda case: (PERSONAS.index(case.lens) if case.lens in PERSONAS else 99, case.id))


def findings(reply: str) -> list[str]:
    """The reply split into finding blocks, each from its start line to the next start; the last one is cut at its
    end (see `FIX_LINE`, `CLOSING_LINE`), so text after the findings is no part of any."""
    starts = [match.start() for match in FINDING_START.finditer(reply)]
    blocks = [reply[start:end] for start, end in zip(starts, [*starts[1:], len(reply)])]
    if blocks:
        blocks[-1] = last_block(blocks[-1])
    return blocks


def last_block(block: str) -> str:
    fix = FIX_LINE.search(block)
    if fix:
        blank = block.find("\n\n", fix.end())
        return block if blank < 0 else block[:blank]
    first_line_end = block.find("\n") + 1 or len(block)
    closing = CLOSING_LINE.search(block, first_line_end)
    return block if closing is None else block[:closing.start()]


def prose(block: str) -> str:
    """The block without fenced or inline code, which quotes the change rather than saying what is wrong with it."""
    return INLINE_CODE.sub(" ", FENCE.sub(" ", block))


def same_file(anchor: str, wanted: str) -> bool:
    """True when one path ends with the other at a path boundary (an absolute or partial anchor still counts)."""
    anchor, wanted = ("/" + re.sub(r"^(?:\./)+", "", path.strip("`'\"")).lstrip("/") for path in (anchor, wanted))
    return anchor.endswith(wanted) or wanted.endswith(anchor)


def near(start: int, end: int, line: int) -> bool:
    """A range wider than `2 * WINDOW` points at a region, not a defect, so it locates nothing."""
    return end - start <= 2 * WINDOW and start - WINDOW <= line <= end + WINDOW


def located(block: str, case: Case) -> bool:
    """The block anchors at a defect location, or (a spec) cites a line near one or names a ref on its first line."""
    for match in PATH_ANCHOR.finditer(block):
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if any(same_file(match.group("path"), file) and near(start, end, line) for file, line in case.locations):
            return True
    if case.kind != "spec":
        return False
    for match in LINE_ANCHOR.finditer(block):
        start = int(match.group("start"))
        if any(near(start, int(match.group("end") or start), line) for _, line in case.locations):
            return True
    first = block.split("\n", 1)[0]
    return any(term_in(ref, first) for ref in case.refs)


def term_in(term: str, text: str) -> bool:
    """`term` as a whole word, case-insensitive; a trailing `*` makes it a prefix."""
    prefix = term.endswith("*")
    body = re.escape(term.rstrip("*"))
    return re.search(rf"(?<![A-Za-z0-9]){body}" + ("" if prefix else r"(?![A-Za-z0-9])"), text, re.I) is not None


def keyed(block: str, case: Case) -> bool:
    """Every keyword group in the finding's prose; for a `match_code` case, in its code spans too."""
    words = block if case.match_code else prose(block)
    return all(any(term_in(term, words) for term in group) for group in case.keywords)


def preamble(reply: str) -> str:
    """The text before the first finding: the assessment and, for a design reviewer, its approach verdict."""
    match = FINDING_START.search(reply)
    return reply[:match.start()] if match else reply


def catches(reply: str, case: Case) -> bool:
    """True when one finding of `reply` names the case's defect: its place and its keywords. An approach is judged
    for the whole change, not at a line, so a `match_code` (design) case also counts its keywords in the preamble."""
    if case.match_code and keyed(preamble(reply), case):
        return True
    return any(located(block, case) and keyed(block, case) for block in findings(reply))


def volume(reply: str, case: Case) -> tuple[int, int]:
    """`(findings, unmatched)` in one reply: how many findings it holds, and how many anchor at no case location.

    Recall alone rewards a persona that sprays findings; these two counts make that visible.
    """
    blocks = findings(reply)
    return len(blocks), sum(not located(block, case) for block in blocks)


def replies(run_dir: Path, persona: str, case: Case) -> dict[int, tuple[str, list[str]]]:
    """`{run number: (reply, tainted paths)}` recorded for one case; the paths come from `run-<n>.meta.json`."""
    directory = run_dir / persona / case.id
    found = {}
    for path in sorted(directory.glob("run-*.md")) if directory.is_dir() else []:
        number = RUN_FILE.match(path.name)
        if not number:
            continue
        meta_path = path.with_suffix(".meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        except ValueError:
            meta = {"tainted": [f"{meta_path.name} is not JSON"]}
        reply = path.read_text(encoding="utf-8", errors="replace")
        found[int(number.group(1))] = (reply, list(meta.get("tainted") or []))
    return found


def tally(run_dir: Path, cases: list[Case]) -> dict[str, dict]:
    """Per persona with recorded replies: each run's catch rate, their mean and spread, and each case's catches.

    A run number missing for a case counts as a miss and is listed under `missing`, and a tainted run is a miss
    listed under `tainted`, so a failed or leaky dispatch lowers the rate visibly instead of shrinking the
    denominator or inflating the numerator.
    """
    from live import FAILED  # imported here: `live` imports this module at its top

    result: dict[str, dict] = {}
    for persona in PERSONAS:
        own = [case for case in cases if case.lens == persona]
        recorded = {case.id: replies(run_dir, persona, case) for case in own}
        runs = sorted({number for found in recorded.values() for number in found})
        if not own or not runs:
            continue
        caught = {case.id: [n in recorded[case.id] and not recorded[case.id][n][1]
                            and catches(recorded[case.id][n][0], case) for n in runs] for case in own}
        rates = [sum(caught[case.id][index] for case in own) / len(own) for index in range(len(runs))]
        # The same replies recall scores: a failure record holds no findings, and a tainted run is not counted.
        counts = [volume(reply, case) for case in own for reply, tainted in recorded[case.id].values()
                  if not tainted and not reply.startswith(FAILED)]
        result[persona] = {
            "runs": [round(rate, 3) for rate in rates], "mean": round(sum(rates) / len(rates), 3),
            "spread": round(max(rates) - min(rates), 3), "cases": caught,
            "findings": round(sum(total for total, _ in counts) / len(counts), 2) if counts else 0.0,
            "unmatched": round(sum(stray for _, stray in counts) / len(counts), 2) if counts else 0.0,
            "missing": [f"{case.id} run-{n}" for case in own for n in runs if n not in recorded[case.id]],
            "tainted": [f"{case.id} run-{n}" for case in own for n in runs
                        if n in recorded[case.id] and recorded[case.id][n][1]],
        }
    return result


def compare(baseline: dict[str, dict], candidate: dict[str, dict]) -> dict[str, list[str]]:
    """The bar a rewritten persona must clear, per persona: `[]` when it holds, else the reasons it does not.

    The candidate has at least as many runs as the baseline, its mean is at least the baseline mean minus one
    baseline run's spread, it catches every case the baseline caught in all of its runs, and it does not buy its
    rate with noise: unless its mean rises by more than the baseline's spread, its unmatched findings per reply
    stay within `noise_allowed` of the baseline's.
    """
    verdicts: dict[str, list[str]] = {}
    for persona, before in baseline.items():
        after = candidate.get(persona)
        if after is None:
            verdicts[persona] = ["no recorded run for this persona"]
            continue
        problems = []
        if len(after.get("runs") or []) < len(before.get("runs") or []):
            problems.append(f"{len(after.get('runs') or [])} run(s) against the baseline's {len(before['runs'])}")
        floor = round(before["mean"] - before["spread"], 3)
        if after["mean"] < floor:
            problems.append(f"mean {after['mean']} is below {floor} "
                            f"(baseline {before['mean']} - spread {before['spread']})")
        for case_id, hits in before["cases"].items():
            if hits and all(hits) and not all(after["cases"].get(case_id) or [False]):
                problems.append(f"{case_id}: caught in every baseline run, missed in a candidate run")
        stray_before, stray_after = before.get("unmatched", 0.0), after.get("unmatched", 0.0)
        recall_rose = after["mean"] > before["mean"] + before["spread"]
        if not recall_rose and stray_after > noise_allowed(stray_before):
            problems.append(f"unmatched findings per reply rose from {stray_before} to {stray_after} (allowed "
                            f"{noise_allowed(stray_before)}) while the mean did not rise past one baseline spread "
                            f"({before['mean']} -> {after['mean']})")
        verdicts[persona] = problems
    return verdicts


def noise_allowed(stray_before: float) -> float:
    """The most unmatched findings per reply a candidate may have: 50% more than the baseline, and never less than
    `NOISE_FLOOR` above it, so a baseline that happened to be clean does not demand zero noise forever."""
    return round(max(stray_before * NOISE_GROWTH, stray_before + NOISE_FLOOR), 2)


def noise(baseline: dict[str, dict], candidate: dict[str, dict]) -> dict[str, dict]:
    """Per persona in both runs: findings and unmatched findings per reply, as `[baseline, candidate]`."""
    keys = ("findings", "unmatched")
    return {persona: {key: [before.get(key, 0.0), candidate[persona].get(key, 0.0)] for key in keys}
            for persona, before in baseline.items() if persona in candidate}


def render(result: dict[str, dict]) -> str:
    """One line per persona: the mean, each run's rate, and the cases with their catches."""
    lines = []
    for persona, row in result.items():
        runs = ", ".join(f"{rate:.2f}" for rate in row["runs"])
        lines.append(f"{persona:<24} mean {row['mean']:.2f}  runs [{runs}]  spread {row['spread']:.2f}  "
                     f"findings/reply {row.get('findings', 0.0):.2f}  unmatched/reply {row.get('unmatched', 0.0):.2f}")
        for case_id, hits in row["cases"].items():
            lines.append(f"  {case_id:<32} {sum(hits)}/{len(hits)}")
        for key in ("missing", "tainted"):
            if row.get(key):
                lines.append(f"  {key} replies (counted as misses): {', '.join(row[key])}")
    return "\n".join(lines) if lines else "no recorded replies"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score recorded reviewer replies against the seeded-defect cases.")
    parser.add_argument("run_dir", type=Path, help="a recorded run, e.g. evals/reviewer/recorded/2026-11-28")
    parser.add_argument("--against", type=Path, help="a baseline run: also report whether each persona holds the bar")
    parser.add_argument("--json", action="store_true", help="print the tally as JSON")
    args = parser.parse_args(argv)
    for directory in (args.run_dir, args.against):
        if directory is not None and not directory.is_dir():
            print(f"score: {directory} is not a directory", file=sys.stderr)
            return 2
    cases = load_cases()
    result = tally(args.run_dir, cases)
    verdicts, volumes = None, None
    if args.against:
        baseline = tally(args.against, cases)
        if not baseline:
            print(f"score: {args.against} holds no recorded replies; there is no baseline to compare with",
                  file=sys.stderr)
            return 2
        verdicts, volumes = compare(baseline, result), noise(baseline, result)
    if args.json:
        print(json.dumps({"tally": result, "bar": verdicts, "noise": volumes}, indent=2))
    else:
        print(render(result))
        for persona, problems in (verdicts or {}).items():
            counts = (volumes or {}).get(persona)
            if counts:
                print(f"noise {persona}: findings/reply {counts['findings'][0]} -> {counts['findings'][1]}, "
                      f"unmatched/reply {counts['unmatched'][0]} -> {counts['unmatched'][1]}")
            print(f"bar {persona}: " + ("holds" if not problems else "; ".join(problems)))
    return 1 if verdicts and any(verdicts.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
