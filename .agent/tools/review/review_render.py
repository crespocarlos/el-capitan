"""What a report and a persona reply carry: rendered findings, sections, degraded mark, provenance.

The score joins the label (`[attention · 4]`); the decision footer is written once from the findings.
A body that already holds a generated section is refused. `save-out` stores a reply's raw bytes beside
`<persona>.provenance.json`; persist checks its sha256 and counts agents (fewer than lenses: degraded).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from review_models import Finding
from review_vocabulary import ABSENT, ASSESSMENT_ORDER, PROBE, canonical_personas, persona_outcome, verdict

from lib.clock import utc_stamp
from lib.files import atomic_write
from lib.next_steps import next_sentence

CAP_NOTE = "The lenses were not independent agents, so the verdict is capped at WARN."


def capped(verdict: str, degraded: bool) -> str:
    """`WARN` for a degraded `PASS`; every other verdict, and every non-degraded one, unchanged."""
    return "WARN" if degraded and verdict == "PASS" else verdict


def banner(agents: int, lenses: int) -> str:
    """The first line of a degraded review."""
    return f"Degraded: {agents} agent{'' if agents == 1 else 's'}, {lenses} lenses"


def with_banner(body: str, line: str) -> str:
    """`body` opened by the banner and the cap note; a body that already starts with one is kept."""
    return body if body.startswith("Degraded:") else f"{line}\n{CAP_NOTE}\n\n{body}"


ASSESSMENT_HEADING = "### Assessment of the change"
COVERAGE_HEADING = "### Coverage by layer"
FILES_HEADING = "### Files reviewed"
PROVENANCE_HEADING = "### Provenance"
# What `persist` appends. A report must not carry any of them, or it renders twice.
GENERATED_SECTIONS = (ASSESSMENT_HEADING, COVERAGE_HEADING, FILES_HEADING, PROVENANCE_HEADING)
# A lens writes a sentence or three of reason. Past this the line is cut with its remainder reported,
# so a reader skimming `REVIEW.md` gets every lens's judgement without paying for four long paragraphs.
CLAUSE_DISPLAY_MAX = 600


def heading_lines(text: str) -> set[str]:
    """The level-3 heading lines of a report, ignoring fenced blocks.

    A finding may quote a heading verbatim (the contract requires quoting, not paraphrasing), and a
    sub-heading such as `#### Files reviewed` is a different section. Only an exact level-3 heading
    outside a fence means the caller wrote the generated section themselves.
    """
    headings: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("### "):
            headings.add(line.rstrip())
    return headings


def assessment_section(rows: dict) -> str:
    """The lenses' judgement on the change, or "" when there is nothing at all to report.

    `rows` is the gate's report, so this renders the verdicts already parsed and gated rather than
    re-reading every reply. The reading order is the vocabulary's own, so a word added there cannot
    silently disappear from the tally; an unexpected word gets its own line instead of being dropped.

    Two views of one fact, because they answer different questions. The tally says whether the lenses
    agree — "3 of 5 request changes" is what routes a decision. The per-lens lines say *why* each one
    landed there, so a reader acting on the review does not have to open four persona files to learn
    that one approved for a different reason than another. A clause past the display cap is cut with
    its length and the file that holds the rest, because a silently shortened reason reads as complete.

    A run with no tally still emits the section when a lens was skipped or never finished: the reader
    of `REVIEW.md` needs those names, and "no lens was asked" is a different, worse fact than "every
    lens approved" — which is why the tally alone cannot decide whether the section appears.
    """
    assessed = rows.get("assessed") or {}
    skipped = rows.get("skipped") or {}
    unavailable = rows.get("unavailable") or {}
    if not (assessed or skipped or unavailable):
        return ""
    by_word: dict[str, list[str]] = {}
    for persona, (word, _clause) in assessed.items():
        by_word.setdefault(word, []).append(persona)
    lines = [ASSESSMENT_HEADING, ""]
    for word in ASSESSMENT_ORDER:
        names = by_word.pop(word, [])
        if names:
            lines.append(f"- **{word}** — {', '.join(sorted(names))}")
    for word in sorted(by_word):
        lines.append(f"- **{word}** — {', '.join(sorted(by_word[word]))}")
    if skipped:
        lines.append(f"- not asked (package predates the rule) — {', '.join(sorted(skipped))}")
    if unavailable:
        named = ", ".join(f"{name} ({outcome})" for name, outcome in sorted(unavailable.items()))
        lines.append(f"- no assessment — {named}")
    if assessed:
        lines.append("")
        lines.append("#### Each lens, and why")
        for persona in sorted(assessed):
            word, clause = assessed[persona]
            lines.append(f"- **{persona}** — {word}: {clause_text(persona, clause)}")
    return "\n".join(lines) + "\n"


def clause_text(persona: str, clause: str, limit: int = CLAUSE_DISPLAY_MAX) -> str:
    """One lens's reason, shortened only when it has to be, and never without saying so.

    The clause is the evidence a reader weighs, so it is reproduced as written. Past the cap it is cut
    at a word boundary with the remaining length and the file that holds the whole line, because a
    reason that ends mid-sentence with no marker is indistinguishable from one the persona wrote short.
    """
    text = " ".join(clause.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return f"{cut}… (+{len(text) - len(cut)} chars; see `{persona}.out.md`)"


# The stage key per mode, so the footer asks the shared table for its next step instead of restating
# it. A code review branches on the verdict it just derived — `BLOCK` resolves findings first, `PASS`
# and `WARN` commit — and the other three modes each have one successor. `pr` is the one entry that
# names a person's action, because a PR review's findings go to `comments.md` and nothing is posted.
STAGE_BY_MODE = {"self": "review", "changes": "review", "pr": "review.pr",
                 "spec": "review.spec", "idea": "review.idea"}


def stage_key(mode: str, findings: list[Finding], degraded: bool = False) -> str:
    """The `next-steps.json` key for this mode and its derived verdict (capped when degraded)."""
    stage = STAGE_BY_MODE.get(mode)
    if stage is None:
        raise ValueError(f"no next-step stage for mode {mode!r}: {', '.join(sorted(STAGE_BY_MODE))}")
    word = capped(verdict(findings), degraded).lower()
    return f"build.{stage}.{word}" if stage == "review" else f"build.{stage}"


def score_suffix(finding: Finding) -> str:
    """` · 4` when the finding carries a score, empty when it was written before the field existed.

    Empty rather than a placeholder: a historical review has no score to show, and printing ` · ?`
    would claim the reviewer was asked and said nothing.
    """
    return "" if finding.confidence is ABSENT else f" · {finding.confidence}"


def label_with_score(finding: Finding) -> str:
    """The label and its score as one bracketed token, which is how every report line carries it."""
    return f"[{finding.label}{score_suffix(finding)}]"


def footer(findings: list[Finding], head: str, mode: str, next_step: str = "",
          derived: bool = True, degraded: bool = False) -> str:
    """The decision block `persist` appends last: verdict, next step, and the reviewed commit.

    Written from the findings rather than copied from the report, because the report's verdict is a
    model's word and this one is derived. `Reviewed at:` is omitted entirely when no `--head` was
    passed: an empty value would claim a tree identity the run never had, and a spec or idea review
    always passes a head, so the omission is a local review saying so.

    `derived=False` writes the next step and the commit without a `Verdict:` line. That is the
    no-`--findings` path: `persist` compared nothing there, so a verdict derived from an empty list
    would be `PASS` stamped under a body that may say `BLOCK`, and every tail-first reader of the
    file takes the last `Verdict:` it finds.

    The next step comes from `next-steps.json` keyed by this mode's stage and the verdict just
    derived, so the persisted report's `> Next:` and the table cannot disagree. A caller may pass
    `next_step` to override it, which is what `persist --next` does. A skill's own trailer is written
    prose that `lint_handoff` holds to the router; it does not read this table.
    """
    step = next_step or next_sentence(stage_key(mode, findings, degraded))
    lines = [f"> Next: {step}"]
    if derived:
        lines.insert(0, f"Verdict: {capped(verdict(findings), degraded)}")
    if head:
        lines.append(f"Reviewed at: {head}")
    return "\n".join(lines)


@dataclass
class Trail:
    """The provenance facts a persisted report states about itself."""

    section: str = ""
    degraded: str = ""


def read_record(review_dir: Path, persona: str) -> dict | None:
    """The persona's provenance record, None when absent, ValueError when unreadable."""
    path = review_dir / f"{persona}.provenance.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{path.name} is not valid JSON ({error})") from None
    if not isinstance(record, dict) or "sha256" not in record:
        raise ValueError(f"{path.name} carries no sha256")
    return record


