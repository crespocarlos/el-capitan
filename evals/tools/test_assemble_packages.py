#!/usr/bin/env python3
"""`crew-assemble-packages.py`: the packages every persona reads, and the prior-round machinery behind them.

Every persona receives the same shared head and the whole diff as a byte-identical prefix, then its
own material; the prompt tier does not re-send what the diff already quotes; an earlier round's
findings arrive with the author's recorded decision; and a file reviewed unchanged since that round
is collapsed with its hunk ids still citable. The command runs in this process (`cli_runner`).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
from pathlib import Path

from cli_runner import run as cli

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review" / "crew-assemble-packages.py"

DIFF = """diff --git a/prompt.md b/prompt.md
--- a/prompt.md
+++ b/prompt.md
@@ -2,3 +2,4 @@
 line two
-old rule
+new rule
+extra rule
 line five
"""

WHOLE = """# Prompt

line two
new rule
extra rule
line five
line six
"""


def build(tmp: Path, config: dict | None = None, guidance: dict | None = None) -> Path:
    run = tmp / "review" / "20260101000000"
    run.mkdir(parents=True)
    (run / "package.diff").write_text(DIFF)
    (run / "hunks.index.md").write_text("# Hunk index (1 hunk in 1 file)\n\n- `prompt.md`: h1 @2(+2/-1)\n")
    (run / "hunks.json").write_text(json.dumps({
        "files": [{"path": "prompt.md", "hunkIds": ["h1"]}], "hunks": [{"id": "h1", "file": "prompt.md"}]}))
    (run / "layers.json").write_text(json.dumps({"layers": [{
        "kind": "prompts", "title": "one prompt change", "explainer": "- why",
        "reviewFocus": "- what", "hunks": ["h1"], "hunkNotes": {"h1": "the rule"}}]}))
    (run / "mem.md").write_text("no entries\n")
    (run / "agent-context.json").write_text(json.dumps({"files": guidance or {}}))
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "prompt.md").write_text(WHOLE)
    for persona in ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality"):
        (run / f"spec.{persona}.md").write_text(f"SPEC for {persona}\n")
    payload = {"repo": str(repo), "prompt_files": ["prompt.md"]}
    payload.update(config or {})
    (run / "assemble.json").write_text(json.dumps(payload))
    result = cli(TOOL, str(run))
    assert result.returncode == 0, result.stderr
    return run


def read(run: Path, persona: str) -> str:
    return (run / f"{persona}.in.md").read_text()


def test_prompt_tier_elides_what_the_diff_already_quotes(tmp: Path) -> None:
    """Collapsing a run shifts every offset after it, so kept lines carry their file line numbers."""
    run = build(tmp)
    text = read(run, "prompt-quality")
    tier = text[text.index("# Prompt tier"):]
    assert "\n6: line five\n" in tier and "\n7: line six\n" in tier, "unchanged text outside the hunk survives, numbered"
    assert "line two" not in tier, "a context line inside the hunk is already in the diff"
    assert "… (lines 2-5 are in the diff above)" in tier
    assert "new rule" not in tier, "the added line is in the diff"
    assert "\n1: # Prompt\n" in tier


def test_guidance_narrowing_is_opt_in_and_keeps_pre_heading_text(tmp: Path) -> None:
    guidance = {"/repo/AGENTS.md": "# Kibana\n\npreamble stays\n\n## Code Style Guidelines\ncss\n\n## Data model\ndata\n"}
    wide = build(tmp / "wide", guidance=guidance)
    assert "## Data model" in read(wide, "code-quality")
    narrow = build(tmp / "narrow", {"guidance_keep": {"code-quality": ["Code Style"]}}, guidance)
    text = read(narrow, "code-quality")
    assert "preamble stays" in text and "## Code Style Guidelines" in text
    assert "## Data model" not in text
    # A persona with no entry keeps everything: disappearing guidance is worse than costly guidance.
    assert "## Data model" in read(narrow, "architecture")


def test_a_wildcard_keeps_every_section(tmp: Path) -> None:
    guidance = {"/repo/AGENTS.md": "# R\n\n## Code Style Guidelines\nx\n\n## Data model\ny\n"}
    run = build(tmp, {"guidance_keep": {"adversarial": ["*"]}}, guidance)
    text = read(run, "adversarial")
    assert "## Code Style Guidelines" in text and "## Data model" in text


def test_a_missing_layer_map_still_produces_a_package(tmp: Path) -> None:
    run = build(tmp)
    (run / "layers.json").unlink()
    result = cli(TOOL, str(run))
    assert result.returncode == 0, result.stderr
    text = read(run, "adversarial")
    assert "## Reading map" not in text, "no map means no map, not an empty one"
    assert "## Hunk reference" in text, "the index survives without the map, as in a hand-built package"


def test_elision_falls_back_when_the_index_disagrees(tmp: Path) -> None:
    """An edited or truncated package.diff must not delete prompt text while claiming it is above."""
    run = build(tmp)
    (run / "hunks.json").write_text(json.dumps({
        "files": [{"path": "prompt.md", "hunkIds": ["h1", "h2"]}],
        "hunks": [{"id": "h1", "file": "prompt.md"}, {"id": "h2", "file": "prompt.md"}]}))
    result = cli(TOOL, str(run))
    assert result.returncode == 0, result.stderr
    assert "sent whole" in result.stdout, "the fallback must be visible in the run output"
    tier = read(run, "prompt-quality")
    assert "line two" in tier and "new rule" in tier, "the whole file must be present"


def test_elision_falls_back_without_a_hunk_index(tmp: Path) -> None:
    run = build(tmp)
    (run / "hunks.json").unlink()
    result = cli(TOOL, str(run))
    assert result.returncode == 0, result.stderr
    tier = read(run, "prompt-quality")
    assert "… (lines" not in tier and "new rule" in tier


def test_a_keep_list_that_matches_nothing_is_refused(tmp: Path) -> None:
    """A typo'd section name used to drop all guidance and still exit 0, which looks assembled."""
    guidance = {"/repo/AGENTS.md": "# R\n\n## Tests\nx\n\n## Data model\ny\n"}
    run = tmp / "review" / "20260101000003"
    run.mkdir(parents=True)
    (run / "package.diff").write_text(DIFF)
    (run / "hunks.index.md").write_text("# Hunk index\n\n- `prompt.md`: h1 @2(+2/-1)\n")
    (run / "agent-context.json").write_text(json.dumps({"files": guidance}))
    (run / "assemble.json").write_text(json.dumps({
        "guidance_keep": {"code-quality": ["Code Style Guidelines"]}}))
    result = cli(TOOL, str(run))
    assert result.returncode == 2
    assert "names no section" in result.stderr and "Tests" in result.stderr


