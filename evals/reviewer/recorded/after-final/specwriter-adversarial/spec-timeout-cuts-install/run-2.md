**Critical**

**Acceptance criteria, criterion 1** — "a per-test timeout of 60 s for every test" contradicts the Summary. The install and upgrade tests are allowed up to 300 s by their own `subprocess` timeouts, "since a cold CI runner is slow". A global `--timeout 60` makes pytest-timeout kill them at 60 s, so they fail on every cold runner. The subprocess timeouts become dead code, and the suite goes red or flaky.

Fix: Give the e2e install and upgrade tests a longer per-test timeout (for example a `@pytest.mark.timeout(330)` marker, or a marker-based split), and state in the criterion that the 60 s default doesn't apply to them.

**Important**

**Acceptance criteria, criterion 2** — "fails within the timeout with the test's name in the output" has no negative-side criterion. Nothing requires that the long-running e2e tests still pass under their larger budget. Nothing requires that a hung test doesn't stall the whole `-n auto` run. A literal build can pass the sleeping fixture while the install tests regress.

Fix: Add a criterion that the install and upgrade tests still pass with their own limit, and that a hang under xdist fails only that test and the run completes.

**Acceptance criteria, criterion 1 ("pytest-timeout (pinned like pytest-xdist)")** — The timeout method is unspecified. The default is the signal method on POSIX. A test hung in a `subprocess` call, such as the `install.sh` child, may leave an orphaned process behind. The thread method kills the whole worker instead. In either case the temporary HOME is not cleaned up. Which method applies is left to the builder.

Fix: Specify the timeout method and require that child processes are not left running after a timeout.

**Tasks, Task 2** — The sleeping fixture lives in the permanent suite at `evals/tools/test_hang_guards.py`. A test that sleeps and is meant to fail turns the suite red on every run. Nothing says how it is made to pass, for example with `xfail` or a subprocess-run pytest that asserts on the failure. Built literally, `bash evals/test.sh` fails permanently.

Fix: Specify that the sleeping test runs in an isolated inner pytest invocation, and that the outer test asserts on the timeout output.

Verdict: 4 finding(s), 3 unverified (the install and upgrade test names and their actual timeouts, the contents of `evals/test.sh`, the existing `pytest-xdist` pin)