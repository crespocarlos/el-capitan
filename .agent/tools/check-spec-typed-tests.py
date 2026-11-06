#!/usr/bin/env python3
"""Exit 0 if every present typed ## Tests subsection has a non-empty Command (not bare none)."""
import re
import sys

def main():
    if sys.argv[1:] in (["-h"], ["--help"]):
        print("usage: check-spec-typed-tests.py <SPEC.md>")
        return
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
    seen = 0
    for layer in layers:
        # Specs in the wild use `### unit` and `### E2E tests`; matching case-sensitively
        # made both the layer and its Command check pass vacuously.
        pat = rf"^### {layer}\b[^\n]*$"
        matches = list(re.finditer(pat, block, re.MULTILINE | re.IGNORECASE))
        if not matches:
            continue
        seen += len(matches)
        # slice subsection
        for sm in matches:
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
    if not seen:
        print("[fail] spec-typed-tests: ## Tests has no recognized layer heading", file=sys.stderr)
        sys.exit(1)
    print("[ok] spec-typed-tests: typed blocks have commands")

if __name__ == "__main__":
    main()
