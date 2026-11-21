#!/usr/bin/env python3
"""Hook scripts this repository no longer ships, shared by both settings mergers.

A registration left behind for a deleted script is worse than a missing one: the guards are
fail-closed, so the hook errors and the command it was inspecting is denied. Both mergers therefore
drop these on every install.

Ownership matters. The match is anchored to the managed install path rather than the bare file name,
because `session-start.sh` and `check-publish.sh` are common names a user's own hook directory may
also contain, and silently unregistering one of those would stop a working hook with no message.

A script belongs in this list only if some released revision registered it. `block-zsh-equals-expansion.sh`
does not: it was never committed (git log --all has no entry for it), so it is deliberately absent.

`guard-shell.sh`, `review-address-gate.sh`, and `review-address-approval.sh` are here because the
hook-contract change replaced them: four shell rules now live one per file under `hooks/guard/`, and
the review-address gate is a `permissions.ask` rule rather than a marker protocol. Any install that
still registers them would run a script that no longer exists.
"""

import re

RETIRED_SCRIPTS = (
    "block-destructive-git.sh",
    "check-publish.sh",
    "block-shell-source-edits.sh",
    "session-start.sh",
    "session-end.sh",
    "session-logger.sh",
    "guard-shell.sh",
    "review-address-gate.sh",
    "review-address-approval.sh",
)

# `<hooks dir>/<name>` where the hooks directory is this installer's managed destination, quoted or
# not: `$HOME/.claude/hooks/x.sh`, `"$HOME/.claude/hooks/x.sh"`, and a resolved absolute
# `/Users/me/.claude/hooks/x.sh` all match. A path such as `~/myhooks/session-start.sh` does not.
MANAGED_PATH = re.compile(r"/\.claude/hooks/" + "(" + "|".join(re.escape(s) for s in RETIRED_SCRIPTS) + r")$")


def retired(command: object) -> bool:
    """True when a registration points at a managed hooks path this repository has retired."""
    text = command if isinstance(command, str) else ""
    # The command may carry a trailing `; exit 0` or arguments; test the first path-like token.
    for token in text.split():
        token = token.strip("\"'")
        if token.endswith(tuple(RETIRED_SCRIPTS)) and MANAGED_PATH.search(token):
            return True
    return False