def agent_key(persona: str, record: dict | None) -> tuple:
    """Which agent answered: shared ids and declared degraded runs collapse to one key."""
    if record is None or record.get("resumed"):
        return ("persona", persona)
    if record.get("agent_id"):
        return ("id", record["agent_id"])
    return ("degraded",) if record.get("degraded") else ("persona", persona)


def check(review_dir: Path, personas: list[str]) -> Trail:
    """Verify each saved reply's hash and say how many agents answered; ValueError on a mismatch."""
    names = canonical_personas(personas, split_commas=False)
    records = {name: read_record(review_dir, name) for name in names}
    for name, record in records.items():
        reply = review_dir / f"{name}.out.md"
        if record and hashlib.sha256(reply.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(
                f"{reply.name} no longer matches its provenance record (sha256 mismatch): it was "
                "edited after save-out; save the persona's real reply again"
            )
    verified = [name for name, record in records.items() if record]
    legacy = [name for name in names if name not in verified]
    if not verified:
        line = "provenance: absent (legacy)"
    else:
        line = f"provenance: verified ({len(verified)} of {len(names)} replies hashed at save-out)"
        if legacy:
            line += f"; absent (legacy) for {', '.join(legacy)}"
    agents = len({agent_key(name, record) for name, record in records.items()})
    degraded = banner(agents, len(names)) if agents < len(names) else ""
    return Trail(section=f"{PROVENANCE_HEADING}\n- {line}\n", degraded=degraded)


SCHEMA_VERSION = 1


def provenance_path(review_dir: Path, persona: str) -> Path:
    return review_dir / f"{persona}.provenance.json"


def add_save_out_parser(commands) -> None:
    parser = commands.add_parser(
        "save-out", help="store a persona reply from stdin as <persona>.out.md with its provenance")
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--harness", required=True, help="cursor, claude-code, codex, ...")
    parser.add_argument("--agent-id", default=None, help="the dispatched agent's id, when known")
    parser.add_argument("--model", default=None, help="the model that answered, when known")
    parser.add_argument("--resume", action="store_true", help="this reply is a resume of the persona")
    parser.add_argument("--degraded", action="store_true",
                        help="the orchestrator played this lens itself (no separate agent)")


def save_out(args: argparse.Namespace) -> int:
    """Write the raw reply and its provenance record; warn, without refusing, on a digest. `--persona probe`
    saves the reviewer-probe reply as `probe.out.md`, which the probe gate of `persist` reads."""
    named = args.persona.strip().lower().removeprefix("reviewer-")
    (persona,) = [PROBE] if named == PROBE else canonical_personas([args.persona], split_commas=False)
    if not args.review_dir.is_dir():
        raise ValueError(f"no such review directory: {args.review_dir}")
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        raise ValueError("stdin is empty: there is no reply to save")
    target = args.review_dir / f"{persona}.out.md"
    target.write_bytes(raw)
    record = {
        "schema_version": SCHEMA_VERSION, "persona": persona, "harness": args.harness,
        "agent_id": args.agent_id or None, "model": args.model or None,
        "time": utc_stamp(),
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "resumed": bool(args.resume), "degraded": bool(args.degraded),
    }
    atomic_write(provenance_path(args.review_dir, persona), json.dumps(record, indent=2) + "\n")
    outcome = persona_outcome(target)
    if outcome in ("summarized", "unknown") and persona != PROBE:
        print(f"warning: {target.name} reads as `{outcome}`; persist will refuse it unless it is "
              "the persona's real reply", file=sys.stderr)
    print(json.dumps({"saved": str(target), "sha256": record["sha256"], "outcome": outcome}))
    return 0
