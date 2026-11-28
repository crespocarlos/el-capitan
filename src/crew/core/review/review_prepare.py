"""`crew-tool.py review-prepare`: a review's setup in one call, for every mode.

In order: the review directory; in self, changes and PR mode the diff (`diff.patch`, `paths.txt`, the hunk
artifacts, PR head files under `head/`); `agent-context.json` and `mem.md`; `select`; and `assemble.json`, whose
`pending` keys (the questions, a spine size gate) assembly refuses until written. Spec and idea runs stamp the questions rule
instead. Prints the directory, then one summary line; a failure names its step (exit 1 nothing to review, else 2).
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path

from crew.core.review.assemble_inputs import DEFAULT_MODE
from crew.core.review.review_head import MAX_FILE_BYTES, fetch_head, pr_head, summary
from crew.core.review.review_hunks import check_diff, package_diff, write_hunks
from crew.core.review.review_vocabulary import CODE_MODES, QUESTIONS_STAMP, SELECT_RULES, mode_arg, selected
from crew.core.review.review_workspace import MANIFEST_FILE, claim, cleanup_stale, manifest, prior_review_dir, read, review_dir, unchanged_since, write
from crew.core.task.task_guidance import collect, memory_context
from crew.lib.errors import StepFailed, ToolError
from crew.lib.git import GitError, base_ref, fork_point, gh, merge_base, output, repo_slug, run_git, toplevel
from crew.lib.runs import append_run

SPINE_FILES, SPINE_LINES = 30, 1500
# Untracked files whose name says secret: never copied into a diff that every persona package carries.
SECRET_NAMES = (".env*", "*.pem", "*.key", "id_rsa*", "*.p12", "credentials*")


@dataclass(frozen=True)
class Request:
    """What `review_prepare` was asked: its parameters, read by every step."""

    mode: str
    task_dir: str
    base: str
    root: Path | None
    pr: int
    repo: str
    paths: list[str]
    query: str
    contract: bool
    compat: bool


def local_root(explicit: Path | None) -> Path | None:
    try:
        return toplevel(explicit)
    except GitError:
        return None


def held_back(root: Path, path: str) -> bool:
    """An untracked file the self diff leaves out: a secret-shaped name, or more than `MAX_FILE_BYTES`."""
    if any(fnmatch.fnmatch(Path(path).name, pattern) for pattern in SECRET_NAMES):
        return True
    try:
        return (root / path).stat().st_size > MAX_FILE_BYTES
    except OSError:
        return False


def self_diff(root: Path, base: str) -> tuple[str, list[str]]:
    """`base` (default: the fork point) against the working tree, untracked files included, as one patch; plus the
    untracked files held back. A builder's new files are untracked, so they must be reviewed."""
    start = merge_base(root, base) if base else fork_point(root, base_ref(root))
    patch, skipped = output(root, ["diff", start]), []
    for path in output(root, ["ls-files", "--others", "--exclude-standard", "-z"]).split("\0"):
        if not path:
            continue
        if held_back(root, path):
            skipped.append(path)
            continue
        added = run_git(root, ["diff", "--no-index", "--", "/dev/null", path], check=False)
        if added.returncode not in (0, 1):
            raise GitError(added.stderr.strip() or f"cannot diff untracked {path}")
        patch += added.stdout
    return patch, skipped


def read_diff(mode: str, root: Path | None, args: Request) -> tuple[str, list[str]]:
    if mode == "pr":
        result = gh("pr", "diff", str(args.pr), "--repo", args.repo)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"gh exit {result.returncode}")
        return result.stdout, []
    if root is None:
        raise ValueError("not in a git checkout; pass --root <checkout>")
    return self_diff(root, args.base) if mode == "self" else (output(root, ["diff", "--cached"]), [])


def diff_step(chosen: Path, mode: str, root: Path | None, args: Request, parts: list[str]) -> dict:
    """Write `diff.patch`, `paths.txt` and the hunk artifacts; return the parsed diff."""
    text, skipped = read_diff(mode, root, args)
    if skipped:
        parts.append(f"untracked files not reviewed (secret-shaped or over 256 KiB): {', '.join(skipped)}; `git add -N <path>` reviews one")
    (chosen / "diff.patch").write_text(text, encoding="utf-8")
    try:
        parsed = check_diff(text, "the diff")
    except ValueError as error:
        raise ToolError("nothing_to_review", f"diff: {error}; nothing to review", "diff") from error
    write_hunks(parsed, chosen, package_diff(text, parsed))
    (chosen / "paths.txt").write_text("".join(f"{e['path']}\n" for e in parsed["files"]), encoding="utf-8")
    return parsed


