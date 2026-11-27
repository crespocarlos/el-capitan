**Critical**

**Acceptance criteria 1 / Summary ("a per-test timeout of 60 s for every test")** — The spec contradicts itself. The Summary says the install and upgrade tests legitimately run up to 300 s because cold CI runners are slow. A uniform 60 s limit will kill them on slow runners, so the suite turns flaky or red.

Fix: Set a per-test override for the end-to-end rows (a marker or per-test timeout larger than their 300 s subprocess timeouts), or state the tiered limits explicitly. Add a criterion that the install and upgrade tests still pass under the new limits.

**Important**

**Acceptance criteria 2 / Tests** — The criterion only covers the default timeout case. It doesn't prove that the long-running tests get a longer limit, or that their own `subprocess` timeouts still fire first. The spec also doesn't say whether the 300 s tests are a few rows or many.

Fix: Add a criterion that an end-to-end test running longer than 60 s but shorter than its override passes, and that one exceeding the override fails with its name.

**Tests ("Unit" only; `bash evals/test.sh -n auto`)** — The sleeping fixture must fail on purpose, so it would turn the normal suite run red. The spec doesn't say how it is expected to fail (xfail, a separate invocation, or a meta-test). A passing suite and the "fails within the timeout" criterion can't both hold as written. Whether the suite runs the real install end to end also isn't addressed.

Fix: State how the hang guard is run and asserted, for example as a subprocess meta-test that expects the timeout failure, and name the layer.

**Task 1 / `-n auto` (xdist)** — The spec doesn't say which timeout method to use. With xdist and a `subprocess` child, the signal method can leave the `install.sh` child process running. The thread method can kill the whole worker. Either way, the test's name may not appear in the output the way criterion 2 requires.

Fix: Specify the timeout method and require that a timed-out test's subprocess is cleaned up and the test's name is reported under xdist.

**Summary** — The motivating hang ran 23 minutes. The spec doesn't say whether that was a unit row or an end-to-end row, or what it was blocked on. If it was an install test blocked inside `subprocess` with a 300 s timeout, the existing timeouts apparently didn't prevent it, and a pytest limit may not either.

Fix: Identify the hung test and show that the chosen mechanism would have caught it.

Verdict: 4 finding(s), 2 unverified. I couldn't verify the `evals/` files, because the case directory has no `evals/` contents (the Glob found nothing). I also couldn't verify the originating issue.