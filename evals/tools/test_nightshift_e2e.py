#!/usr/bin/env python3
"""Hermetic checks for crew-nightshift-e2e.py against a stub nightshift server.

The tool's contract is entirely HTTP-shaped, so a local `http.server` pins it without touching a
real nightshift install: the request bodies it sends, the endpoints it must never call, and how
nightshift's own error text is surfaced. `doctor` is exercised through the same stub plus a
temporary checkout, so its check names and fixes are pinned too.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review" / "crew-nightshift-e2e.py"
KEY = "elastic__kibana__12345"
TESTED_HEAD = "0123456789ab"  # arbitrary: the tool must pass `meta.headSha` through unchanged

# Paths the tool must never touch: the queue posts a PR comment by default, and post-comment
# publishes external state. Both are user decisions, not side effects of asking for a run.
FORBIDDEN = {("/api/e2e/queue", "POST"), ("/api/e2e/post-comment", "POST"), ("/api/state", "GET")}


class Stub:
    """Records every request and answers from a routing table the test sets up."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.routes: dict[tuple[str, str], tuple[int, dict]] = {}
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # keep the test output readable
                pass

            def _record(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"null") if length else None
                stub.requests.append({"method": method, "path": self.path, "body": body})

            def _respond(self, method: str) -> None:
                self._record(method)
                status, payload = stub.routes.get(
                    (method, self.path.split("?")[0]),
                    (200, {"queued": [], "auto": [], "errors": {}, "worktree": None, "machines": []}),
                )
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._respond("GET")

            def do_POST(self) -> None:
                self._respond("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def route(self, method: str, path: str, status: int, payload: object) -> None:
        self.routes[(method, path)] = (status, payload)

    def calls(self) -> list[tuple[str, str]]:
        return [(item["method"], item["path"].split("?")[0]) for item in self.requests]

    def body_of(self, method: str, path: str) -> dict:
        for item in self.requests:
            if item["method"] == method and item["path"].split("?")[0] == path:
                return item["body"] or {}
        raise AssertionError(f"no {method} {path} request; saw {self.calls()}")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def run(stub: Stub | None, *args: str, checkout: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ,
           "NIGHTSHIFT_URL": stub.url if stub else "http://127.0.0.1:9",
           "NIGHTSHIFT_PR_HELPER_DIR": checkout or os.environ.get("_STUB_DIR", "/nonexistent-checkout")}
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def fake_checkout(tmp: Path) -> Path:
    """A directory that resolves as a checkout without needing writes a sandbox refuses.

    `git init` and `.git/config` are both blocked under the sandbox, so this is a `.git`
    directory holding only HEAD plus `node_modules/tsx`: enough for `doctor` to get past
    `location` and `node_modules`. The `repo` check is expected to fail on it, which is not
    what the tests using it assert.
    """
    checkout = tmp / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (checkout / "node_modules" / "tsx").mkdir(parents=True)
    return checkout


def never_forbidden(stub: Stub) -> None:
    hit = FORBIDDEN & set(stub.calls())
    assert not hit, f"touched a forbidden endpoint: {sorted(hit)}"


def test_start_sends_the_documented_body(tmp: Path) -> None:
    stub = Stub()
    try:
        stub.route("POST", f"/api/e2e/{KEY}", 200, {"status": {"state": "waiting-deploy"}})
        result = run(stub, "start", KEY, "--worktree", "kibana", "--deploy",
                     "--instructions", "check the saved-object round trip")
        assert result.returncode == 0, result.stderr
        assert stub.body_of("POST", f"/api/e2e/{KEY}") == {
            "action": "start", "worktree": "kibana", "deploy": True,
            "instructions": "check the saved-object round trip",
        }
        payload = json.loads(result.stdout)
        assert payload["started"]["status"]["state"] == "waiting-deploy"
        assert payload["run"].endswith(f"/pr/{KEY}/e2e")
        never_forbidden(stub)
    finally:
        stub.close()


def test_start_defaults_deploy_to_false(tmp: Path) -> None:
    """Deploying replaces whatever runs in that worktree, so it is never implied."""
    stub = Stub()
    try:
        stub.route("POST", f"/api/e2e/{KEY}", 200, {"status": {"state": "waiting-deploy"}})
        assert run(stub, "start", KEY, "--worktree", "kibana").returncode == 0
        assert stub.body_of("POST", f"/api/e2e/{KEY}")["deploy"] is False
    finally:
        stub.close()


def test_status_and_report_read_the_run(tmp: Path) -> None:
    stub = Stub()
    try:
        stub.route("GET", f"/api/e2e/{KEY}", 200, {
            "status": {"state": "done"}, "outdated": False,
            "meta": {"worktreeLabel": "kibana-main", "headSha": TESTED_HEAD},
            "report": {
                "verdict": "pass", "summary": "all good", "approach": "playwright",
                "checks": [
                    {"title": "loads", "status": "pass", "via": ["ui", "api"], "details": "d"},
                    {"title": "health", "status": "pass", "via": ["health"], "details": "d"},
                    {"title": "unit", "status": "pass", "via": ["unit", "script"], "details": "d"},
                    {"title": "skipped ui", "status": "skipped", "via": ["ui"], "details": "d"},
                ],
                "findings": [{"kind": "note", "title": "slow"}],
                "notCovered": ["permissions"],
                "environmentChanges": ["restarted Kibana"],
            },
        })
        status = json.loads(run(stub, "status", KEY).stdout)
        assert status["state"] == "done" and status["finished"] is True
        assert status["worktree"] == "kibana-main"
        # The skill compares this with the PR's current head; without it a stale run reads as current.
        assert status["testedHead"] == TESTED_HEAD
        report = json.loads(run(stub, "report", KEY).stdout)
        assert report["testedHead"] == TESTED_HEAD
        assert report["verdict"] == "pass"
        assert report["findings"][0]["title"] == "slow"
        assert report["notCovered"] == ["permissions"]
        assert report["environmentChanges"] == ["restarted Kibana"]
        # Nightshift's `via` is a list, and a skipped check proves nothing either way: a passing
        # check observed only by a health probe or a script must be named as not end-to-end,
        # while a skipped one is neither claimed nor flagged.
        assert report["not_end_to_end"] == ["health", "unit"]
        assert [c["end_to_end"] for c in report["checks"]] == [True, False, False, False]
        never_forbidden(stub)
    finally:
        stub.close()


def test_report_before_a_run_finishes_is_an_error(tmp: Path) -> None:
    stub = Stub()
    try:
        stub.route("GET", f"/api/e2e/{KEY}", 200, {"status": {"state": "running"}, "report": None})
        result = run(stub, "report", KEY)
        assert result.returncode == 1 and "no report yet" in result.stderr
        assert "running" in result.stderr
    finally:
        stub.close()


def test_non_object_success_response_is_an_api_error(tmp: Path) -> None:
    """The API contract is JSON objects; a success status does not make a list valid output."""
    stub = Stub()
    try:
        stub.route("GET", f"/api/e2e/{KEY}", 200, ["not", "an", "object"])
        result = run(stub, "status", KEY)
        assert result.returncode == 1, result.stderr
        assert "invalid JSON object response" in result.stderr
    finally:
        stub.close()


def test_followup_and_stop_use_their_actions(tmp: Path) -> None:
    stub = Stub()
    try:
        stub.route("POST", f"/api/e2e/{KEY}", 200, {"ok": True})
        assert run(stub, "followup", KEY, "does it survive a restart?").returncode == 0
        assert run(stub, "stop", KEY).returncode == 0
        posts = [item["body"] for item in stub.requests if item["method"] == "POST"]
        assert {"action": "followup", "question": "does it survive a restart?"} in posts
        assert {"action": "stop"} in posts
        never_forbidden(stub)
    finally:
        stub.close()


def test_nightshift_error_text_reaches_the_user(tmp: Path) -> None:
    """An untracked PR is nightshift's own message, not something crew rewrites."""
    stub = Stub()
    try:
        stub.route("POST", f"/api/e2e/{KEY}", 400,
                   {"error": "PR not found in the current snapshot or a saved review workspace"})
        result = run(stub, "start", KEY, "--worktree", "kibana")
        assert result.returncode == 1
        assert "PR not found in the current snapshot" in result.stderr
    finally:
        stub.close()


def test_unreachable_server_exits_3(tmp: Path) -> None:
    assert run(None, "status", KEY).returncode == 3


def test_invalid_key_is_rejected_before_any_request(tmp: Path) -> None:
    stub = Stub()
    try:
        for bad in ("kibana-12345", "elastic__kibana", KEY + "x", "../etc"):
            assert run(stub, "status", bad).returncode == 2, bad
        assert stub.requests == [], stub.calls()
    finally:
        stub.close()


def test_stack_stop_posts_the_stop_stack_action_only(tmp: Path) -> None:
    stub = Stub()
    try:
        stub.route("POST", "/api/deploy", 200, {"ok": True})
        result = run(stub, "stack-stop", "--worktree", "wt-abc")
        assert result.returncode == 0, result.stderr
        assert stub.calls() == [("POST", "/api/deploy")], stub.calls()
        # `restore` would revert the user's checkout; only the stack may be stopped.
        assert stub.body_of("POST", "/api/deploy") == {"action": "stop-stack", "worktree": "wt-abc"}
    finally:
        stub.close()


def test_dev_stack_note_flags_a_script_that_ignores_eis(tmp: Path) -> None:
    module = load_module()
    root = tmp / "checkout"
    (root / "examples" / "kibana-dev-tools").mkdir(parents=True)
    (root / "examples" / "kibana-dev-tools" / "dev_stack.sh").write_text("[ \"$DEV_STACK_EIS\" = 1 ]\n")
    stale, current = tmp / "stale.sh", tmp / "current.sh"
    stale.write_text("eis_setup\n")
    current.write_text("DEV_STACK_EIS handled\n")
    assert module.dev_stack_current(root, str(stale))[0] is False
    assert module.dev_stack_current(root, str(current))[0] is True
    assert module.dev_stack_current(root, str(tmp / "missing.sh"))[0] is True
    assert module.dev_stack_current(root, None)[0] is True


def test_status_tails_the_last_fatal_line_on_failure(tmp: Path) -> None:
    stub = Stub()
    try:
        worktree = tmp / "worktree"
        (worktree / ".dev-stack").mkdir(parents=True)
        (worktree / ".dev-stack" / "kibana.log").write_text(
            "INFO starting\nFATAL first failure\nINFO retry\nFATAL real cause: missing connector\n")
        stub.route("GET", f"/api/e2e/{KEY}", 200, {
            "status": {"state": "failed", "error": "build_package.js missing"}, "meta": {}})
        result = json.loads(run(stub, "status", KEY, "--worktree-path", str(worktree)).stdout)
        assert result["fatal"] == "FATAL real cause: missing connector"
        # No path, or a done/running state: never attempt to read a log.
        no_path = json.loads(run(stub, "status", KEY).stdout)
        assert "fatal" not in no_path
        stub.route("GET", f"/api/e2e/{KEY}", 200, {"status": {"state": "running"}, "meta": {}})
        running = json.loads(run(stub, "status", KEY, "--worktree-path", str(worktree)).stdout)
        assert "fatal" not in running
    finally:
        stub.close()


def test_port_in_use_detects_a_bound_local_port(tmp: Path) -> None:
    module = load_module()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert module.port_in_use(port) is True
    # Nothing should still be listening right after the socket closes and the OS frees it;
    # retry briefly in case TIME_WAIT races the check.
    for _ in range(20):
        if not module.port_in_use(port):
            break
        time.sleep(0.05)
    assert module.port_in_use(port) is False


def test_duplicate_config_keys_flags_a_repeated_key_only(tmp: Path) -> None:
    module = load_module()
    clean = tmp / "clean.json"
    clean.write_text('{"a": 1, "b": {"c": 2}}')
    assert module.duplicate_config_keys(clean) == []
    dupes = tmp / "dupes.json"
    dupes.write_text('{"a": 1, "a": 2, "b": {"c": 3, "c": 4}}')
    assert sorted(module.duplicate_config_keys(dupes)) == ["a", "c"]
    assert module.duplicate_config_keys(tmp / "missing.json") == []
    broken = tmp / "broken.json"
    broken.write_text("{not json")
    assert module.duplicate_config_keys(broken) == []


def test_doctor_reports_ports_and_config_duplicate_notes(tmp: Path) -> None:
    stub = Stub()
    checkout = fake_checkout(tmp)
    (checkout / "config.local.json").write_text('{"e2e": {"enabled": true}, "e2e": false}')
    try:
        stub.route("GET", "/api/e2e/queue", 200, {
            "queued": [], "auto": [], "errors": {}, "worktree": None,
            "machines": [{"id": "default", "label": "kibana", "enabled": True}],
        })
        result = run(stub, "doctor", checkout=str(checkout))
        payload = json.loads(result.stdout)
        notes = {note["check"]: note for note in payload["notes"]}
        assert "ports_free" in notes
        assert notes["config_duplicate_keys"]["ok"] is False
        assert "e2e" in notes["config_duplicate_keys"]["detail"]
        assert notes["helper_up_to_date"]["ok"] is True  # no remote on this checkout: skipped
    finally:
        stub.close()


def load_module():
    if str(TOOL.parent) not in sys.path:
        sys.path.insert(0, str(TOOL.parent))  # the package directory, where its bootstrap lives
    spec = importlib.util.spec_from_file_location("nightshift_e2e", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_check_matches_the_exact_repo_only(tmp: Path) -> None:
    """A lookalike remote must fail: the config loader runs code from the checkout."""
    module = load_module()
    for good in ("https://github.com/elastic/nightshift-pr-helper",
                 "https://github.com/elastic/nightshift-pr-helper.git",
                 "git@github.com:elastic/nightshift-pr-helper.git",
                 "ssh://git@github.com/elastic/nightshift-pr-helper"):
        assert module.is_canonical_remote(good), good
    for bad in ("https://github.com/evilelastic/nightshift-pr-helper",
                "git@github.com:notelastic/nightshift-pr-helper.git",
                "https://github.com/elastic/nightshift-pr-helper-fork",
                "https://github.com/x/elastic/nightshift-pr-helper"):
        assert not module.is_canonical_remote(bad), bad


def test_doctor_prefers_plist_working_directory_over_the_default(tmp: Path) -> None:
    """The checkout that serves the port wins, so crew does not inspect a different clone."""
    stub = Stub()
    checkout = tmp / "served-checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (checkout / "node_modules" / "tsx").mkdir(parents=True)
    launch_agents = tmp / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    (launch_agents / "dev.prhelper.web.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'<key>WorkingDirectory</key><string>{checkout}</string>\n'
        '</dict></plist>\n'
    )
    try:
        stub.route("GET", "/api/e2e/queue", 200, {
            "queued": [], "auto": [], "errors": {}, "worktree": "kibana",
            "machines": [{"id": "default", "label": "kibana", "enabled": True}],
        })
        env = {**os.environ, "NIGHTSHIFT_URL": stub.url, "HOME": str(tmp)}
        env.pop("NIGHTSHIFT_PR_HELPER_DIR", None)
        result = subprocess.run([sys.executable, str(TOOL), "doctor"],
                                capture_output=True, text=True, env=env)
        payload = json.loads(result.stdout)
        # HOME points at the fixture plist; the tool must follow it instead of its default path.
        assert payload["root"] == str(checkout), payload
        first = payload["checks"][0]
        assert first["check"] == "location" and first["ok"] is True, payload
        # `/api/state` advances the queue and can start a run; a preflight must never call it.
        assert ("GET", "/api/state") not in stub.calls(), stub.calls()
    finally:
        stub.close()


def test_doctor_reports_a_fix_for_each_failing_check(tmp: Path) -> None:
    stub = Stub()
    checkout = fake_checkout(tmp)
    try:
        stub.route("GET", "/api/e2e/queue", 200, {
            "queued": [], "auto": [], "errors": {}, "worktree": "no machine enabled",
            "machines": [{"id": "default", "label": "kibana", "enabled": False}],
        })
        result = run(stub, "doctor", checkout=str(checkout))
        payload = json.loads(result.stdout)
        assert result.returncode == 1 and payload["ok"] is False, payload
        failing = [c for c in payload["checks"] if not c["ok"]]
        assert any(c["check"] == "machine_enabled" for c in failing), failing
        assert all(c["fix"] for c in failing), failing
        assert all(not c["fix"] for c in payload["checks"] if c["ok"])
        assert ("GET", "/api/state") not in stub.calls()
    finally:
        stub.close()


def test_worktrees_lists_designated_ones(tmp: Path) -> None:
    stub = Stub()
    try:
        stub.route("GET", "/api/deploy", 200, {"worktrees": [
            {"id": "kibana", "label": "main", "branch": "main", "kibanaPort": 5601,
             "kibanaRunning": True, "dirty": ["x.ts"], "deploy": {"state": "ready"}},
            {"id": "e2e-1", "label": "dedicated", "branch": "feature/x", "kibanaPort": 5602,
             "kibanaRunning": False, "path": "/Users/x/worktrees/kibana-e2e-1"},
        ]})
        payload = json.loads(run(stub, "worktrees").stdout)
        assert payload["worktrees"] == [
            {"id": "kibana", "label": "main", "name": None, "branch": "main", "kibanaPort": 5601,
             "kibanaRunning": True, "path": None, "dirty": ["x.ts"], "dirtyCount": 1,
             "mainRepoRisk": True},
            {"id": "e2e-1", "label": "dedicated", "name": None, "branch": "feature/x",
             "kibanaPort": 5602, "kibanaRunning": False, "path": "/Users/x/worktrees/kibana-e2e-1",
             "dirty": [], "dirtyCount": 0, "mainRepoRisk": False},
        ]
        assert "GET", "/api/deploy" in [(i["method"], i["path"].split("?")[0]) for i in stub.requests]
    finally:
        stub.close()


def main() -> int:
    tests = [value for key, value in globals().items() if key.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test(Path(tmp))
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
