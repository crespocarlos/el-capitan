**Critical**

**Acceptance criteria #1** — "a per-test timeout of 60 s for every test" contradicts the Summary. The Summary says the install and upgrade tests run the real `install.sh` and "allow themselves up to 300 s". If a global 60 s limit is built literally, `pytest-timeout` kills those tests at 60 s on a cold CI runner. The suite then fails on slow but healthy runs. A builder would have to either raise the limit or add per-test overrides, and the spec doesn't say which.
Fix: Add a criterion for the install and upgrade tests, such as a `@pytest.mark.timeout(N)` with N above their 300 s subprocess timeouts, or a documented override. Also state that the default limit does not apply to them.

**Important**

**Acceptance criteria #1** — The spec doesn't say which timeout method to use or how it interacts with xdist. The default `signal` method does not work on Windows. It also cannot interrupt a hang inside a C call or a child process, such as `install.sh` stuck in a subprocess. The `thread` method kills the whole worker process. A hung test could therefore still stall the run, or the reported failure could lack the test's name.
Fix: Specify the timeout method, and require that a hung subprocess is terminated and that the failure names the test under `-n auto`.

**Acceptance criteria #2** — The criterion only checks that a sleeping test fails. It doesn't check that `evals/test.sh` actually passes `--timeout`. If the fixture carries its own `@pytest.mark.timeout`, it passes even when the flag is missing. A permanently failing "deliberate" fixture would also break the suite by default.
Fix: Require that the fixture relies on the default from `test.sh`, that it is excluded from normal runs, and that it is only run to prove the guard.

**Acceptance criteria #1** — The spec doesn't say what happens when `evals/test.sh` is called with a user-supplied `--timeout` or `-p no:timeout`, or when extra pytest args are passed through. The Tests command, `bash evals/test.sh -n auto`, passes arguments through. It is also unverified whether other entry points, such as CI that calls pytest directly, bypass `test.sh` and so keep the old no-timeout behavior.
Fix: Add a criterion on override behavior, and name the CI entry points that must go through `test.sh`.

Verdict: 4 finding(s), 3 unverified (I read no files: the `test.sh` pass-through, the CI invocation path and the current `pytest-xdist` pin)