**Critical**

**AC1: `a per-test timeout of 60 s for every test`** — The summary says the install and upgrade tests run the real `install.sh` and allow themselves up to 300 s. A literal 60 s global timeout kills them on a cold CI runner, and pytest-timeout's signal or thread method fires before their own `subprocess` timeouts do. The suite goes red on slow runners, and the builder has no sanctioned override.

Fix: Change AC1 to set a default timeout plus a per-test override (`@pytest.mark.timeout(...)`) for the install and upgrade tests, sized above their 300 s subprocess timeouts. Alternatively, put the choice of default and override values under `## Open questions`.

**Important**

**AC2: `A deliberately sleeping fixture fails within the timeout`** — The criterion only proves that the timeout fires. It doesn't prove the e2e tests still pass under their override, or that a hung child process is cleaned up. With `-n auto` and the default signal method, a hang inside a `subprocess` running `install.sh` may leave an orphaned child or a stalled xdist worker, so the run still hangs.

Fix: Add a criterion that the install and upgrade tests still pass under the configured timeout. Add another that a hang inside a subprocess terminates the whole run, and state which `timeout_method` is used.

**Task 2 / AC2: a deliberately sleeping test in the suite** — A permanently sleeping test that "fails" makes `evals/test.sh` fail in normal runs, which contradicts the `bash evals/test.sh -n auto` check expecting green. The spec doesn't say how the test is run in expectation, for example by marking it xfail or running it in a nested pytest.

Fix: State that the sleeping fixture is run as an expected failure or in an isolated invocation, so the main suite stays green.

**AC1: `pinned like pytest-xdist`** — The spec doesn't say where the pin lives or whether CI and local environments install it from there. If `evals/test.sh` runs where the plugin is missing, `--timeout 60` fails with an "unrecognized arguments" error and the whole suite breaks. I didn't verify where `pytest-xdist` is pinned, because I never opened `evals/test.sh`.

Fix: Name the file that holds the pin, and add a criterion that `evals/test.sh` fails with a clear message, or installs the plugin, when it is missing.

Verdict: 3 finding(s), 2 unverified (`evals/test.sh` contents, the location of the `pytest-xdist` pin)