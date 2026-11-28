#!/usr/bin/env python3
"""Repository-specific rules for the Python under `src/crew/`; Ruff owns the generic ones.

`module-size`, `package-direction` (the edges in TOOLS.md `package-edges`), `direct-git` (git argv only
in `lib/git.py`), `single-owner`, `no-sibling-subprocess` and `no-systemexit-str` (exit messages through
`lib.cli.fail`), `pipe-read-eof` (`evals/` too).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from crew.lib.markdown import fenced_blocks
from crew.maintenance.lint_files import rel

MAX_MODULE_LINES = 400
SINGLE_OWNER_FUNCTIONS = ("atomic_write", "gh", "read_json_object", "slug_from_url", "utc_stamp", "parse_stamp", "fenced_blocks", "frontmatter", "spec_field")
# A string in code (not a docstring) only its owner may hold: the PROGRESS.md path, a remote-URL regex, and the
# fence, frontmatter, hunk-header and spec-field patterns.
SINGLE_OWNER_TEXT = (
    ("lib/markdown.py", re.compile(r"\^`{3}|\\A-{3}"), "fences and frontmatter are read by lib.markdown"),
    ("review/review_parse.py", re.compile(r"\^@{2} -"), "a hunk header is parsed by review_parse.HUNK_HEADER"),
    ("task/task_status.py", re.compile(r"\^## (\{name\}|[A-Z]\w*):"), "a spec field is read by task_status.spec_field"),
    ("task/task_progress.py", re.compile(r"^(?:.*/)?PROGRESS\.md$"), "PROGRESS.md is read and appended through task_progress"),
    ("lib/git.py", re.compile(r"\[:/\].*\(\?:\\\.git\)\?"), "owner/repo is parsed by lib.git.slug_from_url"),
)
GIT_LIBRARY = Path("lib") / "git.py"
SIBLING_COMMAND = re.compile(r"^(crew-[a-z0-9-]+\.py|crew\.\w+\.crew_\w+)$")
# A process is the point here, not a way to reach logic: the run must outlive its caller, or show as typed.
SIBLING_PROCESS_ALLOWED = {"task/task_verify.py": "detaches `verify --background`", "tui/tui_model.py": "runs the confirmed crew-task.py move the dialog shows"}
Finding = tuple[str, int, str, str]
Parsed = dict[Path, tuple[str, ast.Module]]


def module_files(root: Path) -> list[Path]:
    """Every Python file under `src/crew/`, in every package, so a new package is covered."""
    tools = root / "src/crew"
    if not tools.is_dir():
        return []
    return sorted(path for path in tools.rglob("*.py") if "__pycache__" not in path.parts)


def parse_modules(root: Path) -> Parsed:
    """Source and tree for every module that parses; Ruff reports the ones that do not."""
    parsed: Parsed = {}
    for path in module_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            parsed[path] = (source, ast.parse(source, filename=str(path)))
        except SyntaxError:
            continue
    return parsed


def check_module_size(name: str, source: str) -> list[Finding]:
    """Every module, entry points included, stays at or under the ceiling."""
    lines = source.count("\n") + (0 if source.endswith("\n") or not source else 1)
    if lines <= MAX_MODULE_LINES:
        return []
    return [(name, 1, "module-size", f"{lines} lines (>{MAX_MODULE_LINES}); split it by responsibility")]


def declared_edges(root: Path) -> dict[str, set[str]] | None:
    """`{package: packages it may import}` from the `package-edges` block of TOOLS.md, or None without one."""
    try:
        found = fenced_blocks((root / "src/crew/TOOLS.md").read_text(encoding="utf-8"), "package-edges")
    except OSError:
        return None
    if not found:
        return None
    edges: dict[str, set[str]] = {}
    for line in found[0].splitlines():
        source, _, targets = line.partition("->")
        if source.strip():
            edges[source.strip()] = set(targets.split())
    return edges


def imported(tree: ast.AST) -> list[tuple[int, str]]:
    """`(line, package)` of every `crew.<package>` import, those inside functions included."""
    names = [(node.lineno, alias.name) for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [(node.lineno, node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    return [(line, name.split(".")[1]) for line, name in names if name.startswith("crew.")]


def check_package_direction(root: Path, parsed: Parsed) -> list[Finding]:
    """An import into another package follows an edge `package-edges` in TOOLS.md declares."""
    tools = root / "src/crew"
    edges = declared_edges(root)
    if edges is None:
        return [("src/crew/TOOLS.md", 1, "package-direction", "no ```package-edges block declares the imports")]
    found = []
    for path, (_, tree) in parsed.items():
        source = path.relative_to(tools).parts[0]
        for line, target in imported(tree):
            if target != source and target not in edges.get(source, set()):
                found.append(
                    (rel(root, path), line, "package-direction", f"{source} imports crew.{target}; TOOLS.md package-edges does not allow {source} -> {target}")
                )
    return found


def is_git_argv(node: ast.AST) -> bool:
    """True for a list or tuple literal whose first element is the string `git`."""
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return False
    first = node.elts[0]
    return isinstance(first, ast.Constant) and first.value == "git"


def check_direct_git(name: str, relative: Path, tree: ast.AST) -> list[Finding]:
    """No module outside `lib/git.py` writes a git argv; one runner owns the error shape."""
    if relative == GIT_LIBRARY:
        return []
    return [(name, node.lineno, "direct-git", "build the argv in lib/git.py instead") for node in ast.walk(tree) if is_git_argv(node)]


def docstring_ids(tree: ast.AST) -> set[int]:
    """The ids of every docstring constant, so prose can name a file its code may not touch."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def check_owned_text(name: str, relative: Path, tree: ast.AST) -> list[Finding]:
    """A string in code that names an owned resource, outside its owner."""
    prose = docstring_ids(tree)
    strings = [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose]
    return [
        (name, node.lineno, "single-owner", what)
        for owner, marker, what in SINGLE_OWNER_TEXT
        if relative.as_posix() != owner
        for node in strings
        if marker.search(node.value)
    ]