def test_a_refusal_leaves_no_half_written_package_set(tmp: Path) -> None:
    """A refusal on the last persona must not leave the first four beside stale files."""
    guidance = {"/repo/AGENTS.md": "# R\n\n## Tests\nx\n"}
    run = tmp / "review" / "20260101000004"
    run.mkdir(parents=True)
    (run / "package.diff").write_text(DIFF)
    (run / "hunks.index.md").write_text("# Hunk index\n\n- `prompt.md`: h1 @2(+2/-1)\n")
    (run / "agent-context.json").write_text(json.dumps({"files": guidance}))
    (run / "adversarial.in.md").write_text("STALE from an earlier run")
    (run / "assemble.json").write_text(json.dumps({
        "guidance_keep": {"adversarial": ["Tests"], "prompt-quality": ["No Such Section"]}}))
    result = cli(TOOL, str(run))
    assert result.returncode == 2
    assert (run / "adversarial.in.md").read_text() == "STALE from an earlier run"


def test_pr_mode_refuses_local_excerpts(tmp: Path) -> None:
    """PR mode must not ship local excerpts (`--help` is `test_command_names.py`'s)."""

    run = tmp / "review" / "20260101000005"
    run.mkdir(parents=True)
    (run / "package.diff").write_text(DIFF)
    (run / "hunks.index.md").write_text("# Hunk index\n\n- `prompt.md`: h1 @2(+2/-1)\n")
    (run / "agent-context.json").write_text(json.dumps({"files": {}}))
    pr = {"mode_kind": "pr", "consumers": [["prompt.md", 1, 2, "a consumer"]]}
    (run / "assemble.json").write_text(json.dumps(pr))
    result = cli(TOOL, str(run))
    assert result.returncode == 2
    assert "PR mode" in result.stderr and "consumers" in result.stderr
    # With the extras removed, the same run packages normally.
    (run / "assemble.json").write_text(json.dumps({"mode_kind": "pr", "repo": str(tmp)}))
    assert cli(TOOL, str(run)).returncode == 0


