"""The finding vocabulary and the classifier that reads a persona's reply with it.

The closed sets a finding's fields come from (`label` how bad, `kind` what sort, kept out of the
fingerprint) and `PERSONA_STATUSES`; then whether a `<persona>.out.md` ran and holds review content,
credited by evidence (`path:line`, an `Anchor:` line, a quoted sentence, a line number with a body).
"""
from __future__ import annotations

import re

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
KINDS = {"security", "correctness", "reliability", "documentation", "testing", "other"}
# The reviewer's own belief that a finding is real, one point per band. Five points rather than a
# percentage because a percentage implies a calibration nobody can supply, and per finding rather
# than per review because only this form can be joined to whether the finding was fixed.
CONFIDENCE = {5: "confirmed", 4: "strong", 3: "likely", 2: "uncertain", 1: "suspicion"}
# What a probe observed about the finding, in the reviewer's own record: the claim held, it did not
# hold, or the run did not settle it. The middle value is the only one that may lower a score.
PROBE_OUTCOMES = {"confirmed", "refuted", "inconclusive"}
# Absent is not the same as empty: an optional field must not grow a key the persona never wrote,
# because `normalize` republishes the finding for later steps to parse. Held here rather than in the
# record so the vocabulary and the probe module can name it without importing each other.
ABSENT = object()
# The words a persona may open its reply with, and the order the report renders them in (worst
# first). One tuple each, because the regex, the report, and the evals all read this vocabulary and
# three independent copies is how a word added in one place disappears from the others.
ASSESSMENT_WORDS = ("approve", "request-changes", "comment")
ASSESSMENT_ORDER = ("request-changes", "comment", "approve")
# A finding the review asks the author to act on has to be one the reviewer believes in.
ACTED_CONFIDENCE = 3
OUTCOMES = {"fixed", "rejected", "deferred", "skipped"}
PERSONAS = {"adversarial", "architecture", "code-quality", "product-flow", "prompt-quality", "explorer"}
LEGACY_PERSONAS = {"fresh-eyes"}  # removed persona; kept so old review dirs still normalize
CODE_MODES = {"self", "changes", "pr"}
PERSONA_STATUSES = {"failed", "skipped", "truncated"}
# Tiered output cap, counted separately so polish cannot evict severity: a nit has a 4-slot budget
# and non-nits a 12-slot one, so a flat cap cannot bind a real finding out to make room for polish.
MAX_FINDINGS = 12
MAX_NITS = 4
EMITTED = {"patch", "decide"}
DISPOSITIONS = {"patch", "decide", "defer", "dropped", "merged"}
EVIDENCE_LOCATION = re.compile(r"^[^:\s][^:]*:\d+(?:@[0-9a-f]{7,40})?$")
SELECT_RULES = {
    "prompt-quality": re.compile(r"(^|/)(agents|skills|evals)/|\.mdc$"),
    "architecture": re.compile(r"router|orchestrator|install|dispatch|tools\.json|(^|/)\.claude/"),
}


def verdict(findings: list) -> str:
    """`BLOCK`, `WARN`, or `PASS` for a persisted report, decided from the emitted findings.

    Emitted means `Finding.is_emitted()`: a deferred blocking finding is not one the review asks the
    author to fix now, so it must not block the run. Prose in `pipeline.md` stated this mapping for
    a reader to apply by hand; here it is one expression every reader agrees on.
    """
    emitted = [finding for finding in findings if finding.is_emitted()]
    labels = {str(finding.label).lower() for finding in emitted}
    if "blocking" in labels:
        return "BLOCK"
    if labels & {"attention", "concern"}:
        return "WARN"
    return "PASS"


def mode_arg(value: str) -> str:
    """Normalize a mode before the choices check, so `--mode PR` is accepted.

    The protocol names the mode `PR` while the CLI enumerates lowercase values, which made a
    correct review fail on an argparse error before any persona was dispatched. Accept the
    documented casing and the `auto`/`auto-loop` modifiers instead of failing the run.
    """
    normalized = value.strip().lower()
    for modifier in (" auto-loop", " auto", "-auto-loop", "-auto"):
        normalized = normalized.replace(modifier, "")
    return normalized


def confidence_scale() -> str:
    """The five bands as one clause, so every rejection and every document states them alike."""
    return ", ".join(f"{score} {name}" for score, name in sorted(CONFIDENCE.items(), reverse=True))


def confidence_value(raw: object) -> int:
    """The score a caller wrote, or ValueError naming the 1-5 scale it violated.

    Absence is not a value: `require_confidence` refuses it at persist, because `normalize` has to
    keep reading the reviews recorded before the field existed.
    """
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in CONFIDENCE:
        raise ValueError(
            f"invalid confidence: {raw!r} (expected an integer 1-5: {confidence_scale()})"
        )
    return raw


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def canonical_personas(value: object, *, split_commas: bool = True) -> list[str]:
    """The persona names a caller named, normalized and validated against the vocabulary."""
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


