"""Run a `crew-*.py` entry point in this process, the way its shell invocation would, without a new interpreter.

`run(path, *args, env=..., cwd=...)` imports the entry module at `path` (under `src/`), sets `sys.argv`, the
environment overrides (`None` unsets) and the cwd for the call, captures stdout and stderr, and turns
`SystemExit` into the exit code (an uncaught error into a traceback on stderr and exit 1). The streams are
UTF-8 text over bytes, as from a shell. The entry module is reloaded for each HOME it runs under; the modules
it imports are shared, so they read HOME at call time, never at import. It returns a
`subprocess.CompletedProcess`, so a test can switch between this and `subprocess.run` freely. Not thread-safe.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import subprocess
import sys
import traceback
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

SRC = Path(__file__).resolve().parents[2] / "src"
_HOMES: dict[str, str | None] = {}


def load(path: Path) -> ModuleType:
    """The entry module at `path` (a catalog name: `-` reads `_`), reloaded when HOME changed since its last load."""
    name = ".".join(Path(path).resolve().relative_to(SRC).with_suffix("").parts).replace("-", "_")
    module = importlib.import_module(name)
    if _HOMES.setdefault(name, os.environ.get("HOME")) != os.environ.get("HOME"):
        _HOMES[name] = os.environ.get("HOME")
        module = importlib.reload(module)
    return module


def launcher(name: str) -> Path:
    """The dev environment's launcher of an installed command (`crew-task.py`): what ~/.agent/bin links to."""
    return Path(sys.executable).with_name(name)


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
