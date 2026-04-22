#!/usr/bin/env python3
"""task-bundle.py — write bundle-manifest.txt for a task (path-only; no secret contents).

Requires env TASK_DIR to an existing directory. Optional tar when CREW_TASK_BUNDLE_TAR=1.
"""
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    task_dir = os.environ.get("TASK_DIR", "").strip()
    if not task_dir:
        print("usage: set TASK_DIR to the task directory", file=sys.stderr)
        sys.exit(2)
    root = Path(task_dir)
    if not root.is_dir():
        print(f"task-bundle: not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    manifest = root / "bundle-manifest.txt"
    lines = [
        "# bundle-manifest — paths only; do not add .env, *.pem, id_rsa, or credential files",
    ]
    if (root / "SPEC.md").is_file():
        lines.append(f"SPEC={root / 'SPEC.md'}")
    if (root / "REPORT.md").is_file():
        lines.append(f"REPORT={root / 'REPORT.md'}")
    if (root / "REPORT.digest.md").is_file():
        lines.append(f"DIGEST={root / 'REPORT.digest.md'}")
    if (root / "PROGRESS.md").is_file():
        lines.append(f"PROGRESS={root / 'PROGRESS.md'}")
    art = root / "artifacts"
    if art.is_dir():
        for f in sorted(art.rglob("*")):
            if f.is_file():
                lines.append(f"ARTIFACT={f}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {manifest}")

    if os.environ.get("CREW_TASK_BUNDLE_TAR") == "1":
        # The tar is a summary archive — it packs SPEC, PROGRESS, REPORT, and the manifest.
        # Artifact files under artifacts/ are listed in bundle-manifest.txt but NOT included
        # in the tar; they can be large and are accessible via the paths in the manifest.
        tar_out = root / "task-bundle.tar"
        files = ["bundle-manifest.txt"]
        for name in ("SPEC.md", "PROGRESS.md", "REPORT.md", "REPORT.digest.md"):
            if (root / name).is_file():
                files.append(name)
        cmd = [
            "tar",
            "-cf",
            str(tar_out),
            "--exclude=.env",
            "--exclude=*.pem",
            "--exclude=id_rsa",
            "-C",
            str(root),
            *files,
        ]
        subprocess.run(cmd, check=True)
        print(f"Wrote optional archive {tar_out} (manifest-only: artifacts listed but not packed)")


if __name__ == "__main__":
    main()
