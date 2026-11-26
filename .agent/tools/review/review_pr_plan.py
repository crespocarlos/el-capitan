"""The write half of the PR family: the `gh` mutation plan and the paste-ready comment bodies.

`reply` and `resolve` plan by default and act only on `--execute`; the plan names the exact `gh` argv.
`comments` writes `comments.md`, one body per anchored finding (a draft; nothing here calls `gh`), and
`check-map` parses a `reviewer-layers` reply before anything packages it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import review_bootstrap  # noqa: F401

from review_layers import parse_map_block
from review_models import Finding, to_finding
from review_render import label_with_score
from review_vocabulary import ABSENT

from lib.files import atomic_write, read_json_object
from lib.git import gh
from lib.output import bounded_json

DEFAULT_QUERY = Path.home() / ".agent/bin/pr-review-threads.graphql"
RESOLVE_QUERY = ("mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) "
                 "{ thread { isResolved } } }")


def default_query() -> Path:
    """The graphql asset: the installed link when one exists, else the copy beside this file.

    An asset is read, not installed, so `install.sh` links none. An installed path is still
    preferred when present, because a plan printed for an operator to run
    by hand should name the stable path they will find.
    """
    if DEFAULT_QUERY.is_file():
        return DEFAULT_QUERY
    return Path(__file__).resolve().with_name("pr-review-threads.graphql")


def repository(value: str) -> tuple[str, str]:
    try:
        owner, name = value.split("/", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--repo must be OWNER/REPO") from error
    return owner, name


def query_command(query: Path, owner: str, name: str, pr: int, cursor: str | None) -> list[str]:
    """The argv for one page of review threads; the cursor is added only when a caller passed one."""
    command = ["gh", "api", "graphql", "-F", f"query=@{query}", "-f", f"owner={owner}",
               "-f", f"repo={name}", "-F", f"pr={pr}"]
    if cursor:
        command.extend(["-f", f"cursor={cursor}"])
    return command


def mutation_command(args: argparse.Namespace) -> list[str]:
    """The exact `gh` argv for this mutation; the plan prints it so it can be run by hand."""
    owner, name = repository(args.repo)
    if args.command == "resolve":
        return ["gh", "api", "graphql", "-F", f"threadId={args.thread_id}",
                "-f", f"query={RESOLVE_QUERY}"]
    return ["gh", "api", f"repos/{owner}/{name}/pulls/{args.pr}/comments/{args.comment_id}/replies",
            "-f", f"body={args.body}"]


def mutation(args: argparse.Namespace) -> int:
    """Print the plan, or with `--execute` run exactly the command the plan would have printed."""
    plan = {
        "action": args.command, "repo": args.repo, "pr": args.pr,
        "thread_id": args.thread_id, "comment_id": getattr(args, "comment_id", None),
        "execute": args.execute,
        "command": mutation_command(args),
    }
    if args.command == "reply":
        plan["body"] = args.body
    if not args.execute:
        print(json.dumps({"planned": plan}, indent=2))
        return 0
    result = gh(*plan["command"][1:])
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(result.stdout)
    return 0


def guard(action: argparse.ArgumentParser) -> None:
    """`--execute` is the only mutation switch; `--dry-run` is its inverse and forces the plan."""
    mode = action.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true",
                      help="perform the GitHub call (without it, print the plan and exit 0)")
    mode.add_argument("--dry-run", action="store_true",
                      help="print the plan naming the exact gh command; never calls gh")


# A PR comment is how a finding reaches the author, so every emitted label needs one — a nit
# included. Excluding nits produced a PR review with three findings, no `comments.md`, and no
# warning: the file is what the user pastes, and the nits were the whole review.
COMMENTED_LABELS = frozenset({"blocking", "attention", "needs more info", "nit"})
FENCE = "```"


def anchor(finding: Finding) -> str:
    """The `path:line` a comment attaches to, or "" when the finding has no usable anchor."""
    path = finding.text("file").strip()
    line = finding.text("line").strip()
    if not path:
        return ""
    return f"{path}:{line}" if line else path


def comment_body(finding: Finding) -> str:
    """The body written for this finding, or "" when the orchestrator wrote none."""
    return "" if finding.comment is ABSENT else str(finding.comment or "").strip()


def suggestion_block(finding: Finding) -> str:
    """The replacement code as a GitHub ```` ```suggestion ```` block, or "" when there is none.

    The fence carries no info string: GitHub turns a bare ```` ```suggestion ```` block into a
    one-click commit of the anchored range, so any other token silently demotes it to a plain code
    block. A writer that supplied its own fence — the common mistake, since the prose asks for one —
    is unwrapped here rather than rendered inside a second fence.
    """
    body = "" if finding.suggestion is ABSENT else str(finding.suggestion or "")
    body = body.strip("\n")
    if body.lstrip().startswith(FENCE) and body.rstrip().endswith(FENCE):
        inner = body.lstrip()[len(FENCE):]
        body = inner[:inner.rindex(FENCE)]
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.strip("\n")
    if not body.strip():
        return ""
    return f"{FENCE}suggestion\n{body}\n{FENCE}"


def missing_comments(findings: list[Finding], mode: str) -> list[str]:
    """Titles of emitted findings that still need a comment body, in report order.

    Only PR mode is gated: a self-review's findings are read by the person who ran it, so demanding
    a second wording there would be a copy of the same text with no reader.
    """
    if mode != "pr":
        return []
    return [f.title for f in findings
            if f.is_emitted() and f.label in COMMENTED_LABELS and not comment_body(f)]


def render(findings: list[Finding], head: str = "") -> str:
    """`comments.md`: one section per comment, in report order, each ready to paste.

    Order is the report's, so a reviewer pastes in the order they wrote the review. Nothing is
    repeated from the report's prose: the body is the whole comment, because the author of the PR
    reads one comment at a time and never sees this file.
    """
    lines = [
        "# Review comments",
        "",
        "One body per anchor, in the order of `report.md`. Paste each under its own line; nothing "
        "here was posted. A body ending in a GitHub suggestion block is a one-click commit of the "
        "anchored range.",
        "",
    ]
    if head:
        lines += [f"Reviewed at: {head}", ""]
    drafted = [f for f in findings if f.is_emitted() and comment_body(f)]
    if not drafted:
        return "\n".join(lines + ["No comments were drafted for this review.", ""])
    for index, finding in enumerate(drafted, 1):
        lines += [
            f"## {index}. {anchor(finding) or 'no anchor'}",
            "",
            f"_{label_with_score(finding)} {finding.title}_",
            "",
            comment_body(finding),
            "",
        ]
        replacement = suggestion_block(finding)
        if replacement:
            # The block goes inside the body, last: a suggestion is the actionable half of the
            # comment, and GitHub reads it from the comment text rather than from this file.
            lines += [replacement, ""]
        excerpt = finding.text("excerpt").strip()
        if excerpt:
            lines += ["Verified lines:", "", FENCE, excerpt, FENCE, ""]
        lines += ["---", ""]
    return "\n".join(lines)


def write_for_mode(review_dir: Path, findings: list[Finding], mode: str,
                   head: str = "") -> Path | None:
    """Write `comments.md` for a PR review; None when a PR review exists but worded nothing.

    Three cases, and the file matters in two of them. A clean review — no emitted finding at all —
    still gets the file, saying so, because Step 8 reports its path and must never link a file that
    was not written. Emitted findings with bodies get the
    file. Emitted findings with no bodies get a warning and no file: a file saying "no comments were
    drafted" would misreport findings that exist but were never worded.
    """
    if mode != "pr":
        return None
    pending = missing_comments(findings, mode)
    if pending:
        print(f"warning: no comment drafted for {len(pending)} finding(s): "
              f"{'; '.join(pending)}", file=sys.stderr)
    if not any(f.is_emitted() for f in findings):
        return write(review_dir, findings, head)
    if not any(f.is_emitted() and comment_body(f) for f in findings):
        print("warning: no paste-ready comment exists for this PR review; add a `comment` body to "
              "each finding, then re-run `crew-review-findings.py comments --review-dir "
              f"{review_dir}`", file=sys.stderr)
        return None
    return write(review_dir, findings, head)


def write(review_dir: Path, findings: list[Finding], head: str = "") -> Path:
    """Write `comments.md` beside the report, returning the path."""
    path = review_dir / "comments.md"
    atomic_write(path, render(findings, head))
    return path


def findings_from(path: Path) -> list[Finding]:
    """Emitted findings from a written findings file, for a caller re-rendering comments later."""
    payload = read_json_object(path, "findings")
    return [to_finding(item, index) for index, item in enumerate(payload["findings"], 1)]


def comments(args: argparse.Namespace) -> int:
    """Write `comments.md` and report what it holds; exit 1 when a body is still missing.

    A clean review is not a failure: it writes a file saying so and exits 0, because the report links
    this path and a missing file would read as a broken run.
    """
    review_dir = args.review_dir.resolve()
    findings = findings_from(args.findings or review_dir / "consolidation.json")
    pending = missing_comments(findings, "pr")
    if pending:
        for title in pending:
            print(f"review-findings: no comment drafted for {title!r}", file=sys.stderr)
        return 1
    path = write(review_dir, findings, args.head)
    drafted = [f for f in findings if f.is_emitted() and comment_body(f)]
    print(bounded_json({"comments": str(path), "drafted": len(drafted)}, args.max_chars,
                       what="comments summary"))
    return 0


def check_map(args: argparse.Namespace) -> int:
    """Parse the layers reply and print the map as JSON, or fail naming the parse error."""
    payload = parse_map_block(Path(args.reply).read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    summary = {"layers": len(payload["layers"])}
    if args.output:
        summary["out"] = str(args.output)
    print(bounded_json(summary, args.max_chars, what="layer map"))
    return 0