# Reviewer personas do not all number their findings: three document an unnumbered
# `**path — line N**` — title body closed by `Fix/Response:`, and explorer returns `##` sections.
EXPLORER_SECTIONS = (
    "## Similar patterns",
    "## Potential duplicates",
    "## Conflicting implementations",
    "## Prior art",
    "## Canonical approach",
    "## Cross-file consistency",
)
# The emptiness sentinel: a persona that examined the artifact and found nothing writes this line.
# It does not say `Verdict:`, because that word belongs to an outcome scale a reader and a gate parse.
NO_FINDINGS = re.compile(r"^### Findings:\s*none\s*$", re.M | re.I)
# The judgement on the change as a whole, which a persona opens with when its package asks for it.
# The words come from the vocabulary, longest first, so an added word cannot be shadowed by a prefix.
ASSESSMENT = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?Assessment:(?:\*\*)?[ \t]*"
    r"(?P<word>" + "|".join(sorted(ASSESSMENT_WORDS, key=len, reverse=True)) + r")\b"
    r"(?P<clause>[^\n]*)",
    re.M | re.I,
)
# Public, because the report gate compares a persisted report's list against the finding JSON with
# the same vocabularies. A second copy of either pattern is how the two drift apart.
SEVERITY = r"(?:blocking|attention|concern|nit|needs more info)(?:\s*·\s*[1-5])?"
ANCHOR = r"(?:`?[^`\n\s]+`?\s*:\s*\d+|—\s*line\s*\d+)"
# A severity label plus a location anchor, in either order: label first, inside leading bold, after a
# bullet, or after the anchor. Rejecting one aborts the review, and the anchor must still be a real
# `path:line`. The label may carry its confidence score (`[attention · 4]`), which the contract makes
# mandatory, so the suffix is part of the token: a bare `]` would refuse every finding now written.
_BULLET = r"(?:[-*+]\s+)?(?:\d+[.)]?\s*)?"  # list bullet, number, or bare ordinal; all five are used
LABELED_FINDING = re.compile(
    # label first: `1. [blocking] … path.ts:42`, `- **[attention]** … path.ts:42`
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[" + SEVERITY + r"\][^\n]*?" + ANCHOR
    # anchor first: `` 1. `path.ts:42` — [blocking] … ``
    + r"|^[ \t]*" + _BULLET + r"(?:\*\*)?`?[^`\n\s\[\]]+`?\s*:\s*\d+[^\n]*?\[" + SEVERITY + r"\]",
    re.M | re.I,
)
# Findings whose anchor sits on an `Anchor: path:line` line rather than the label's own line.
LABEL_LINE = re.compile(
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[(" + SEVERITY + r")\]([^\n]*)", re.M | re.I
)
ANCHOR_ANYWHERE = re.compile(ANCHOR, re.I)
FIX_RESPONSE_FINDING = re.compile(
    # Three documented spellings of the fix field: `Fix:`, `Fix/Response:`, and `Suggested fix:`.
    # Rejecting any one of them refused real reviews as placeholders.
    r"(?ms)^\*\*.+?\*\*\s+—\s+\S.*?^(?:Suggested fix|Fix/Response|Fix):\s+\S"
)
EXPLORER_FINDING = re.compile(
    r"(?m)^(?:" + "|".join(re.escape(section) for section in EXPLORER_SECTIONS) + r")\s*$\n\s*-\s+\S"
)
# An orchestrator's own digest written in place of a persona's response. The protocol forbids it and
# it cannot be verified or re-graded later, so it is refused rather than accepted as output. The
# marker must read as an announcement — bare, bracketed, in a heading, or on a `status:` line — so a
# persona reviewing a prompt that merely contains the word is unaffected.
SUMMARY_ARTIFACT = re.compile(
    r"\A\s*(?:#{1,6}[^\n]*)?\s*[(\[]?\s*(?:condensed|summari[sz]ed)\b"
    r"|^[ \t]*(?:#{1,6}[ \t]*)?[(\[]\s*(?:condensed|summari[sz]ed)\b"
    r"|^[ \t]*status:.*\b(?:condensed|summari[sz]ed)\b",
    re.I | re.M,
)
SUMMARY_HEADER_CHARS = 300
# How far past a label line its evidence may sit, so neither a stray anchor far below can rescue a
# marker-only block nor a long finding lose its own `Anchor:` line.
ANCHOR_WINDOW = 2000
# A spec or idea review has one artifact under review, so its findings anchor by quoting the sentence
# they attack rather than by a `path:line` into a diff.
QUOTED_EVIDENCE = re.compile(r"[\"“][^\"”\n]{20,}[\"”]")
# A spec review cites the one artifact under review, so a finding may anchor to a bare line number or
# range. The number is still required, and described content must follow it, or `[nit] 611` would pass.
SPEC_FINDING = re.compile(
    r"^[ \t]*" + _BULLET + r"(?:\*\*)?\s*\[" + SEVERITY + r"\][\s*:—–-]*"
    r"\(?\s*\d[\d,\s–-]*\)?[\d,\s–\-:()]*\**\s*[A-Za-z\"“][^\n]{40,}",
    re.M | re.I,
)


