"""What `crew-task.py ship` refuses to commit: files named like a secret, blobs over 1 MB, credential-like lines.

The credential pattern is `.claude/hooks/lib/token-patterns.ere` (the shell guard scans with gitleaks); an unreadable
pattern raises rather than passing the scan.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from crew.lib.files import checkout
from crew.lib.git import output

MAX_BYTES = 1024 * 1024
SECRET_NAMES = (
    ".env*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*credentials*",
    "*secret*",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".npmrc",
    ".netrc",
    "service-account*.json",
)
SECRET_EXEMPT = (".env.example", ".env.sample")
SECRET_PATTERN = checkout() / ".claude" / "hooks" / "lib" / "token-patterns.ere"
ZERO = "0" * 40


def secret_name(path: str) -> bool:
    base = Path(path).name.lower()
    return base not in SECRET_EXEMPT and any(fnmatch.fnmatch(base, pattern) for pattern in SECRET_NAMES)


def untracked(tree: Path) -> list[str]:
    """Untracked files git does not ignore, relative to the worktree."""
    return [path for path in output(tree, ["ls-files", "--others", "--exclude-standard", "-z"]).split("\0") if path]


def untracked_refusals(tree: Path, paths: list[str]) -> list[str]:
    """The untracked files ship refuses to stage: named like a secret, or over 1 MB."""
    found = [f"{path} (looks like a secret)" for path in paths if secret_name(path)]
    return found + [
        f"{path} (larger than 1 MB)" for path in paths if not secret_name(path) and (tree / path).is_file() and (tree / path).stat().st_size > MAX_BYTES
    ]


def blob_size(tree: Path, sha: str) -> int:
    return 0 if sha == ZERO else int(output(tree, ["cat-file", "-s", sha]).strip())


def index_refusals(tree: Path) -> list[str]:
    """Staged files ship refuses: an added one named like a secret, or a blob that is or grew over 1 MB."""
    fields = output(tree, ["diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames", "--diff-filter=AM"]).split("\0")
    found = []
    for header, path in zip(fields[0::2], fields[1::2]):
        _, _, old, new, status = header.split()
        if status == "A" and secret_name(path):
            found.append(f"{path} (looks like a secret)")
        elif blob_size(tree, new) > MAX_BYTES and blob_size(tree, old) <= MAX_BYTES:
            found.append(f"{path} (larger than 1 MB)")
    return found


def leaks(tree: Path) -> list[str]:
    """The staged files whose added lines match the credential pattern."""
    pattern = re.compile(SECRET_PATTERN.read_text(encoding="utf-8").splitlines()[0])
    current, found = "", []
    for line in output(tree, ["diff", "--cached", "-U0", "--no-color"]).splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and pattern.search(line[1:]) and current not in found:
            found.append(current)
    return found
