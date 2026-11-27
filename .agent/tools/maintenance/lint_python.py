#!/usr/bin/env python3
"""Repository-specific rules for the Python under `.agent/tools/`; Ruff owns the generic ones.

`module-size`, `package-direction` (the edges in TOOLS.md `package-edges`), `direct-git` (git argv only
in `lib/git.py`), `single-owner`, `bootstrap-identical`, `no-sibling-subprocess` and `no-systemexit-str`
(exit messages through `lib.cli.fail`); `sys.path` is Ruff's (TID251). Names and summaries: `lint_files.RULES`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from lint_files import rel

MAX_MODULE_LINES = 400
EDGES_BLOCK = re.compile(r"^```package-edges[ \t]*\n(.*?)^```", re.M | re.S)
SINGLE_OWNER_FUNCTIONS = ("atomic_write", "gh", "read_json_object", "slug_from_url", "utc_stamp",
                          "parse_stamp")
# A string in code (not a docstring) only its owner may hold: the PROGRESS.md path, a remote-URL regex.
SINGLE_OWNER_TEXT = (
    ("task/task_progress.py", re.compile(r"^(?:.*/)?PROGRESS\.md$"),
     "PROGRESS.md is read and appended through task_progress"),
    ("lib/git.py", re.compile(r"\[:/\].*\(\?:\\\.git\)\?"), "owner/repo is parsed by lib.git.slug_from_url"),
)
GIT_LIBRARY = Path("lib") / "git.py"
SIBLING_COMMAND = re.compile(r"^crew-[a-z0-9-]+\.py$")
# A process is the point here, not a way to reach logic: the run must outlive its caller.
SIBLING_PROCESS_ALLOWED = {"task/task_verify.py": "detaches `verify --background`"}
Finding = tuple[str, int, str, str]
Parsed = dict[Path, tuple[str, ast.Module]]


def module_files(root: Path) -> list[Path]:
    """Every Python file under `.agent/tools/`, in every package, so a new package is covered."""
    tools = root / ".agent/tools"
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
        found = EDGES_BLOCK.search((root / ".agent/tools/TOOLS.md").read_text(encoding="utf-8"))
    except OSError:
        return None
    if not found:
        return None
    edges: dict[str, set[str]] = {}
    for line in found.group(1).splitlines():
        source, _, targets = line.partition("->")
        if source.strip():
            edges[source.strip()] = set(targets.split())
    return edges


def owners(tools: Path, parsed: Parsed) -> dict[str, str]:
    """The package of every importable name: a module's basename, or a sub-package directory's name."""
    found = {}
    for path in parsed:
        parts = path.relative_to(tools).parts
        found.setdefault(path.stem, parts[0])
        for directory in parts[1:-1]:
            found.setdefault(directory, parts[0])
    return found


def imported(tree: ast.AST) -> list[tuple[int, str]]:
    """`(line, first name)` of every absolute import, those inside functions included."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def check_package_direction(root: Path, parsed: Parsed) -> list[Finding]:
    """An import into another package follows an edge `package-edges` in TOOLS.md declares."""
    tools = root / ".agent/tools"
    edges = declared_edges(root)
    if edges is None:
        return [(".agent/tools/TOOLS.md", 1, "package-direction", "no ```package-edges block declares the imports")]
    where = owners(tools, parsed)
    found = []
    for path, (_, tree) in parsed.items():
        source = path.relative_to(tools).parts[0]
        for line, name in imported(tree):
            target = "lib" if name == "lib" else where.get(name)
            if target and target != source and target not in edges.get(source, set()):
                found.append((rel(root, path), line, "package-direction", f"{source} imports {name} ({target}); "
                              f"TOOLS.md package-edges does not allow {source} -> {target}"))
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
    return [(name, node.lineno, "direct-git", "build the argv in lib/git.py instead")
            for node in ast.walk(tree) if is_git_argv(node)]


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
    strings = [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and id(node) not in prose]
    return [(name, node.lineno, "single-owner", what) for owner, marker, what in SINGLE_OWNER_TEXT
            if relative.as_posix() != owner for node in strings if marker.search(node.value)]


def check_single_owner(root: Path, parsed: Parsed) -> list[Finding]:
    """Each shared helper is defined exactly once in the whole tree."""
    found = []
    for wanted in SINGLE_OWNER_FUNCTIONS:
        defining = [(path, node.lineno) for path, (_, tree) in parsed.items() for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == wanted]
        if len(defining) != 1:
            where = ", ".join(f"{rel(root, path)}:{line}" for path, line in defining) or "nowhere"
            found.append((".agent/tools", 0, "single-owner",
                          f"def {wanted} is defined {len(defining)} times ({where}); expected once"))
    return found


def is_bootstrap(relative: Path) -> bool:
    """True for a package's `<package>_bootstrap.py`, the one place the import path is set (Ruff TID251)."""
    return relative.name == f"{relative.parts[0]}_bootstrap.py" and len(relative.parts) == 2


def check_bootstraps_identical(root: Path, parsed: Parsed) -> list[Finding]:
    """Every package bootstrap is byte-identical, so the one reviewed copy is the one that runs."""
    tools = root / ".agent/tools"
    copies = {path: source for path, (source, _) in parsed.items() if is_bootstrap(path.relative_to(tools))}
    if len(set(copies.values())) <= 1:
        return []
    first = min(copies)
    return [(rel(root, path), 1, "bootstrap-identical", f"differs from {rel(root, first)}; the copies are identical")
            for path, source in sorted(copies.items()) if source != copies[first]]


def imports_subprocess(tree: ast.AST) -> bool:
    return any(isinstance(node, ast.Import) and any(alias.name == "subprocess" for alias in node.names)
               or isinstance(node, ast.ImportFrom) and node.module == "subprocess" for node in ast.walk(tree))


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
        found.extend(item for item in candidates if isinstance(item, ast.Constant)
                     and isinstance(item.value, str) and SIBLING_COMMAND.match(item.value))
    return found


def check_sibling_subprocess(name: str, relative: Path, tree: ast.AST) -> list[Finding]:
    """A module that runs subprocesses does not run a sibling command; it imports the logic."""
    if relative.as_posix() in SIBLING_PROCESS_ALLOWED or not imports_subprocess(tree):
        return []
    return [(name, node.lineno, "no-sibling-subprocess",
             f"{node.value} is run as a process; import the module that holds its logic")
            for node in sibling_command_literals(tree)]


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
        if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and called_name(node.exc) == "SystemExit"
                and node.exc.args and isinstance(node.exc.args[0], (ast.JoinedStr, ast.Constant))
                and isinstance(getattr(node.exc.args[0], "value", ""), str)):
            found.append((name, node.lineno, "no-systemexit-str", "exits 1; use lib.cli.fail(message), which exits 2"))
    return found


def lint_python(root: Path) -> list[Finding]:
    """The repository rules over every module; a tree with no Python has nothing to judge."""
    parsed = parse_modules(root)
    if not parsed:
        return []
    found: list[Finding] = []
    for path, (source, tree) in parsed.items():
        name, relative = rel(root, path), path.relative_to(root / ".agent/tools")
        found.extend(check_module_size(name, source))
        found.extend(check_direct_git(name, relative, tree))
        found.extend(check_sibling_subprocess(name, relative, tree))
        found.extend(check_owned_text(name, relative, tree))
        found.extend(check_cli(name, tree))
    found.extend(check_single_owner(root, parsed))
    found.extend(check_package_direction(root, parsed))
    found.extend(check_bootstraps_identical(root, parsed))
    return found
