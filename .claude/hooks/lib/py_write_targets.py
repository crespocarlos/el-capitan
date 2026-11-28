"""The path literals a Python snippet writes to, for the shell guard's source-edit rule; the snippet is parsed, never run.

Reads the snippet on stdin and prints one target per line, exit 0. A target is the literal path of `open(<p>, <mode
with w, a, x or +>)` (also `io.open`, `codecs.open` and `Path(<p>).open`), `Path(<p>).write_text`/`write_bytes`, the
destination of `shutil.copy*`/`shutil.move` and of `os.replace`/`os.rename`. `<p>` is a string literal, a
`Path(<literal>)`, or a name bound once, by plain assignment, to one of those. A write this cannot resolve (a path or
mode that is no literal: a loop variable, an f-string, a name bound twice; `os.open`/`os.write`, `fileinput` with
`inplace`, `subprocess`, `exec`, `eval`, `getattr`, `__import__`, or a write function imported or aliased by another
name) prints every string literal outside a dict display instead, since a dict is data such as review JSON. Exit 3, and
the guard counts every quoted literal, when the snippet does not parse.
Run as `python3 -I`, so nothing from the working directory is imported.
"""

from __future__ import annotations

import ast
import sys

WRITE_MODE = set("wax+")
PATH_NAMES = {"Path", "PosixPath", "PurePath"}
OPAQUE_CALLS = {"exec", "eval", "getattr", "__import__", "os.open", "os.write", "os.system", "os.popen", "os.fdopen"}
OPAQUE_NAMES = {"subprocess", "exec", "eval", "getattr", "__import__"}
# A write function imported bare from these modules is called under a name this parser does not follow.
OPAQUE_MODULES = {"subprocess", "fileinput", "shutil", "os", "io", "codecs"}
WRITE_NAMES = {"open", "copy", "copy2", "copyfile", "copytree", "move", "replace", "rename", "write", "system", "popen", "input", "FileInput", "*"}


class Unresolved(Exception):
    """A write whose target this parser cannot name."""


def names(tree: ast.AST) -> dict[str, str]:
    """Names bound once, by plain assignment, to a path literal; any other binding of a name (a loop, a `with`, a
    second assignment, an augmented one) leaves it out."""
    seen: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            bound, value = list(node.targets), node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor, ast.NamedExpr)):
            bound, value = [node.target], None
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            bound, value = [item.optional_vars for item in node.items if item.optional_vars is not None], None
        else:
            continue
        for target in bound:
            for name in ast.walk(target):
                if isinstance(name, ast.Name):
                    found = literal(value, {}) if value is not None and target is name else None
                    seen[name.id] = found if name.id not in seen else None
    return {name: value for name, value in seen.items() if value is not None}


def called(node: ast.Call) -> str:
    """`open`, `Path`, `shutil.copy`, ...: the dotted name of what is called, or ""."""
    func, parts = node.func, []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def literal(node: ast.AST | None, known: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.Call) and called(node).rsplit(".", 1)[-1] in PATH_NAMES and node.args:
        return literal(node.args[0], known)
    return None


def argument(node: ast.Call, index: int, keyword: str) -> ast.AST | None:
    if len(node.args) > index:
        return node.args[index]
    return next((item.value for item in node.keywords if item.arg == keyword), None)


def resolved(node: ast.AST | None, known: dict[str, str]) -> str:
    found = literal(node, known)
    if found is None:
        raise Unresolved
    return found


def writes(node: ast.Call, index: int, known: dict[str, str]) -> bool:
    """Whether an open call writes: no mode reads, and a mode that is no literal cannot be judged."""
    mode = argument(node, index, "mode")
    return mode is not None and bool(WRITE_MODE & set(resolved(mode, known)))


def imports_a_write(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0] == "subprocess" for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = (node.module or "").split(".")[0]
        bare = any(alias.name in WRITE_NAMES for alias in node.names)
        return module == "subprocess" or (module in OPAQUE_MODULES and bare)
    return False


def opaque(tree: ast.AST) -> bool:
    """A construct that can write without a call this parser reads."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
            called(node) in OPAQUE_CALLS or (called(node).startswith("fileinput.") and any(item.arg == "inplace" for item in node.keywords))
        ):
            return True
        if isinstance(node, ast.Name) and node.id in OPAQUE_NAMES or imports_a_write(node):
            return True
        if isinstance(node, (ast.Assign, ast.keyword)) and isinstance(node.value, ast.Name) and node.value.id == "open":
            return True
    return False


def targets(source: str) -> list[str]:
    tree = ast.parse(source)
    if opaque(tree):
        raise Unresolved
    known, found = names(tree), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = called(node)
        method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if name in ("open", "io.open", "codecs.open") and writes(node, 1, known):
            found.append(resolved(argument(node, 0, "file"), known))
        elif method == "open" and isinstance(receiver, ast.Call) and writes(node, 0, known) or method in ("write_text", "write_bytes") and receiver is not None:
            found.append(resolved(receiver, known))
        elif name.startswith("shutil.copy") or name in ("shutil.move", "os.replace", "os.rename"):
            found.append(resolved(argument(node, 1, "dst"), known))
    return found


def literals(tree: ast.AST) -> list[str]:
    """Every string literal but data: a dict display's, and the path of a read (`open(<p>)` with no write mode, `<p>.read_text()`)."""
    data = [part for item in ast.walk(tree) if isinstance(item, ast.Dict) for part in item.keys + item.values]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and called(node) in ("open", "io.open", "codecs.open"):
            mode = argument(node, 1, "mode")
            if not WRITE_MODE & set((literal(mode, {}) or "w") if mode else "r"):
                data.append(argument(node, 0, "file"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("read_text", "read_bytes"):
            data.append(node.func.value)
    skip = {id(node) for part in data if part for node in ast.walk(part)}
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip]


def main() -> int:
    source = sys.stdin.read()
    try:
        found = targets(source)
    except Unresolved:
        found = literals(ast.parse(source))
    except (SyntaxError, ValueError, RecursionError):
        return 3
    print("\n".join(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
