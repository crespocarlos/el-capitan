"""Shared pytest fixtures: `tmp` is the test's own temporary directory (pytest's `tmp_path`).

The caller's Claude config dir, auto-memory switch and session id are dropped from the environment, so an install a
test runs into a throwaway HOME never writes into the real config dir; a test that needs one sets it.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

for _name in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_SESSION_ID"):
    os.environ.pop(_name, None)


@pytest.fixture(autouse=True)
def runs_ledger(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs ledger reviews and resolves append to, kept out of the real `~/.agent/state` for every test."""
    from crew.lib import runs

    path = tmp_path_factory.mktemp("state") / "runs.jsonl"
    monkeypatch.setattr(runs, "ledger", lambda: path)
    return path


@pytest.fixture
def tmp(tmp_path: Path) -> Path:
    return tmp_path