def check_single_owner(root: Path, parsed: Parsed) -> list[Finding]:
    """Each shared helper is defined exactly once in the whole tree."""
    found = []
    for wanted in SINGLE_OWNER_FUNCTIONS:
        defining = [
            (path, node.lineno)
            for path, (_, tree) in parsed.items()
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == wanted
        ]
        if len(defining) != 1:
            where = ", ".join(f"{rel(root, path)}:{line}" for path, line in defining) or "nowhere"
            found.append(("src/crew", 0, "single-owner", f"def {wanted} is defined {len(defining)} times ({where}); expected once"))
    return found


def imports_subprocess(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Import)
        and any(alias.name == "subprocess" for alias in node.names)
        or isinstance(node, ast.ImportFrom)
        and node.module == "subprocess"
        for node in ast.walk(tree)
    )


def sibling_command_literals(tree: ast.AST) -> list[ast.Constant]:
    """`crew-*.py` literals used as a path or an argv element, not as prose or a `prog=` keyword."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            candidates = [node.right]
        elif isinstance(node, ast.Call):
            candidates = list(node.args)
        elif isinstance(node, (ast.List, ast.Tuple)):
            candidates = list(node.elts)
        else:
            continue
        found.extend(item for item in candidates if isinstance(item, ast.Constant) and isinstance(item.value, str) and SIBLING_COMMAND.match(item.value))
    return found


def check_sibling_subprocess(name: str, relative: Path, tree: ast.AST) -> list[Finding]:
    """A module that runs subprocesses does not run a sibling command; it imports the logic."""
    if relative.as_posix() in SIBLING_PROCESS_ALLOWED or not imports_subprocess(tree):
        return []
    return [
        (name, node.lineno, "no-sibling-subprocess", f"{node.value} is run as a process; import the module that holds its logic")
        for node in sibling_command_literals(tree)
    ]


def called_name(node: ast.Call) -> str:
    """`SystemExit` for `builtins.SystemExit(...)` or `SystemExit(...)`, else ""."""
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    return function.id if isinstance(function, ast.Name) else ""


def check_cli(name: str, tree: ast.AST) -> list[Finding]:
    """An exit message goes through `lib.cli.fail` (exit 2), never `raise SystemExit("message")` (exit 1)."""
    found: list[Finding] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and called_name(node.exc) == "SystemExit"
            and node.exc.args
            and isinstance(node.exc.args[0], (ast.JoinedStr, ast.Constant))
            and isinstance(getattr(node.exc.args[0], "value", ""), str)
        ):
            found.append((name, node.lineno, "no-systemexit-str", "exits 1; use lib.cli.fail(message), which exits 2"))
    return found


def reads_a_pipe(node: ast.AST) -> bool:
    """`os.read(<...stdout...>)`, or `.read()`/`.readline()` on something named stdout or stderr."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    func, streams = node.func, ("stdout", "stderr")
    if func.attr == "read" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return bool(node.args) and any(stream in ast.unparse(node.args[0]) for stream in streams)
    return func.attr in ("read", "readline") and any(stream in ast.unparse(func.value) for stream in streams)


