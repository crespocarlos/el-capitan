#!/usr/bin/env python3
"""Contract checks for .agent/tools/review/crew-assemble-packages.py.

Two behaviours carry the value and can regress silently: every persona receives the same shared
header, and the prompt tier does not re-send what the diff already quotes. A package that lost its
contract or its hunk index still passes `check-packages`, which only looks for the phrases a persona
must never restate — so the coverage lives here.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

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
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return run


def read(run: Path, persona: str) -> str:
    return (run / f"{persona}.in.md").read_text()


def test_every_persona_gets_the_same_contract_and_hunk_reference(tmp: Path) -> None:
    run = build(tmp)
    for persona in ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality"):
        text = read(run, persona)
        assert "# Shared reviewer contract" in text, persona
        assert "## Hunk reference" in text and "h1 @2(+2/-1)" in text, persona
        assert "cites the hunk ids whose change causes it" in text, persona
        assert f"SPEC for {persona}" in text, persona
        assert "```diff" in text, persona


def test_prompt_tier_elides_what_the_diff_already_quotes(tmp: Path) -> None:
    run = build(tmp)
    text = read(run, "prompt-quality")
    tier = text[text.index("# Prompt tier"):]
    assert "line six" in tier, "unchanged text outside the hunk must survive"
    assert "line two" not in tier, "a context line inside the hunk is already in the diff"
    assert "… (lines 2-5 are in the diff above)" in tier
    assert "new rule" not in tier, "the added line is in the diff"
    # The other personas get no prompt tier at all.
    assert "# Prompt tier" not in read(run, "code-quality")


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
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
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
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "sent whole" in result.stdout, "the fallback must be visible in the run output"
    tier = read(run, "prompt-quality")
    assert "line two" in tier and "new rule" in tier, "the whole file must be present"


def test_elision_falls_back_without_a_hunk_index(tmp: Path) -> None:
    run = build(tmp)
    (run / "hunks.json").unlink()
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    tier = read(run, "prompt-quality")
    assert "… (lines" not in tier and "new rule" in tier


def test_dropped_guidance_sections_are_printed(tmp: Path) -> None:
    guidance = {"/repo/AGENTS.md": "# R\n\n## Code Style Guidelines\nx\n\n## Data model\ny\n"}
    run = tmp / "review" / "20260101000002"
    run.mkdir(parents=True)
    (run / "package.diff").write_text(DIFF)
    (run / "hunks.index.md").write_text("# Hunk index\n\n- `prompt.md`: h1 @2(+2/-1)\n")
    (run / "agent-context.json").write_text(json.dumps({"files": guidance}))
    (run / "assemble.json").write_text(json.dumps({
        "repo": str(tmp), "guidance_keep": {"code-quality": ["Code Style"]}}))
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "guidance narrowed, 1 section(s) dropped" in result.stdout
    assert "Data model" in result.stdout


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
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
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
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 2
    assert (run / "adversarial.in.md").read_text() == "STALE from an earlier run"


def test_cli_offers_help_and_pr_mode_refuses_local_excerpts(tmp: Path) -> None:
    """`--help` must work (the catalog claims argparse), and PR mode must not ship local excerpts."""
    helped = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True)
    assert helped.returncode == 0 and "review_dir" in helped.stdout

    run = tmp / "review" / "20260101000005"
    run.mkdir(parents=True)
    (run / "package.diff").write_text(DIFF)
    (run / "hunks.index.md").write_text("# Hunk index\n\n- `prompt.md`: h1 @2(+2/-1)\n")
    (run / "agent-context.json").write_text(json.dumps({"files": {}}))
    pr = {"mode_kind": "pr", "consumers": [["prompt.md", 1, 2, "a consumer"]]}
    (run / "assemble.json").write_text(json.dumps(pr))
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "PR mode" in result.stderr and "consumers" in result.stderr
    # With the extras removed, the same run packages normally.
    (run / "assemble.json").write_text(json.dumps({"mode_kind": "pr", "repo": str(tmp)}))
    assert subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True).returncode == 0


def test_a_layer_without_kind_or_title_still_packages(tmp: Path) -> None:
    """The coverage gate requires neither, so the assembler must not crash on a map that passes it."""
    run = build(tmp)
    (run / "layers.json").write_text(json.dumps({"layers": [
        {"id": "L1", "explainer": "why", "reviewFocus": "- check", "hunks": ["h1"]}]}))
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = read(run, "code-quality")
    assert "### 1. layer — L1" in text and "Explain: why" in text
    assert not (run / "_common.md").exists(), "no shared file is written any more"


def test_elided_lines_carry_their_file_line_numbers(tmp: Path) -> None:
    """Collapsing a run shifts every offset after it, so kept lines must carry their numbers."""
    run = build(tmp)
    tier = read(run, "prompt-quality")
    assert "\n1: # Prompt\n" in tier
    assert "\n6: line five\n" in tier and "\n7: line six\n" in tier
    assert "… (lines 2-5 are in the diff above)" in tier


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
    result = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
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
    done = subprocess.run([sys.executable, str(TOOL), str(run)], capture_output=True, text=True)
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


def main() -> int:
    tests = [value for key, value in globals().items() if key.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except Exception as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {type(error).__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
