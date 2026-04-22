#!/usr/bin/env python3
"""Exit 0 if every present typed ## Tests subsection has a non-empty Command (not bare none)."""
import re
import sys

def main():
    if len(sys.argv) != 2:
        print("usage: check-spec-typed-tests.py <SPEC.md>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print(f"[fail] cannot read spec: {e}", file=sys.stderr)
        sys.exit(1)
    m = re.search(r"^## Tests", text, re.MULTILINE)
    if not m:
        print("[ok] spec-typed-tests: no ## Tests section")
        return
    start = m.end()
    rest = text[start:]
    m2 = re.search(r"^## [^#\s]", rest, re.MULTILINE)
    block = rest[: m2.start()] if m2 else rest
    layers = ("Unit", "Integration", "E2E", "Validation")
    for layer in layers:
        pat = rf"^### {layer}\s*$"
        if not re.search(pat, block, re.MULTILINE):
            continue
        # slice subsection
        subm = list(re.finditer(pat, block, re.MULTILINE))
        for sm in subm:
            i = sm.end()
            tail = block[i:]
            nm = re.search(r"^### ", tail, re.MULTILINE)
            sub = tail[: nm.start()] if nm else tail
            cmd_m = re.search(
                r"^\s*-\s*\*\*Command\*\*:\s*(.+)$|^\s*\*\*Command\*\*:\s*(.+)$|^\s*-\s*Command:\s*(.+)$|^\s*Command:\s*(.+)$",
                sub,
                re.MULTILINE | re.IGNORECASE,
            )
            if not cmd_m:
                print(f"[fail] spec-typed-tests: ### {layer} missing Command line", file=sys.stderr)
                sys.exit(1)
            val = next((g for g in cmd_m.groups() if g), "").strip()
            if not val or val.lower() == "none" or val == "<test command or \"none\">":
                print(
                    f"[fail] spec-typed-tests: ### {layer} Command empty or none-only",
                    file=sys.stderr,
                )
                sys.exit(1)
    print("[ok] spec-typed-tests: typed blocks have commands")

if __name__ == "__main__":
    main()