def has_findings(text: str) -> bool:
    """True when the artifact carries at least one credited finding.

    Separate from `has_review_content` because the two answer different questions. The sentinel line
    says "nothing to report"; a finding says the opposite. Content wins: the sentinel is a signal for
    an empty review, never a cancellation of findings above it.
    """
    if LABELED_FINDING.search(text) or FIX_RESPONSE_FINDING.search(text):
        return True
    if EXPLORER_FINDING.search(text) or SPEC_FINDING.search(text):
        return True
    labels = list(LABEL_LINE.finditer(text))
    for index, match in enumerate(labels):
        # End the block at the next label, as the artifact's own structure implies, and in any case no
        # earlier than ANCHOR_WINDOW past the label line: a long finding may put its `Anchor:` further
        # down than the next label is far away, and truncating it would refuse a real finding.
        next_label = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        block = text[match.start():max(next_label, match.end() + ANCHOR_WINDOW)]
        if ANCHOR_ANYWHERE.search(block) or QUOTED_EVIDENCE.search(block):
            return True
    return False


def has_review_content(text: str) -> bool:
    """True when the artifact carries the sentinel, a finding, or explorer sections.

    A finding is credited by evidence, not by layout. Four real spec reviews and five bullet-style
    code reviews were refused as placeholders because the accepted shape was narrower than the
    format the persona documents.
    """
    if NO_FINDINGS.search(text):
        return True
    return has_findings(text)


def assessment_of(text: str) -> tuple[str, str] | None:
    """The persona's `(word, clause)` judgement on the change, or None when it wrote none.

    Fenced blocks are blanked first. The contract shows the line inside one, and every finding quotes
    its evidence verbatim, so a persona that echoes the template before writing its own judgement
    would otherwise be read as `approve` with a placeholder long enough to satisfy the gate.

    The clause comes back without its separator: a bare word is recorded but the gate refuses it,
    because "approve" with no reason is the unactionable opinion the line exists to replace.
    """
    match = ASSESSMENT.search(without_fences(text))
    if match is None:
        return None
    return match.group("word").lower(), match.group("clause").strip(" \t—:-–")


def without_fences(text: str) -> str:
    """The text with every fenced block blanked, line breaks kept so line numbers still resolve.

    The contract requires each finding to quote the lines it anchors verbatim, and the templates a
    persona may quote are themselves finding-shaped, so a reader looking for the report's own list or
    verdict has to skip what a finding quotes. Blanking the fence and its contents rather than
    deleting them keeps every line below it on the line it occupied before.
    """
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            kept.append("\n")
            continue
        kept.append("\n" if in_fence else line)
    return "".join(kept)


def persona_outcome(path) -> str:
    """Classify a persona artifact: ok, failed, skipped, truncated, summarized, missing, unknown.

    Only the leading block is read, so a persona quoting `status: failed` from the finding it
    reviews cannot flip a good run. The documented success signal is the sentinel line or a complete
    labeled finding; an empty artifact is `unknown`, not `ok`, because the failure this guards
    against is a persona that died silently. Only `failed|skipped|truncated` are read from a
    `status:` line: any other word (`dispatched`, `done`, `complete`) is not a success claim, so it
    falls through to the content check and a placeholder without a sentinel stays `unknown`.

    `summarized` is an orchestrator's condensed digest written in place of the persona's response.
    It is a separate outcome from `unknown` because the artifact does contain findings, but nothing
    in it is attributable to the persona or re-verifiable later, so persistence refuses it and names
    the real cause instead of "no output".
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "missing"
    if not text.strip():
        return "unknown"
    # An orchestrator summary is not the persona's response, whatever it says. Checked before the
    # status line so `status: ok (condensed) …` cannot pass as a completed persona.
    if SUMMARY_ARTIFACT.search(text[:SUMMARY_HEADER_CHARS]):
        return "summarized"
    declared = re.match(r"\s*(?:#+[^\n]*\n+\s*)?status:\s*(\w+)", text)
    if declared:
        word = declared.group(1).lower()
        # Failure words are authoritative; any other word (`dispatched`, `done`) is
        # not a success claim, so fall through to the content check below.
        if word in PERSONA_STATUSES:
            return word
    return "ok" if has_review_content(text) else "unknown"
