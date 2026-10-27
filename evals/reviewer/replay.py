#!/usr/bin/env python3
"""Replay stored reviewer input packages against baseline and current prompts."""
import argparse, hashlib, json, os, shlex, subprocess, sys, tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--baseline-ref", required=True)
parser.add_argument("--persona", required=True)
parser.add_argument("--runner", default=os.environ.get("REVIEW_REPLAY_COMMAND"))
parser.add_argument("review_dirs", nargs="+")
args = parser.parse_args()
if not args.runner:
    print("set --runner or REVIEW_REPLAY_COMMAND (use {prompt} and {input})", file=sys.stderr)
    sys.exit(2)

prompt_path = Path(".cursor/agents") / f"reviewer-{args.persona}.md"
baseline = subprocess.run(
    ["git", "show", f"{args.baseline_ref}:{prompt_path}"], text=True, capture_output=True
)
if baseline.returncode:
    print(baseline.stderr, file=sys.stderr)
    sys.exit(2)

def replay(prompt, package):
    with tempfile.TemporaryDirectory() as directory:
        prompt_file = Path(directory) / "prompt.md"
        prompt_file.write_text(prompt)
        command = args.runner.format(prompt=shlex.quote(str(prompt_file)), input=shlex.quote(str(package)))
        result = subprocess.run(command, shell=True, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return {hashlib.sha1(line.strip().encode()).hexdigest()
                for line in result.stdout.splitlines() if line.strip()}

try:
    old, new = set(), set()
    for directory in map(Path, args.review_dirs):
        package = directory / f"{args.persona}.in.md"
        if package.exists():
            old |= replay(baseline.stdout, package)
            new |= replay(prompt_path.read_text(), package)
except RuntimeError as error:
    print(str(error), file=sys.stderr)
    sys.exit(2)
print(json.dumps({"baseline_ref": args.baseline_ref, "persona": args.persona,
                  "lost": sorted(old - new), "gained": sorted(new - old)}, indent=2))
