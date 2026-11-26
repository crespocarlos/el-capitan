"""What the verify mirror shares: the Node pin, the pass cache, the result file and the partial verdict.

The Node pin is found, never assumed (`.nvmrc`, `.node-version`, `.tool-versions`, `package.json`
`engines.node`). A result is cached by its identity (the tree plus the mirrored command, env and
Node) only when it passed: a failure is re-run, never replayed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from lib.cli import EXIT_INVALID
from lib.clock import utc_iso
from lib.files import atomic_write
from lib.git import GitError, output

EXIT_NOT_VERIFIED = 3  # every gate passed, but the run was partial or only prose checks exist


def run_argv(argv: list[str], cwd: Path, env: dict, timeout: int, log: Path) -> tuple[int, float]:
    """`(exit, seconds)` of one process with its output in `log`; 124 on timeout, 127 when it cannot start."""
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        try:
            done = subprocess.run(argv, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
            code = done.returncode
        except subprocess.TimeoutExpired:
            code = 124
        except OSError as error:
            handle.write(f"cannot run: {error}\n")
            code = 127
    return code, round(time.monotonic() - started, 2)


def write_result(out: Path | None, payload: dict) -> None:
    if out is not None:
        atomic_write(out, json.dumps(payload, indent=2) + "\n")


def log_of(out: Path) -> Path:
    return out.with_suffix(".log")


def write_failed(out: Path | None, reason: str) -> None:
    """Mark a run that ended without a `done` result; the log beside `out` has the detail."""
    if out is None:
        return
    payload = {"schema_version": 1, "state": "failed", "verified": False, "started": utc_iso(), "pid": os.getpid(),
               "reason": reason, "log": str(log_of(out)), "gates": []}
    atomic_write(out, json.dumps(payload, indent=2) + "\n")


def gate_line(gate: dict) -> str:
    return f"{gate['name']} exit={gate['exit']}" + (" cached" if gate.get("cached") else "")


def not_ci(skipped: list[str]) -> list[str]:
    """The workflows left out because they are not CI; they never make the run partial."""
    return [s for s in skipped if ": not CI (on: " in s]


def kinds(skipped: list[str]) -> tuple[list[str], list[str], list[str]]:
    """`(setup, other, uses)` entries of the skipped list; the not-CI workflows are in none of them."""
    uses = [s for s in skipped if s.startswith("uses: ")]
    setup = [s for s in skipped if s.endswith(": setup step")]
    expected = set(uses) | set(setup) | set(not_ci(skipped))
    return setup, [s for s in skipped if s not in expected], uses


def is_partial(skipped: list[str]) -> bool:
    return bool(kinds(skipped)[1])


def partial_line(skipped: list[str]) -> str:
    """The verdict line of a partial run: its gates may all pass, and it is still not a pass."""
    count = len(kinds(skipped)[1])
    return f"verify: NOT VERIFIED: partial mirror ({count} steps skipped); a pass here does not prove CI passes"


def partial_exit(skipped: list[str], gates_ok: bool, strict: bool) -> int:
    """The process exit: 1 for a failed gate, else 3 (2 with --strict) when the run is partial, else 0."""
    if not gates_ok:
        return 1
    return (EXIT_INVALID if strict else EXIT_NOT_VERIFIED) if is_partial(skipped) else 0

NODE_HOMES = (".nvm/versions/node", ".local/share/fnm/node-versions", "Library/Application Support/fnm/node-versions",
              ".volta/tools/image/node", ".asdf/installs/nodejs")


def required_node(nvmrc: str) -> str:
    """The version `.nvmrc` names without a leading `v`; an alias such as `lts/*` comes back as is."""
    for line in nvmrc.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            return line.strip().removeprefix("v")
    return ""


def version_tuple(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", name))


def find_node_bin(required: str, home: Path | None = None) -> Path | None:
    """The `bin` directory of the newest installed Node matching `required`, or None."""
    if not re.match(r"^\d+(\.\d+){0,2}$", required):
        return None
    base = home or Path(os.environ.get("HOME", "~")).expanduser()
    found: list[tuple[tuple[int, ...], Path]] = []
    for relative in NODE_HOMES:
        root = base / relative
        for entry in root.glob("*") if root.is_dir() else []:
            version = entry.name.removeprefix("v")
            if version == required or version.startswith(required + "."):
                for bin_dir in (entry / "bin", entry / "installation" / "bin"):
                    if (bin_dir / "node").exists():
                        found.append((version_tuple(version), bin_dir))
    return max(found, key=lambda pair: pair[0])[1] if found else None


def node_version(path: str) -> str:
    """`node --version` under the given PATH, or `unavailable`."""
    try:
        done = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=20,
                              env={**os.environ, "PATH": path})
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unavailable"


def node_env(pin: dict) -> tuple[dict, str]:
    """`({required, used, source}, PATH)`: the pinned Node when installed, else the PATH's own.

    With no pin (`source` is `none`) the PATH is left alone: a repo that names no Node is never forced onto one.
    """
    required = pin["required"]
    found = find_node_bin(required) if required else None
    path = f"{found}{os.pathsep}{os.environ.get('PATH', '')}" if found else os.environ.get("PATH", "")
    return {"required": required, "used": node_version(path), "source": pin["source"]}, path


def tree_key(root: Path) -> str:
    """The tree the gates would run on: HEAD's tree, hashed with the diff and untracked files if dirty."""
    tree = output(root, ["rev-parse", "HEAD^{tree}"]).strip()
    extra = hashlib.sha256(output(root, ["diff", "HEAD", "--binary"]).encode("utf-8", "replace"))
    dirty = bool(extra.digest() != hashlib.sha256(b"").digest())
    for path in sorted(output(root, ["ls-files", "--others", "--exclude-standard"]).splitlines()):
        target = root / path
        extra.update(path.encode() + (target.read_bytes() if target.is_file() else b""))
        dirty = True
    return hashlib.sha256(f"{tree}{extra.hexdigest()}".encode()).hexdigest() if dirty else tree


