**Critical**

**"A hung test ran for 23 minutes before anyone noticed; `evals/test.sh` has no per-test timeout. The suite holds fast unit rows and a few end-to-end rows: the install and upgrade tests run the real `install.sh`... allow themselves up to 300 s with their own `subprocess` timeouts"** — The uniform 60 s timeout contradicts the 300 s the spec itself says the install and upgrade tests need.

Criterion 1 requires "a per-test timeout of 60 s for every test". Those e2e tests would be killed by pytest-timeout on a cold CI runner, well before their own subprocess timeouts fire, so the change turns slow-but-healthy runs into failures. The spec does not say which of the two should win.

Fix: Put the choice under Open questions. Either give the e2e tests a per-test override (marker or a higher limit) and say what it is, or justify 60 s for them with evidence.

**Important**

**Acceptance criteria 2 and Tests/Unit** — The sleeping fixture does not prove the timeout is applied through `evals/test.sh`.

If the fixture sleeps for 60 s or more, it slows every run. If it carries its own `@pytest.mark.timeout`, it passes without test.sh's `--timeout 60` ever being exercised. As written it also fails the suite permanently, so the spec must say how it is expected to fail without breaking the normal run (xfail or deselect). "Fails within the timeout" has no numeric bound either.

Fix: Specify a test that invokes `evals/test.sh` (or its pytest command line) on a short-sleep fixture with a reduced timeout. It should assert a nonzero exit and the test name in the output, and the fixture should be excluded from the default run.

**Acceptance criteria 1 / `-n auto`** — The spec does not say how the timeout behaves under pytest-xdist, or which timeout method is used.

The signal method does not work on every platform or thread, and the thread method kills the whole worker process. Under xdist that can crash the worker and make the report confusing, so the test name might not appear in the output. The "test's name in the output" criterion depends on this.

Fix: State the `--timeout-method` choice and add a criterion that the name is reported under `-n auto`.

**Tasks / pinning** — "Pinned like `pytest-xdist`" is unverified, and the spec does not say where the pin lives.

I did not check how `pytest-xdist` is pinned in `evals/test.sh`. The spec does not say whether a requirements file, an inline `--with` flag, or something else is meant. An implementer could pin in the wrong place.

Fix: Name the file and the line where the xdist pin lives.

**Consider**

**Summary** — The 23-minute hang was never reproduced or traced to a cause.

A 60 s timeout stops a hang from going unnoticed. It does not address whether the hang came from a subprocess without a timeout, which pytest-timeout may not clean up (orphan child processes).

Fix: Say whether the hung test is known, and whether subprocess children are cleaned up when a test is killed.

Verdict: 4 finding(s), 2 unverified (how `pytest-xdist` is pinned in `evals/test.sh`; the originating issue and the hung test's identity). I did not read any case files.