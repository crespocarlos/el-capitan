**Critical**

**Task 1** — calls `slug_from_url`, which only Task 3 adds

Task 1's verify line runs before Task 3 has created the helper, so the builder's sequential loop fails at Task 1.

Move Task 3 before Task 1.

Verdict: 1 finding(s)