def test_a_layer_without_kind_or_title_still_packages(tmp: Path) -> None:
    """The coverage gate requires neither, so the assembler must not crash on a map that passes it."""
    run = build(tmp)
    (run / "layers.json").write_text(json.dumps({"layers": [
        {"id": "L1", "explainer": "why", "reviewFocus": "- check", "hunks": ["h1"]}]}))
    result = cli(TOOL, str(run))
    assert result.returncode == 0, result.stderr
    text = read(run, "code-quality")
    assert "### 1. layer — L1" in text and "Explain: why" in text
    assert not (run / "_common.md").exists(), "no shared file is written any more"


def test_the_builders_unverified_claims_reach_every_persona(tmp: Path) -> None:
    report = tmp / "REPORT.md"
    report.write_text("### Unverified claims\n- cursor runs the hook — verify: `bash run.sh`\n\n### Files Changed\na\n")
    run = build(tmp / "new", {"report": str(report)})
    for persona in ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality"):
        text = read(run, persona)
        assert "## Builder's unverified claims" in text and "cursor runs the hook — verify: `bash run.sh`" in text, persona


def test_a_report_without_the_section_changes_nothing(tmp: Path) -> None:
    old = tmp / "REPORT.md"
    old.write_text("## Implementation Report\n\n### Quality gates\n- `npm test` — pass\n")
    plain = read(build(tmp / "plain"), "adversarial")
    for config in ({"report": str(old)}, {"report": str(tmp / "missing.md")}):
        text = read(build(tmp / f"with{len(str(config))}", config), "adversarial")
        assert "unverified claims" not in text and text.count("# Diff") == plain.count("# Diff")


def test_missing_inputs_are_reported(tmp: Path) -> None:
    run = tmp / "review" / "20260101000001"
    run.mkdir(parents=True)
    result = cli(TOOL, str(run))
    assert result.returncode == 2 and "package.diff" in result.stderr


def file_diff(path: str, body: str) -> str:
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,2 @@\n context\n"
            + "".join(f"+{line}\n" for line in body.splitlines()))


def custom_run(tmp: Path, files: dict[str, str], layers: list[dict], config: dict | None = None):
    """A review directory over several files; `layers` is `[(kind, [path, ...])]` shaped dicts."""
    run = tmp / "review" / "20260101000002"
    run.mkdir(parents=True)
    (run / "package.diff").write_text("".join(file_diff(p, b) for p, b in files.items()))
    hunks = [{"id": f"h{i}", "file": p} for i, p in enumerate(files, 1)]
    ids = {p: f"h{i}" for i, p in enumerate(files, 1)}
    (run / "hunks.index.md").write_text("# Hunk index\n\n" + "".join(f"- `{p}`: {ids[p]}\n" for p in files))
    (run / "hunks.json").write_text(json.dumps({"files": [], "hunks": hunks}))
    (run / "layers.json").write_text(json.dumps({"layers": [
        {"kind": kind, "title": kind, "explainer": "e", "reviewFocus": "f", "hunks": [ids[p] for p in paths]}
        for kind, paths in layers]}))
    (run / "mem.md").write_text("none\n")
    (run / "agent-context.json").write_text(json.dumps({"files": {}}))
    (run / "assemble.json").write_text(json.dumps(config or {}))
    done = cli(TOOL, str(run))
    assert done.returncode == 0, done.stderr
    return run, done.stdout


CODE_FILES = {"web/App.tsx": "const total = computeTotal(rows)", "core/engine.ts": "function computeTotal(rows) {}",
              "core/other.ts": "const unrelated = 1", "docs/guide.md": "notes about nothing"}
CODE_LAYERS = [("ui", ["web/App.tsx"]), ("core", ["core/engine.ts", "core/other.ts"]), ("docs", ["docs/guide.md"])]


def test_a_persona_that_cannot_apply_is_skipped_as_a_recorded_decision(tmp: Path) -> None:
    run, out = custom_run(tmp, CODE_FILES, CODE_LAYERS)
    assert not (run / "prompt-quality.in.md").exists() and (run / "adversarial.in.md").exists()
    assert "skipped: prompt-quality: no prompt" in out, out
    manifest = json.loads((run / "manifest.json").read_text())["personas"]
    assert manifest["schema_version"] == 1 and "prompt-quality" not in manifest["packaged"]
    assert manifest["skipped"] == [{"persona": "prompt-quality",
                                    "reason": "no prompt, agent, skill, rule or embedded prompt path in the diff"}]
    assert "size: adversarial" in out, "the per-persona size report is printed"


