#!/usr/bin/env python3
"""The nightshift HTTP client: one request shape, and one error per way it can fail.

The server is `NIGHTSHIFT_URL` (default `http://localhost:3737`). Two failures are distinguished
because they mean different things to a caller: `ApiError` means the server answered and rejected
the request, carrying nightshift's own `error` text unchanged, and `Unreachable` means nothing
answered at all. The entry point maps those to exit 1 and exit 3, so "the run was refused" never
reads the same as "the machine could not be asked".
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:3737"
KEY = re.compile(r"^[A-Za-z0-9._-]+__[A-Za-z0-9._-]+__\d+$")


class ApiError(RuntimeError):
    """The server answered and rejected the request; `message` is its own `error` field."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Unreachable(RuntimeError):
    """Nothing answered on the port; the caller maps this to its own exit code."""


def base_url() -> str:
    return (os.environ.get("NIGHTSHIFT_URL", "").strip() or DEFAULT_URL).rstrip("/")


def request(method: str, path: str, body: dict | None = None, timeout: float = 60.0) -> dict:
    """One JSON call; a shaped object or one of the two errors above."""
    url = base_url() + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            try:
                payload = json.loads(response.read().decode() or "{}")
            except json.JSONDecodeError as error:
                raise ApiError(f"invalid JSON response from {url}") from error
            if not isinstance(payload, dict):
                raise ApiError(f"invalid JSON object response from {url}")
            return payload
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error") if isinstance(parsed, dict) else detail
        except json.JSONDecodeError:
            message = detail or error.reason
        raise ApiError(str(message), status=error.code) from error
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise Unreachable(str(getattr(error, "reason", error))) from error


def check_key(key: str) -> str:
    """The key itself, or ValueError naming the expected shape."""
    if not KEY.match(key):
        raise ValueError(f"{key!r} is not a nightshift PR key (expected owner__repo__number)")
    return key


def agent_check(cli: str) -> tuple[bool, str]:
    """Ask nightshift whether a harness works; a 502 carries its own install message."""
    try:
        payload = request("GET", f"/api/agents?cli={cli}", timeout=30)
    except ApiError as error:
        return False, str(error)
    except Unreachable as error:
        return False, f"server unreachable: {error}"
    models = payload.get("models")
    if not models:
        return False, f"no {cli} models available; check its installation and sign-in"
    return True, ""