def cache_key(tree: str, command: str, env: dict[str, str], node: str) -> str:
    """The identity of one gate result: tree hash, command, env and Node version."""
    material = json.dumps([tree, command, sorted(env.items()), node])
    return hashlib.sha256(material.encode()).hexdigest()


def cache_dir(root: Path) -> Path:
    """Shared by every worktree of the repository, under git's common directory."""
    try:
        common = output(root, ["rev-parse", "--git-common-dir"]).strip()
    except GitError:
        return root / ".crew-verify-cache"
    return (root / common).resolve() / "crew-verify"


def cache_get(root: Path, key: str) -> dict | None:
    try:
        return json.loads((cache_dir(root) / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(root: Path, key: str, result: dict) -> None:
    directory = cache_dir(root)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass


NONE = ("none", "")
VERSION = re.compile(r"\d+(?:\.\d+){0,2}")


def tool_versions_pin(text: str) -> str:
    """The version on the `nodejs` (or `node`) line of an asdf `.tool-versions`, or ''."""
    for line in text.splitlines():
        parts = line.split("#")[0].split()
        if len(parts) >= 2 and parts[0] in ("nodejs", "node"):
            return parts[1].removeprefix("v")
    return ""


def engines_pin(text: str) -> str:
    """The first version in `engines.node` (`>=22.18`, `^20.3.0 || ^22`), or ''."""
    try:
        spec = json.loads(text)["engines"]["node"]
    except (ValueError, KeyError, TypeError):
        return ""
    found = VERSION.search(spec) if isinstance(spec, str) else None
    return found.group(0) if found else ""


def node_pin(read: Callable[[str], str | None]) -> tuple[str, str]:
    """`(source, required)` for the first pin `read(path)` can show, else `("none", "")`."""
    for path, parse in ((".nvmrc", required_node), (".node-version", required_node),
                        (".tool-versions", tool_versions_pin), ("package.json", engines_pin)):
        required = parse(read(path) or "")
        if required:
            return ("package.json engines.node" if path == "package.json" else path), required
    return NONE
