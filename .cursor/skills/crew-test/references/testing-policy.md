# Testing policy

The full rule set behind `personal.mdc` "Testing". Read it before planning tests for a non-trivial
change; the summary in the rule carries the obligation, this file carries the detail.

- **Test what can regress.** Add tests for new behavior, a fixed bug, or a changed contract — not for
  docs, config, mechanical refactors, renames, type-only changes, pass-through code, library or
  framework behavior, or coverage numbers. Prompt changes are verified with targeted evals instead.
  Scale the rest of this section to the change: a small fix needs one test and one command, not a
  plan.
- **Contract first.** For non-trivial behavioral changes, map each acceptance criterion or changed
  contract to the lowest-layer test that proves it and runs in the repository's normal CI, and state
  any gap. Include the mapping in any plan presented for approval, so approval covers the tests. For
  a bug fix, write the failing regression test first.
- **Test behavior, not implementation.** Extend existing tests or case tables before adding new ones;
  one behavior, one test, unless layers can fail independently. Assert observable behavior through
  public interfaces — not private functions, mock call counts (unless the call is the contract), or
  large snapshots.
- **Probes are not tests.** When an end-to-end or cross-system flow needs independent evidence, use an
  external Python or Playwright acceptance probe through a public interface, kept in task artifacts
  and out of the diff. It proves the change works now; committed tests protect it later.
- **Keep the suite honest.** Never delete, skip, or weaken a test, or loosen its assertions, to make it
  pass; fix the cause or report the failure. Delete or merge tests your change makes redundant.
  Before reporting, drop added tests that protect no distinct contractual behavior or failure mode; if
  unsure, keep and flag.
- **Report evidence.** Run the narrowest tests that cover the change. Before reporting a behavioral
  change that adds tests, run a pruning pass: for every kept test record the protected behavior, the
  distinct failure mode, the verification command, and its CI coverage; remove redundant tests or
  retain and flag the uncertainty. Report removed tests, probes, and gaps. With no test runner, say so
  and describe the manual check.
