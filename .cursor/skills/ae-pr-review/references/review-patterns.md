# Review Patterns

Review dimensions and what to look for in each. Inspired by [CodeRabbit's category framework](https://docs.coderabbit.ai/guides/dashboard-metrics) — six dimensions that cover the space of meaningful review findings.

Automated tools (linters, SAST, CodeRabbit itself) handle surface-level detection well. This skill focuses on the deeper analysis they miss: intent mismatches, cross-component impact, and completeness gaps.

## Review dimensions

Every finding falls into one of these six categories. Scan for all six on every PR — don't let the change type bias which dimensions you check.

### 1. Functional Correctness

Logic errors that produce wrong results.

- Off-by-one errors in loops, slicing, pagination
- Incorrect boolean conditions (AND vs OR, negation errors)
- Wrong comparison operators (`>` vs `>=`, `==` vs `===`)
- Algorithm mistakes — does the implementation match the stated intent?
- **Intent mismatch** — code does something subtly different from what the PR description claims (automated tools miss this consistently)

### 2. Stability & Availability

Issues that cause crashes, hangs, or resource leaks at runtime.

- Null/undefined access without guards
- Unhandled promise rejections, missing `catch` blocks
- Resource leaks — open connections, timers, subscriptions without cleanup
- Deadlocks, race conditions in concurrent code
- Error handling that swallows exceptions silently (empty `catch {}`)
- Retry logic without backoff or max attempts

### 3. Performance & Scalability

Inefficiencies that impact speed or resource usage under real workloads.

- N+1 queries — fetching in a loop instead of batching
- Missing memoization on expensive computations called repeatedly
- Unbounded data structures — arrays that grow without limit
- Synchronous blocking in async contexts
- **Only flag when the path is hot or the data is large.** "This O(n²) loop runs on a 5-element array" is not a real finding.

### 4. Data Integrity & Integration

Problems that corrupt data or break API/schema contracts.

- Type changes that propagate incorrectly to consumers
- Missing database transaction boundaries around multi-step writes
- Schema migration mismatches — code expects fields the schema doesn't have (or vice versa)
- **Broken downstream consumers** — the most important category automated tools miss. A change that's locally correct but breaks callers is invisible to linters and surface-level AI review.
- Serialization/deserialization mismatches (API sends X, client expects Y)

### 5. Security & Privacy

Vulnerabilities that enable exploitation or expose sensitive data.

- Authentication/authorization bypass in new endpoints or changed guards
- Injection vectors — unsanitized user input in queries, commands, templates
- Exposed secrets — tokens, keys, credentials in code or config
- Overly permissive CORS, CSP, or access control policies
- Logging sensitive data (PII, tokens, passwords)

### 6. Maintainability & Code Quality

Code hygiene affecting readability and future changes. **Apply a high bar here** — only flag maintainability issues that cause real confusion or make bugs likely. Don't duplicate what linters catch.

- Duplicated logic that should be extracted (same pattern in 3+ places)
- Abstraction at the wrong level — too generic (YAGNI) or too specific (can't extend)
- Dead code left behind by the change
- Naming that actively misleads (function called `getUser` that also modifies state)

## Size-based strategy

How aggressively to review based on PR size:

| PR size | Lines | Strategy |
|---------|-------|----------|
| Small | < 100 | Read every line. Full context for all changed files. Check all consumers. |
| Medium | 100–500 | Read all behavioral changes. Skim structural changes. Spot-check consumers for key exports. |
| Large | 500–1500 | Identify the spine (2-3 key decisions). Review the spine thoroughly. Skim the rest for red flags. |
| Very large | > 1500 | File-level triage first (see [commands.md](./commands.md)). Focus on new files and most-changed files. Review tests separately. |

## Finding types

When producing findings, classify each one:

- **Potential issue** — a real bug, vulnerability, or broken contract. Needs action.
- **Improvement** — code works but could be meaningfully better (maintainability, performance, clarity). Suggest, don't demand.
- **Nitpick** — style, naming, minor preference. **Skip these entirely** unless they cause genuine confusion. The linter handles style.

## What automated tools miss

Focus your depth on these — they're where human review provides the most value over tools like CodeRabbit:

1. **Intent mismatch** — code doesn't match what the PR description says it does
2. **Cross-component impact** — change is locally correct but breaks a consumer, caller, or downstream system
3. **Completeness** — what's NOT in the diff that should be (missing tests, missing error paths, missing docs, missing migration)
4. **Design fitness** — is this the simplest approach that works? Is the abstraction level right? Would a different structure prevent future bugs?
5. **Behavioral subtleties** — refactors that silently change behavior, weakened test assertions, changed defaults
