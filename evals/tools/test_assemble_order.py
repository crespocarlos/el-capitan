#!/usr/bin/env python3
"""The package layout: one shared head and the whole diff before any per-persona material.

Every persona receives the same contract, hunk reference, memory and diff, so the bytes they share
are worth paying for once — but only if they are a *prefix*. This suite pins the order, the
byte-identical head, the diff embedded unchanged, and the per-persona material that must still
arrive after it. It also pins the two cost regressions the same build could reintroduce: a second
read of `package.diff` for the prompt tier, and a PR-mode config that asks for a local-index extra.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-assemble-packages.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "assemble"
REVIEW_TOOL = ROOT / ".agent" / "tools" / "review"
PERSONAS = ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality")
CONSUMER_PERSONAS = ("adversarial", "architecture", "product-flow")
PRIOR_HEADING = "## Already reported in an earlier round"

# The tail sections that every package carries, in the order the build must emit them after the diff.
TAIL_HEADINGS = ("# Size gate", "## Spec", "## Reading map", "# Repository guidance",
                 PRIOR_HEADING)


def fixture_repo(tmp: Path) -> Path:
    """A repository holding the two files the consumer and prompt extras read."""
    repo = tmp / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "prompts" / "rule.md").write_text(
        "# Rule\n\n## Rule\nnew wording\nextra wording\nkeep this line\n")
    (repo / ".agent" / "tools" / "review").mkdir(parents=True)
    (repo / ".agent" / "tools" / "review" / "assemble_build.py").write_text(
        "def build(persona, review_dir, config, shared, hunks_json):\n"
        '    report = {"whole": []}\n'
        "    parts = [shared]\n"
        "    return parts\n")
    return repo


def prior_round(tmp: Path) -> Path:
    """An earlier round carrying one finding, so every package gains the prior-round block."""
    previous = tmp / "review" / "20260101000000"
    previous.mkdir(parents=True)
    (previous / "consolidation.json").write_text(json.dumps([{
        "file": ".agent/tools/review/assemble_build.py", "line": 18, "label": "nit",
        "fingerprint": "aaa", "title": "The build reads the diff twice", "disposition": "patch"}]))
    return previous


RUN_STDOUT: dict[Path, str] = {}


def run(tmp: Path, config: dict | None = None) -> Path:
    """A packaged review directory built from the checked-in fixtures.

    The tool's stdout is kept in `RUN_STDOUT`, keyed by review directory: it is where the guidance
    narrowing report goes, and a suite that captures it and drops it cannot assert the "never
    silently" half of that contract.
    """
    review = tmp / "review" / "20260102000000"
    review.mkdir(parents=True)
    for name in ("package.diff", "hunks.index.md", "hunks.json", "layers.json",
                 "agent-context.json", "mem.md"):
        (review / name).write_bytes((FIXTURES / name).read_bytes())
    for persona in PERSONAS:
        (review / f"spec.{persona}.md").write_text(f"SPEC for {persona}\n")
    payload = {
        "repo": str(fixture_repo(tmp)),
        "size_gate": "Size gate: full diff — 2 files, 4 changed lines\n",
        "consumers": [[".agent/tools/review/assemble_build.py", 18, 21, "the builder"]],
        "prompt_files": ["prompts/rule.md"],
        "prior_review_dir": str(prior_round(tmp)),
        "guidance_keep": {"code-quality": ["Testing"]},
    }
    payload.update(config or {})
    (review / "assemble.json").write_text(json.dumps(payload))
    result = subprocess.run([sys.executable, str(TOOL), str(review)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    RUN_STDOUT[review] = result.stdout
    return review


def packages(review: Path) -> dict[str, str]:
    return {persona: (review / f"{persona}.in.md").read_text(encoding="utf-8")
            for persona in PERSONAS}


def diff_text() -> str:
    return (FIXTURES / "package.diff").read_text(encoding="utf-8")


def diff_span(text: str) -> tuple[int, int]:
    """Where the embedded diff sits: (start of the fenced block, byte after the diff)."""
    start = text.index(diff_text())
    return start, start + len(diff_text())


def first_difference(left: str, right: str) -> int:
    """The index of the first byte two packages disagree on."""
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right))


# --- the order -------------------------------------------------------------


def test_the_shared_head_comes_first_and_the_diff_follows_it(tmp: Path) -> None:
    """Contract, hunk reference and memory before the diff; the per-persona tail after it."""
    texts = packages(run(tmp))
    for persona, text in texts.items():
        order = ["# Shared reviewer contract", "## Hunk reference", "# Repo memory",
                 "# Diff (package.diff", *TAIL_HEADINGS]
        if persona in CONSUMER_PERSONAS:
            order.append("# Consumers of the changed contracts")
        if persona == "prompt-quality":
            order.append("# Prompt tier")
        positions = [text.index(heading) for heading in order]
        assert positions == sorted(positions), f"{persona}: {list(zip(order, positions))}"


def test_the_shared_head_is_byte_identical_across_personas(tmp: Path) -> None:
    texts = packages(run(tmp))
    heads = {persona: text[:diff_span(text)[0]] for persona, text in texts.items()}
    reference = heads["adversarial"]
    for persona, head in heads.items():
        assert head == reference, f"{persona} shares only {first_difference(head, reference)} bytes"


def test_the_whole_diff_is_embedded_with_no_hunk_filtered(tmp: Path) -> None:
    """A package carries `package.diff` byte for byte: no hunk collapsed, elided, or reordered."""
    texts = packages(run(tmp))
    for persona, text in texts.items():
        start, end = diff_span(text)
        assert text[start:end] == diff_text(), persona
        assert text.count(diff_text()) == 1, f"{persona} carries the diff more than once"


def test_the_first_difference_between_personas_falls_after_the_diff(tmp: Path) -> None:
    """The prefix is as long as the shared content, which is the whole point of the order."""
    texts = packages(run(tmp))
    for other in PERSONAS[1:]:
        left, right = texts["adversarial"], texts[other]
        boundary = diff_span(left)[1]
        difference = first_difference(left, right)
        assert difference >= boundary, (
            f"adversarial and {other} diverge at {difference}, inside the shared head/diff "
            f"which ends at {boundary}")


# --- the per-persona tail --------------------------------------------------


def test_every_persona_still_receives_its_own_material(tmp: Path) -> None:
    texts = packages(run(tmp))
    for persona, text in texts.items():
        start, end = diff_span(text)
        tail = text[end:]
        assert f"SPEC for {persona}" in tail, f"{persona} lost its own spec context"
        assert "## Reading map" in tail, f"{persona} lost its reading map"
        assert PRIOR_HEADING in tail, f"{persona} lost the prior-round block"
        assert "The build reads the diff twice" in tail, persona
    # The fixture map's `core` layer is adversarial's primary kind, so the ordering is preserved.
    assert "Your primary layers: 1" in texts["adversarial"]


def test_only_the_lenses_that_use_them_get_consumers_and_the_prompt_tier(tmp: Path) -> None:
    texts = packages(run(tmp))
    for persona, text in texts.items():
        tail = text[diff_span(text)[1]:]
        has_consumers = "# Consumers of the changed contracts" in tail
        has_tier = "# Prompt tier" in tail
        assert has_consumers == (persona in CONSUMER_PERSONAS), persona
        assert has_tier == (persona == "prompt-quality"), persona
    assert "the builder" in texts["architecture"]


def test_narrowed_guidance_stays_in_the_tail_and_reports_what_it_dropped(tmp: Path) -> None:
    """Guidance is narrowed per lens, so it cannot sit in the shared head — and never silently."""
    review = run(tmp)
    text = (review / "code-quality.in.md").read_text(encoding="utf-8")
    tail = text[diff_span(text)[1]:]
    assert "## Testing" in tail and "## File layout" not in tail
    assert "# Repository guidance" in tail
    assert "## File layout" in (review / "architecture.in.md").read_text(encoding="utf-8")
    report = RUN_STDOUT[review]
    assert "guidance narrowed, 1 section(s) dropped" in report, report
    assert "File layout" in report, report


# --- the duplicate read, and the PR-mode refusal ---------------------------


def test_a_prompt_quality_build_reads_the_diff_once(tmp: Path) -> None:
    """The prompt tier needs the diff the build already holds; a second read is a second source."""
    review = run(tmp, {"guidance_keep": {}})
    sys.path[:0] = [str(ROOT / ".agent" / "tools"), str(REVIEW_TOOL)]
    import assemble_build  # noqa: E402 - the path must be set first

    original = pathlib.Path.read_text
    reads: list[Path] = []

    def counting(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "package.diff":
            reads.append(self)
        return original(self, *args, **kwargs)

    pathlib.Path.read_text = counting  # type: ignore[method-assign]
    try:
        content, _report = assemble_build.build(
            "prompt-quality", review, json.loads((review / "assemble.json").read_text()),
            "HEAD\n", json.loads((review / "hunks.json").read_text()))
    finally:
        pathlib.Path.read_text = original  # type: ignore[method-assign]
    assert len(reads) == 1, f"package.diff was read {len(reads)} times"
    assert diff_text() in content


def test_pr_mode_refuses_the_extras_that_read_the_local_index(tmp: Path) -> None:
    """Both extras come from the local checkout, which a PR review must not read."""
    sys.path[:0] = [str(ROOT / ".agent" / "tools"), str(REVIEW_TOOL)]
    from assemble_config import check_inputs  # noqa: E402 - the path must be set first

    review = run(tmp)
    for key in ("consumers", "prompt_files"):
        config = {"mode_kind": "pr",
                  key: json.loads((review / "assemble.json").read_text())[key]}
        problem = check_inputs(review, config)
        assert key in problem and "PR mode" in problem, f"{key}: {problem!r}"
    assert check_inputs(review, {"mode_kind": "pr"}) == "", "a PR run with no extras must proceed"


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except Exception as error:  # noqa: BLE001 - one broken test must not hide the rest
                failed += 1
                print(f"FAIL: {test.__name__}: {type(error).__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
