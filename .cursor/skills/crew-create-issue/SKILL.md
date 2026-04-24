---
name: crew-create-issue
description: "Structure a rough idea into a well-formed GitHub issue and file it. Trigger: 'crew create issue' or 'crew create issue: <description>'."
---

# Create Issue

**Primary source: the current session conversation.** Synthesize the issue from what has already been discussed — do not ask questions to fill gaps. The session context is the source of truth.

## When Invoked

### Step 1: Identify the target repo

Infer from git context:

```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null
```

If that returns a repo, use it. If the current directory is not a git repo and no repo was mentioned in the conversation, ask exactly one question: **"Which repo? (OWNER/REPO)"**

### Step 2: Synthesize issue content from session

Mine the current conversation for:

- **Problem statement** — what is broken or missing
- **Context** — background, motivation, what was discussed
- **Acceptance criteria** — what "done" looks like (from any decision, proposal, or agreed outcome in the conversation)
- **Scope** — what is explicitly in or out of scope

Do not ask for any of these. If the conversation doesn't cover something, leave that section minimal or omit it — do not prompt the user.

### Step 3: Auto-classify issue type

Classify from synthesized content as **bug** or **feature**:

- Bug: something broken, an error, unexpected behavior, regression, crash
- Feature: something new — a capability, workflow, integration, enhancement

Default to **feature** if ambiguous. *(Features are lower-risk to mis-classify — a false bug report creates noise in the bug queue; a false feature is harmless.)* State the classification in the draft — don't ask.

### Step 4: Check for repo templates

```bash
gh api repos/OWNER/REPO/contents/.github/ISSUE_TEMPLATE --jq '.[].name' 2>/dev/null
```

If the repo has its own issue templates, use the most relevant one. Otherwise use the templates in [issue-templates.md](./references/issue-templates.md).

### Step 5: Draft the issue

Fill all sections from synthesized content. Present:

```
**Title:** <title>

**Body:**
<formatted issue body>

---
File this? (yes / edit / cancel)
```

One question only. If the user says "edit", wait for their next message with corrections, apply them, and re-present the draft — do not ask what to change. If the user says "cancel", stop without filing. Do not ask anything else.

### Step 6: File the issue

```bash
gh issue create --repo OWNER/REPO --title "TITLE" --body "BODY"
```

No labels, projects, or assignees.

Print the issue URL and suggest the next step:

```
Filed: https://github.com/OWNER/REPO/issues/N

Next: `crew spec OWNER/REPO#N`
```

## Rules

- **Session conversation is the primary source.** Never ask about content already present in the session.
- **One question maximum** — repo disambiguation only, and only when genuinely unresolvable from git context.
- **No gap-filling prompts.** If information is missing, omit the section or leave it thin.
- **No labels, projects, or assignees.** Title and body only.
- **Prefer repo templates** over built-in defaults when `.github/ISSUE_TEMPLATE/` exists.
- **Always use `--repo OWNER/REPO`** explicitly.
- **Pipeline handoff uses full reference**: `crew spec OWNER/REPO#N`, not just `#N`.

## Auto-clarity override

Drop to plain language before calling `gh issue create` — show the complete title, body, and target repo; GitHub issues are public and permanent. Resume after the URL is returned.