def test_a_prompt_embedded_in_code_keeps_prompt_quality(tmp: Path) -> None:
    run, out = custom_run(tmp, {"src/prompts/system.md": "be careful", "src/a.ts": "const x = 1"},
                          [("prompts", ["src/prompts/system.md"]), ("core", ["src/a.ts"])])
    assert (run / "prompt-quality.in.md").exists() and "skipped:" not in out, out
    run2, out2 = custom_run(tmp / "forced", {"src/a.ts": "const x = 1"}, [("core", ["src/a.ts"])],
                            {"skip_personas": {"architecture": "no contract changed"}})
    assert not (run2 / "architecture.in.md").exists() and "skipped: architecture: no contract changed" in out2


def test_slicing_is_opt_in_and_keeps_every_hunk_reachable(tmp: Path) -> None:
    def shown(run: Path, persona: str) -> str:
        text = read(run, persona)
        return text[text.index("# Diff"):text.index("\n```\n", text.index("```diff"))]

    whole, _ = custom_run(tmp / "off", CODE_FILES, CODE_LAYERS)
    assert "core/other.ts" in shown(whole, "product-flow"), "no slice unless asked"
    run, out = custom_run(tmp / "on", CODE_FILES, CODE_LAYERS, {"slice": True})
    flow = shown(run, "product-flow")
    assert "web/App.tsx" in flow and "docs/guide.md" in flow, "its primary layers"
    assert "core/engine.ts" in flow, "closure: App.tsx calls a symbol engine.ts defines, so it travels with it"
    assert "core/other.ts" not in flow and "sliced to 3 of 4 files" in flow, flow[:400]
    quality = shown(run, "code-quality")
    assert "docs/guide.md" not in quality and "web/App.tsx" in quality, "its caller travels with core code"
    for persona in ("adversarial", "architecture"):
        assert all(path in shown(run, persona) for path in CODE_FILES), f"{persona} keeps the whole diff"
    note = json.loads((run / "manifest.json").read_text())["personas"]["sliced"]["product-flow"]
    assert note["files"] == 3 and note["of"] == 4 and note["closure"] == ["core/engine.ts"], note
    assert "sliced 3 of 4 files" in out, out


def test_the_coverage_gate_refuses_a_slice_that_would_lose_a_hunk(tmp: Path) -> None:
    sys.path[:0] = [str(TOOL.parent), str(TOOL.parents[1])]
    import assemble_build

    diff = "".join(file_diff(p, b) for p, b in CODE_FILES.items())
    hunks = {"hunks": [{"id": f"h{i}", "file": p} for i, p in enumerate(CODE_FILES, 1)]}
    layers = [{"kind": "ui", "hunks": ["h1"]}, {"kind": "core", "hunks": ["h2"]}]
    sliced, note = assemble_build.plan(layers, hunks, diff, ["product-flow", "code-quality"])
    assert sliced == {} and "coverage gate" in note, (sliced, note)
    with_full, _ = assemble_build.plan(layers, hunks, diff, ["product-flow", "adversarial"])
    assert list(with_full) == ["product-flow"], "a lens reading the whole diff covers the rest"
    assert assemble_build.plan([], hunks, diff, ["adversarial"])[0] == {}


# --- the layout: one shared head and the whole diff before any per-persona material -------------

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "assemble"
REVIEW_TOOL = TOOL.parent
PERSONAS = ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality")
CONSUMER_PERSONAS = ("adversarial", "architecture", "product-flow")
PRIOR_HEADING = "## Already reported in an earlier round"
TAIL_HEADINGS = ("# Size gate", "## Spec", "## Reading map", "# Repository guidance", PRIOR_HEADING)
sys.path[:0] = [str(REVIEW_TOOL.parent), str(REVIEW_TOOL)]


