"""Run a `crew-*.py` entry point in this process, the way its shell invocation would, without a new interpreter.

`run(path, *args, env=..., cwd=...)` loads the script by path (its directory first on `sys.path`, as
Python does for a script), sets `sys.argv`, the environment overrides (`None` unsets) and the cwd for the
call, captures stdout and stderr, and turns `SystemExit` into the exit code (an uncaught error into a
traceback on stderr and exit 1, as the interpreter would). The streams are UTF-8 text over bytes, so a
command that reads `sys.stdin.buffer` or writes `sys.stdout.buffer` works as it does from a shell. The
script is executed afresh for each HOME it runs under; the modules it imports are shared, so they must
read HOME and the environment at call time, never at import. It returns a `subprocess.CompletedProcess`,
so a test can switch between this and `subprocess.run` freely. Not thread-safe.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import traceback
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

_LOADED: dict[tuple[Path, str | None], ModuleType] = {}


def load(path: Path) -> ModuleType:
    """The entry script, executed under the current environment once per (path, HOME)."""
    path = Path(path).resolve()
    key = (path, os.environ.get("HOME"))
    if key not in _LOADED:
        if str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED[key] = module
    return _LOADED[key]


@contextlib.contextmanager
def environment(env: dict[str, str | None] | None, cwd: str | Path | None) -> Iterator[None]:
    saved_env, saved_cwd = dict(os.environ), os.getcwd()
    try:
        for key, value in (env or {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if cwd is not None:
            os.chdir(cwd)
        yield
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)


def stream(raw: io.BytesIO) -> io.TextIOWrapper:
    """A text stream with a `.buffer`, as `sys.stdin`/`sys.stdout` have; writes reach the bytes in order."""
    return io.TextIOWrapper(raw, encoding="utf-8", write_through=True)


def run(path: Path, *args: str, env: dict[str, str | None] | None = None, cwd: str | Path | None = None,
        stdin: str = "") -> subprocess.CompletedProcess:
    raw_out, raw_err = io.BytesIO(), io.BytesIO()
    out, err = stream(raw_out), stream(raw_err)
    saved_argv, saved_stdin = sys.argv, sys.stdin
    code: object = 0
    try:
        with environment(env, cwd), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            sys.argv, sys.stdin = [Path(path).name, *args], stream(io.BytesIO(stdin.encode("utf-8")))
            try:
                code = load(path).main()
            except SystemExit as stop:
                code = stop.code
            except Exception:  # an uncaught error is a traceback and exit 1, as from python3
                traceback.print_exc()
                code = 1
    finally:
        sys.argv, sys.stdin = saved_argv, saved_stdin
    if isinstance(code, str):
        err.write(code + "\n")
        code = 1
    exit_code = 0 if code is None else int(code)
    text = [raw.getvalue().decode("utf-8", errors="replace") for raw in (raw_out, raw_err)]
    return subprocess.CompletedProcess([str(path), *args], exit_code, *text)
