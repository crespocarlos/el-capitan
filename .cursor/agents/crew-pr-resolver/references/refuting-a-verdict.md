# Refuting a verdict

Step 4 detail for `crew-pr-resolver`. One pass over the verdicts you just assigned, using the file
already loaded — no new reads. Its only job is to catch a verdict the comment did not deserve.

## The move

Take each verdict and argue the other side. State what would have to be true for the opposite verdict,
then check that against the lines you already hold. A verdict you cannot defend against the code was a
guess.

## Per verdict

- **Reject** must survive its own counter-argument. If the comment's claim holds at the cited line, it
  is not a reject. A reject you cannot defend drops to `Ask`, because the floor rule already says a
  doubtful reject cannot close a thread.
- **Apply** must not be what the comment asked for *because* the comment asked. Check the edit against
  the intent, the tests, and any fixture whose expected value it moves — a fixture edit proves the test
  agrees with the change, not that the change is right.
- **Adapt** is a Reject plus a different edit. Refute both halves: the concern must hold, and the
  replacement edit must address it.
- **Decide** is the easiest verdict to abuse: it looks diligent while dropping a real bug. If the code
  settles the claim it is a fault, and belongs as Apply or Reject. `Decide` is only for a comment that
  asks to change a decision the author owns.
- **Already Addressed** must cite the line that already contains the fix. "I remember seeing this" is
  not a citation.
- **Defer** and **Ask** need the reason they are not settled here, not merely that they are hard. An
  `Ask` states the exact unknown; a `Defer` states what scope the comment falls outside.

## Recording it

One clause on the report row, so a reader sees the verdict survived a challenge rather than being
asserted:

```
| 3 | path/to/file.ts:120 | @who | Reject · 4 | — | Not changing this: … | refuted: no — the guard is absent at `path/to/file.ts:120` |
```

A verdict that flips keeps its new value and the clause says what flipped it. A run where every
verdict survives is the expected outcome; the clause exists so that outcome is visible rather than
assumed.
