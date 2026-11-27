"""Shared pytest fixtures: `tmp` is the test's own temporary directory (pytest's `tmp_path`)."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp(tmp_path: Path) -> Path:
    return tmp_path
