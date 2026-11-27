"""Document discovery, the path helpers every lint family shares, and the rule registry.

`files` is the whole in-scope document set (rules, agents, skills and references, the catalog page,
harness settings, hook scripts), so a family never re-derives it. `RULES` lists every rule once with
its family and summary; `--list-rules` prints it and `test_lint_rules.py` fails an unregistered rule.
"""
from __future__ import annotations

from pathlib import Path

PATTERNS = (
    "rules/*.mdc",
    ".cursor/rules/*.mdc",
    ".cursor/agents/**/*.md",
    ".cursor/skills/**/SKILL.md",
    ".cursor/skills/**/references/*.md",
    ".agent/tools/*.md",
    ".claude/CLAUDE.md",
    ".claude/settings.json",
    ".claude/settings.template.json",
    ".cursor/hooks.template.json",
    ".claude/hooks/*.sh",
    ".claude/hooks/guard/*.sh",
)


def files(root: Path) -> list[Path]:
    """Every in-scope document under `root`, deduplicated and sorted."""
    result: set[Path] = set()
    for pattern in PATTERNS:
        result.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(result)


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


RULES: dict[str, tuple[str, str]] = {
    # lint_catalog: the tool manifest and basenames
    "missing-tool-catalog": ("catalog", "tools.json exists"),
    "invalid-tool-catalog": ("catalog", "tools.json parses and every entry has the required fields"),
    "catalog-kind-missing": ("catalog", "every entry declares kind"),
    "catalog-kind-invalid": ("catalog", "kind is command, module or asset and matches its section"),
    "installable-module": ("catalog", "a module never carries a command basename"),
    "cataloged-tool-unavailable": ("catalog", "a command exists and is executable"),
    "cataloged-module-unavailable": ("catalog", "a module exists under its declared dir"),
    "cataloged-asset-unavailable": ("catalog", "an asset exists under its declared dir"),
    "command-name": ("catalog", "a command matches ^crew-[a-z0-9-]+.(py|sh)$"),
    "tool-name": ("catalog", "a module is snake_case; a tree file is a command or a module"),
    "uncataloged-tool": ("catalog", "every .py and .sh under .agent/tools is in tools.json"),
    # lint_prompts: rules, skills, agents and tool grants
    "missing-rule-frontmatter": ("prompts", "a rule file opens with YAML frontmatter"),
    "invalid-rule-frontmatter": ("prompts", "a rule's frontmatter closes, with description and alwaysApply"),
    "inactive-rule-extension": ("prompts", "a rule file uses the .mdc extension"),
    "always-on-rule-unreachable": ("prompts", "an always-on rule is reachable from the imports"),
    "missing-agent-frontmatter": ("prompts", "an agent file opens with YAML frontmatter"),
    "invalid-agent-frontmatter": ("prompts", "an agent's frontmatter closes"),
    "invalid-skill-frontmatter": ("prompts", "a skill's frontmatter parses with name and description"),
    "missing-disable-model-invocation": ("prompts", "a user-only skill disables model invocation"),
    "missing-readonly": ("prompts", "a read-only agent declares readonly: true"),
    "unexpected-readonly": ("prompts", "a write-capable agent does not declare readonly"),
    "agents-inherit-tools": ("prompts", "an agent's tools: line is its class list plus the MCP placeholder, or absent"),
    "persona-turn-budget": ("prompts", "a persona declares tool_budget, states it once, and maxTurns >= budget + 2"),
    "mcp-tool-unknown": ("prompts", "an MCP tool id is in the catalog"),
    "tool-id-unknown": ("prompts", "a native tool id is in the catalog"),
    # lint_references: paths, installed names and routing
    "bad-frontmatter": ("references", "an agent or skill frontmatter has name and description"),
    "missing-reference": ("references", "a linked reference file exists"),
    "missing-rule-file": ("references", "a named rule file exists"),
    "missing-agent": ("references", "a named agent exists"),
    "missing-script": ("references", "an ~/.agent/bin name is in the .agent/tools tree"),
    "stale-path": ("references", "a repository path named in a document exists"),
    "stale-task-path": ("references", "a task path comes from crew-resolve-task-dir.py"),
    "routing-drift": ("references", "routing tables live only in crew-router.mdc"),
    "unrouted-command": ("references", "a crew verb named in a prompt has a routing row"),
    "swallowed-call": ("references", "a command's failure is not hidden by 2>/dev/null or || true"),
    "git-fact-in-prompt": ("references", "a prompt asks a command, not git, for a fact"),
    # lint_references (handoff): the `> Next:` trailer
    "handoff-no-command": ("references", "a trailer names a crew verb"),
    "handoff-multiple-trailers": ("references", "one trailer per file"),
    "handoff-trailer-not-last": ("references", "the trailer is the last non-empty line"),
    "handoff-stray-next": ("references", "no `Next:` outside the trailer"),
    "handoff-unrouted-command": ("references", "the trailer's verb resolves in the router"),
    # lint_writing: transitions, edits, hooks, local state
    "progress-not-a-transition": ("writing", "a PROGRESS write is a declared transition"),
    "shell-file-edit": ("writing", "prompts edit files with the edit tool, not shell"),
    "unregistered-hook": ("writing", "every hook script is registered in both harnesses"),
    "tracked-local-state": ("writing", "local state under .agent is not tracked"),
    # lint_prompts (--budget)
    "budget": ("prompts", "the always-on set fits its token ceiling and an agent or skill file its line cap"),
    "prompt-budget": ("prompts", "each prompt file fits its byte ceiling"),
    "prompt-headroom": ("prompts", "a prompt file stays within 90% of its ceiling, the always-on set within 95%"),
    # lint_python: repository rules for .agent/tools (Ruff, configured in ruff.toml, owns the generic ones)
    "module-size": ("python", "no module over 400 lines, entry points included, in .agent/tools and tui/"),
    "package-direction": ("python", "an import crosses packages only along an edge TOOLS.md declares"),
    "direct-git": ("python", "no git argv outside lib/git.py"),
    "single-owner": ("python", "one definition per shared helper; PROGRESS.md and owner/repo parsing in their owners"),
    "bootstrap-identical": ("python", "the <package>_bootstrap.py copies are byte-identical (sys.path: Ruff TID251)"),
    "no-systemexit-str": ("python", "no raise SystemExit(\"message\") (exit 1); lib.cli.fail exits 2"),
    "no-sibling-subprocess": ("python", "no module runs a sibling crew-*.py as a process to reach its logic"),
    "pipe-read-eof": ("python", "a while loop reading a subprocess pipe leaves on its read variable's end of file"),
    # lint_writing: what prompts, docs and tool sources say
    "removed-command-form": ("writing", "no prompt, doc, hook or tool names a removed command form"),
    "docstring-length": ("writing", "a module docstring under .agent/tools is at most 6 lines"),
    "no-incident-narration": ("writing", "no docstring, comment or prompt narrates history (used to, N of M measured)"),
    # lint_docs: the README's generated blocks and the release files
    "readme-commands-current": ("docs", "the README command table equals `crew-lint.py --commands`; rows described"),
    "readme-counts-current": ("docs", "the README counts of agents, personas, skills and commands match the tree"),
    "release-files": ("docs", "release, security, contributing and template files exist; VERSION = manifest"),
    # lint_style: the repo-specific writing standard for prompt files (Vale, .vale.ini, owns the generic prose rules)
    "duplicate-passages": ("style", "no 12-word passage shared by two prompt files outside the allow-list"),
    "glossary-terms": ("style", "one glossary in .agent/tools/AGENTS.md defining the core terms"),
    "vendor-tools-scoped": ("style", "Elastic-only ids only in Kibana prompts, personal rules or an (opt-in) section"),
    "undefined-placeholder": ("style", "a $PLACEHOLDER in an agent or skill is defined before use"),
    "one-closing-confirmation": ("style", "journal writes and draft imports only in closing confirmation or resolver"),
}


def rule_table() -> list[str]:
    """One `rule  family  summary` line per registered rule, sorted by family then rule."""
    rows = sorted(RULES.items(), key=lambda item: (item[1][0], item[0]))
    width = max(len(name) for name in RULES)
    return [f"{name:<{width}}  {family:<10}  {summary}" for name, (family, summary) in rows]