def size_gate(parsed: dict) -> str:
    files = len(parsed["files"])
    lines = sum(h["additions"] + h["deletions"] for h in parsed["hunks"])
    if files > SPINE_FILES or lines > SPINE_LINES:
        return ""  # pending: the orchestrator writes the spine strategy
    return f"Size gate: full diff — {files} files, {lines} changed lines"


def guidance_root(mode: str, root: Path | None, repo: str) -> tuple[Path | None, str]:
    """The checkout guidance is read from; in PR mode only a checkout of the PR's own repository."""
    if root is None:
        return None, "no local checkout: the packages carry no guidance"
    if mode == "pr":
        try:
            same = repo_slug(root).split("/")[1].lower() == repo.split("/")[-1].lower()
        except GitError:
            same = False
        if not same:
            return None, f"{root} is not a checkout of {repo}: the packages carry no guidance"
    return root, ""


def context_step(chosen: Path, mode: str, root: Path | None, paths: list[str], args: Request) -> list[str]:
    """`agent-context.json` and `mem.md`; returns the notes a gap leaves."""
    notes = []
    checkout, note = guidance_root(mode, root, args.repo)
    record = {"files": {}, "targets": []}
    if checkout is not None:
        record = collect(checkout, [checkout / p for p in paths] or [checkout])
    elif note:
        notes.append(note)
    (chosen / "agent-context.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    text, reason = memory_context("review", args.query, paths, repo=args.repo or None, root=root)
    if text is None:
        notes.append(f"memory unavailable ({reason})")
    else:
        (chosen / "mem.md").write_text(text, encoding="utf-8")
    return notes


def mode_block(mode: str, root: Path | None, args: Request, head: str) -> str:
    start = f"the merge base with {args.base}" if args.base else "the fork point"
    source = {
        "self": f"Self review of {root}: {start} against the working tree, untracked files included.",
        "changes": f"Changes review of {root}: the staged diff.",
        "pr": f"PR review of #{args.pr} in {args.repo} at head {head[:7]}, read only at that SHA.",
    }[mode]
    return DEFAULT_MODE.replace("# Mode\n\n", f"# Mode\n\n{source}\n\n", 1)


def skeleton(mode: str, root: Path | None, parsed: dict, personas: list[str], extra: dict) -> dict:
    """`assemble.json` as prepared: facts filled in, and `pending` naming the keys the orchestrator's judgement writes."""
    gate = size_gate(parsed)
    config: dict = {
        "schema_version": 1,
        "mode": extra["mode"],
        "size_gate": gate,
        "selected": personas,
        "questions": {p: [] for p in personas},
        "pending": ["questions", *([] if gate else ["size_gate"])],
    }
    if mode == "pr":
        config["mode_kind"] = "pr"
        return config
    config["repo"] = str(root)
    prompts = [e["path"] for e in parsed["files"] if SELECT_RULES["prompt-quality"].search(e["path"]) and (Path(str(root)) / e["path"]).is_file()]
    if prompts:
        config["prompt_files"] = prompts
    if extra.get("prior"):
        config["prior_review_dir"] = extra["prior"]
    return config


def prior_step(chosen: Path, root: Path, paths: list[str], parts: list[str]) -> str | None:
    """Write this round's manifest; the earlier round's directory, with how many files it saw unchanged in `parts`."""
    current = manifest(root, paths)
    write(chosen, current)
    previous = prior_review_dir(chosen)
    if previous is None:
        return None
    same = unchanged_since(root, current, read(previous) or {})
    parts.append(f"prior round {previous.name}: {len(same)} of {len(paths)} files unchanged")
    return str(previous)


def stamp_questions(chosen: Path) -> None:
    """Hold hand-composed spec and idea packages to the questions rule, as assembled ones are."""
    path = chosen / MANIFEST_FILE
    record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    record["personas"] = {**(record.get("personas") or {}), QUESTIONS_STAMP: True}
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_steps(args: Request, mode: str) -> tuple[Path, str]:
    root = local_root(args.root)
    pr = mode == "pr"
    if pr and not (args.pr and "/" in args.repo):
        raise StepFailed("arguments", "PR mode needs --pr N and --repo OWNER/REPO")
    task_dir = None if pr else (args.task_dir or None)
    name = args.repo.split("/")[-1] if pr else (root.name if root else "review")
    step = "review-dir"
    try:
        chosen = review_dir(task_dir, name, mode)
        claim(chosen, mode, name, task_dir)
        cleanup_stale(chosen.parent, chosen)
        parsed, extra, parts, found = {"files": [], "hunks": []}, {}, [], {"sha": ""}
        if pr:
            step = "head"
            found = pr_head(args.repo, args.pr)
        if mode in CODE_MODES:
            step = "diff"
            parsed = diff_step(chosen, mode, root, args, parts)
        if pr:
            step = "head"
            moved = pr_head(args.repo, args.pr)["sha"]
            if moved != found["sha"]:
                raise StepFailed(step, f"the PR moved from {found['sha'][:7]} to {moved[:7]} during prepare; rerun")
        paths = [e["path"] for e in parsed["files"]] or list(args.paths)
        if mode in ("self", "changes"):
            step = "prior-review"
            extra["prior"] = prior_step(chosen, root, paths, parts)
        if pr:
            step = "head"
            parts.append("head: " + summary(fetch_head(found["head_repo"], found["sha"], paths, chosen / "head")))
        step = "context"
        notes = context_step(chosen, mode, root, paths, args)
        step = "select"
        personas = sorted(selected(mode, paths, args.contract, args.compat))
        step = "assemble.json"
        if mode in CODE_MODES:
            extra["mode"] = mode_block(mode, root, args, found["sha"])
            config = skeleton(mode, root, parsed, personas, extra)
            (chosen / "assemble.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            parts.insert(0, f"{len(parsed['files'])} files, {len(parsed['hunks'])} hunks; {config['size_gate'] or 'size gate: spine strategy'}")
            parts.append(f"write the pending {', '.join(config['pending'])} in assemble.json, then crew-tool.py review-dispatch")
        else:
            stamp_questions(chosen)
            parts.append("compose the packages by hand, each ending with its lens questions")
    except (GitError, RuntimeError, ValueError, OSError) as error:
        raise StepFailed(step, str(error)) from error
    line = "; ".join([f"prepare: {mode}", *parts[:1], f"personas {' '.join(personas)}", *parts[1:], *notes])
    return chosen, line


@dataclass
class Prepared:
    """The review directory and one summary line."""

    review_dir: str
    summary: str


def review_prepare(
    mode: str,
    task_dir: str = "",
    base: str = "",
    root: str = "",
    pr: int = 0,
    repo: str = "",
    paths: list[str] | None = None,
    query: str = "",
    contract: bool = False,
    compat: bool = False,
) -> Prepared:
    """A review's setup in one call: directory, diff, hunks, guidance, memory, persona selection, assemble.json.

    Args:
        mode: self, changes, pr, spec or idea (`auto` modifiers accepted)
        task_dir: the resolved task; PR mode ignores it
        base: self mode: diff from merge-base(BASE, HEAD) (default: the fork point from the default branch)
        root: the reviewed checkout (default: the current one)
        pr: PR mode: the PR number
        repo: PR mode: OWNER/REPO
        paths: spec and idea: the paths guidance is read for
        query: the memory query, such as the spec or PR title
    """
    args = Request(mode_arg(mode), task_dir, base, Path(root) if root else None, pr, repo, paths or [], query, contract, compat)
    if args.mode not in CODE_MODES | {"spec", "idea"}:
        raise StepFailed("arguments", f"unknown mode {mode!r}")
    chosen, line = run_steps(args, args.mode)
    target = f"{repo}#{pr}" if args.mode == "pr" else repo or Path.cwd().name
    append_run(str(chosen.resolve()), "start", kind="review", mode=args.mode, target=target, task="" if args.mode == "pr" else task_dir)
    return Prepared(str(chosen), line)