def layout(tmp: Path, config: dict | None = None) -> tuple[Path, str]:
    """A packaged review built from the checked-in fixtures, with an earlier round carrying one finding."""
    repo = tmp / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "prompts" / "rule.md").write_text("# Rule\n\n## Rule\nnew wording\nextra wording\nkeep this line\n")
    (repo / ".agent" / "tools" / "review").mkdir(parents=True)
    (repo / ".agent" / "tools" / "review" / "assemble_build.py").write_text(
        "def build(persona, review_dir, config, shared, hunks_json):\n    report = {\"whole\": []}\n    parts = [shared]\n    return parts\n")
    previous = tmp / "review" / "20260101000000"
    previous.mkdir(parents=True)
    (previous / "consolidation.json").write_text(json.dumps([{"file": ".agent/tools/review/assemble_build.py", "line": 18, "label": "nit",
                                                               "fingerprint": "aaa", "title": "The build reads the diff twice", "disposition": "patch"}]))
    review = tmp / "review" / "20260102000000"
    review.mkdir(parents=True)
    for name in ("package.diff", "hunks.index.md", "hunks.json", "layers.json", "agent-context.json", "mem.md"):
        (review / name).write_bytes((FIXTURES / name).read_bytes())
    for persona in PERSONAS:
        (review / f"spec.{persona}.md").write_text(f"SPEC for {persona}\n")
    payload = {"repo": str(repo), "size_gate": "Size gate: full diff — 2 files, 4 changed lines\n",
               "consumers": [[".agent/tools/review/assemble_build.py", 18, 21, "the builder"]], "prompt_files": ["prompts/rule.md"],
               "prior_review_dir": str(previous), "guidance_keep": {"code-quality": ["Testing"]}, **(config or {})}
    (review / "assemble.json").write_text(json.dumps(payload))
    result = cli(TOOL, str(review))
    assert result.returncode == 0, result.stderr
    return review, result.stdout


def fixture_diff() -> str:
    return (FIXTURES / "package.diff").read_text(encoding="utf-8")


def test_the_layout_shares_a_byte_identical_head_and_the_whole_diff(tmp: Path) -> None:
    """Contract, hunk reference and memory, then the diff byte for byte; personas first differ after it."""
    review, report = layout(tmp)
    texts = {persona: (review / f"{persona}.in.md").read_text(encoding="utf-8") for persona in PERSONAS}
    diff = fixture_diff()
    for persona, text in texts.items():
        order = ["# Shared reviewer contract", "\n# Lookups\n", "## Hunk reference", "# Repo memory", "# Diff (package.diff", *TAIL_HEADINGS]
        order += ["# Consumers of the changed contracts"] if persona in CONSUMER_PERSONAS else []
        order += ["# Prompt tier"] if persona == "prompt-quality" else []
        positions = [text.index(heading) for heading in order]
        assert positions == sorted(positions), f"{persona}: {list(zip(order, positions))}"
        assert text.count(diff) == 1, f"{persona} must carry the diff once, unchanged"
        tail = text[text.index(diff) + len(diff):]
        assert f"SPEC for {persona}" in tail and "The build reads the diff twice" in tail, persona
        assert ("# Consumers of the changed contracts" in tail) == (persona in CONSUMER_PERSONAS), persona
        assert ("# Prompt tier" in tail) == (persona == "prompt-quality"), persona
    head = texts["adversarial"][:texts["adversarial"].index(diff) + len(diff)]
    assert all(text.startswith(head) for text in texts.values()), "the head and diff are not a shared prefix"
    assert "Your primary layers: 1" in texts["adversarial"] and "the builder" in texts["architecture"]
    code_quality = texts["code-quality"][texts["code-quality"].index(diff):]
    assert "## Testing" in code_quality and "## File layout" not in code_quality and "## File layout" in texts["architecture"]
    assert "guidance narrowed, 1 section(s) dropped" in report and "File layout" in report, report


def test_a_prompt_quality_build_reads_the_diff_once(tmp: Path) -> None:
    review, _ = layout(tmp, {"guidance_keep": {}})
    import assemble_build

    original, reads = pathlib.Path.read_text, []

    def counting(self: Path, *args: object, **kwargs: object) -> str:
        reads.extend([self] if self.name == "package.diff" else [])
        return original(self, *args, **kwargs)

    pathlib.Path.read_text = counting  # type: ignore[method-assign]
    try:
        content, _ = assemble_build.build("prompt-quality", review, json.loads((review / "assemble.json").read_text()), "HEAD\n",
                                          json.loads((review / "hunks.json").read_text()))
    finally:
        pathlib.Path.read_text = original  # type: ignore[method-assign]
    assert len(reads) == 1 and fixture_diff() in content, f"package.diff was read {len(reads)} times"


# --- the prior-round block and the machinery behind it -------------------------------------------

PRIOR = {"file": "prompt/discovery.md.text", "line": 11, "label": "nit", "fingerprint": "aaa",
         "title": "The flaky flag and the flaky_probe reason are explained in two bullets", "disposition": "patch"}
