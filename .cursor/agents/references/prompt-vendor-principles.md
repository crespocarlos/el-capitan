# Model-vendor prompting principles

Backdrop for the `reviewer-prompt-quality` rubric, not a checklist to apply during a review. Where a
technique names a model, it was measured on that model: flag the risk, never a universal rule.

## Anthropic — prompting best practices

(platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

- Use consistent, descriptive tag names across prompts; wrap each kind of content in its own tag and
  nest tags when the content has a natural hierarchy.
- Provide instructions as sequential steps when the order or completeness of steps matters.
- Give the reason behind a rule: a bare `NEVER do X` is weaker than "X, because Y".
- Be clear and direct: if a colleague with minimal context would be confused, the model will be too.
- Replace blanket defaults with targeted instructions, and remove over-prompting.
- Put long-form data at the top of the prompt, above the query, instructions, and examples.

## OpenAI — GPT-4.1 and GPT-5 prompting guides

(developers.openai.com/cookbook)

- Starting structure: Role and Objective, Instructions, Reasoning Steps, Output Format, Examples,
  Context.
- Conflicting instructions: GPT-4.1 tends to follow the one closest to the end of the prompt, and
  contradictions cost GPT-5 more than other models because it spends reasoning tokens trying to
  reconcile them.
- XML-style sections let a prompt reference earlier categories and sections by name; naming a section
  in the final instruction directs the model to it.
- In long contexts place instructions at both the start and the end. Behavior shown in an example
  should also appear in the rules.
- All-caps and other emphasis are rarely needed and can backfire.
