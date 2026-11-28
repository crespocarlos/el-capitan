#!/usr/bin/env python3
"""Hook registrations of earlier installs (a script under ~/.claude/hooks; every one now runs `crew-hook.py`), dropped
by install: a registration left for a deleted script denies every command a guard inspected. The match is the managed
path and a name this repository shipped, so a user's own `~/myhooks/session-start.sh` is not matched.
"""

import re

# Every script a released revision registered under ~/.claude/hooks.
NAMES = """block-destructive-git.sh check-publish.sh block-shell-source-edits.sh session-start.sh session-end.sh session-logger.sh
guard-shell.sh review-address-gate.sh review-address-approval.sh session-event.sh probe.sh check-write-boundary.sh
guard/credentials.sh guard/destructive-git.sh guard/local-pr-ref.sh guard/owner-only.sh guard/source-edit.sh
guard/task-files.sh guard/worker-tree.sh guard/zsh-equals.sh guard/shell.sh check-task-spec-owner.sh log-tool-use.sh
record-pr.sh notify-idle.sh memory-context.sh cursor-memory-context.sh agents-refresh.sh spec-status-reconcile.sh
memory-capture-prompt.sh capture-reply.sh mode-anchor.sh cursor-usage.sh usage.sh"""
RETIRED_SCRIPTS = tuple(NAMES.split())

# `<hooks dir>/<name>`, quoted or not: `$HOME/.claude/hooks/x.sh`, `"$HOME/.claude/hooks/x.sh"`, a resolved absolute
# `/Users/me/.claude/hooks/x.sh` and a project's `${CLAUDE_PROJECT_DIR}/.claude/hooks/x.sh` all match.
MANAGED_PATH = re.compile(r"/\.claude/hooks/" + "(" + "|".join(re.escape(s) for s in RETIRED_SCRIPTS) + r")$")


def retired(command: object) -> bool:
    """True when a registration points at a managed hooks path this repository has retired."""
    text = command if isinstance(command, str) else ""
    # The command may carry a trailing `; exit 0` or arguments; test the first path-like token.
    for token in text.split():
        token = token.strip("\"';")
        if token.endswith(tuple(RETIRED_SCRIPTS)) and MANAGED_PATH.search(token):
            return True
    return False