PRIOR_DIFF = ("diff --git a/a.ts b/a.ts\nindex 1111111..2222222 100644\n--- a/a.ts\n+++ b/a.ts\n@@ -1,2 +1,3 @@\n keep\n+added\n tail\n"
              "diff --git a/b.ts b/b.ts\nindex 3333333..4444444 100644\n--- a/b.ts\n+++ b/b.ts\n@@ -10,2 +10,2 @@\n-old\n+new\n tail\n")


def prior_dir(tmp: Path, findings: list | None) -> Path:
    directory = tmp / "review" / "20260101000000"
    directory.mkdir(parents=True)
    (directory / "run.json").write_text("{}")
    if findings is not None:
        (directory / "consolidation.json").write_text(json.dumps(findings))
    return directory


def test_the_prior_block_lists_findings_with_the_authors_decision_only_when_recorded(tmp: Path) -> None:
    from assemble_inputs import prior_section

    directory = prior_dir(tmp, [PRIOR, dict(PRIOR, fingerprint="bbb", title="word " * 200)])
    block = prior_section(directory)
    lines = [line for line in block.splitlines() if line.startswith("- [nit]")]
    assert PRIOR["title"] in block and "prompt/discovery.md.text:11" in block and "new evidence" in block.lower(), block
    assert not any(word in lines[0] for word in ("fixed", "rejected", "deferred", "skipped")), "an unrecorded decision was invented"
    assert all(len(line) < 220 for line in lines), "a long title is cut to keep the block small"
    (tmp / "review" / "outcomes.jsonl").write_text(json.dumps({"fingerprint": "aaa", "outcome": "rejected"}) + "\n")
    assert "rejected" in prior_section(directory)
    assert prior_section(prior_dir(tmp / "empty", [])) == "" and prior_section(prior_dir(tmp / "none", None)) == ""


def test_content_identity_is_gits_blob_id_and_unchanged_needs_it_on_both_sides(tmp: Path) -> None:
    import review_workspace as manifest

    target = tmp / "a.ts"
    target.write_text("one\n")
    assert manifest.blob_id(target) == hashlib.sha1(b"blob %d\0" % len(target.read_bytes()) + target.read_bytes()).hexdigest()
    git = subprocess.run(["git", "hash-object", "--", str(target)], capture_output=True, text=True)
    assert git.returncode != 0 or manifest.blob_id(target) == git.stdout.strip(), "blob id disagrees with git"
    assert manifest.blob_id(tmp / "gone.ts") is None
    (tmp / "b.ts").write_text("two\n")
    first = manifest.manifest(tmp, ["a.ts", "b.ts", "missing.ts"])
    assert list(first["files"]) == ["a.ts", "b.ts"]
    (tmp / "b.ts").write_text("changed\n")
    (tmp / "c.ts").write_text("three\n")
    assert manifest.unchanged_since(tmp, manifest.manifest(tmp, ["a.ts", "b.ts", "c.ts"]), first) == {"a.ts"}
    run = tmp / "review" / "20260101000000"
    run.mkdir(parents=True)
    manifest.write(run, first)
    assert manifest.read(run) is not None and manifest.read(run / manifest.MANIFEST_FILE) is not None and manifest.read(tmp / "absent") is None


def test_discovery_finds_the_previous_review_round_only(tmp: Path) -> None:
    import review_workspace as manifest

    review = tmp / "review"
    for name in ("20260101000000", "20260102000000", "20260103000000", "notes"):
        (review / name).mkdir(parents=True)
        (review / name / "run.json").write_text("{}")
    assert manifest.prior_review_dir(review / "20260103000000") == review / "20260102000000"
    assert manifest.prior_review_dir(review / "20260101000000") is None
    (tmp / "runs" / "20260101000000").mkdir(parents=True)
    assert manifest.prior_review_dir(tmp / "runs" / "20260101000000") is None, "a directory outside review/ has no prior"


def test_the_collapse_omits_a_reviewed_body_and_keeps_its_ids_citable(tmp: Path) -> None:
    import review_workspace as manifest
    from review_parse import parse

    parsed = parse(PRIOR_DIFF)
    collapsed = manifest.collapse_reviewed(PRIOR_DIFF, parsed, {"a.ts"}, "20260101000000")
    note = next(line for line in collapsed.splitlines() if "already reviewed at" in line)
    assert "h1" in note and "+added" not in collapsed and "b.ts" in collapsed and "+new" in collapsed, collapsed
    assert manifest.collapse_reviewed(PRIOR_DIFF, parsed, set(), "20260101000000") == PRIOR_DIFF