def stops_at_eof(test: ast.expr, chunks: set[str]) -> bool:
    """`not <chunk>`, or `<chunk> == b""` / `""`, for a name a pipe read was assigned to."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return isinstance(test.operand, ast.Name) and test.operand.id in chunks
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id in chunks
        and isinstance(test.ops[0], (ast.Eq, ast.Is))
        and any(isinstance(side, ast.Constant) and side.value in (b"", "") for side in test.comparators)
    )


def check_pipe_reads(name: str, tree: ast.AST) -> list[Finding]:
    """A `while` loop that reads a subprocess's stdout or stderr leaves at end of file: an `if` on the variable the
    read was assigned to breaks or returns. A read of a closed pipe returns empty forever, so the loop would spin."""
    found: list[Finding] = []
    for loop in (node for node in ast.walk(tree) if isinstance(node, ast.While)):
        if not any(reads_a_pipe(node) for node in ast.walk(loop)):
            continue
        chunks = {
            target.id
            for node in ast.walk(loop)
            if isinstance(node, ast.Assign) and any(reads_a_pipe(inner) for inner in ast.walk(node.value))
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        exits = (
            isinstance(node, ast.If) and stops_at_eof(node.test, chunks) and any(isinstance(item, (ast.Break, ast.Return)) for item in node.body)
            for node in ast.walk(loop)
        )
        if not any(exits):
            found.append((name, loop.lineno, "pipe-read-eof", "assign the pipe read to a name and leave the loop on `if not <name>: break`"))
    return found


def pipe_read_files(root: Path) -> list[Path]:
    """The Python of the tools and the tests: the tests are where subprocess output is read in a loop."""
    bases = [root / base for base in ("src/crew", "evals") if (root / base).is_dir()]
    return sorted(path for base in bases for path in base.rglob("*.py") if "__pycache__" not in path.parts and ".venv" not in path.parts)


def lint_python(root: Path) -> list[Finding]:
    """The repository rules over every module; a tree with no Python has nothing to judge."""
    found: list[Finding] = []
    for path in pipe_read_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        found.extend(check_pipe_reads(rel(root, path), tree))
    parsed = parse_modules(root)
    if not parsed:
        return found
    for path, (source, tree) in parsed.items():
        name, relative = rel(root, path), path.relative_to(root / "src/crew")
        found.extend(check_module_size(name, source))
        found.extend(check_direct_git(name, relative, tree))
        found.extend(check_sibling_subprocess(name, relative, tree))
        found.extend(check_owned_text(name, relative, tree))
        found.extend(check_cli(name, tree))
    found.extend(check_single_owner(root, parsed))
    found.extend(check_package_direction(root, parsed))
    return found
