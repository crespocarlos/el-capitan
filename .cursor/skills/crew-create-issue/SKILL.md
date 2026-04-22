---
name: crew-create-issue
description: "Structure a rough idea into a well-formed GitHub issue and file it. Trigger: 'crew create issue' or 'crew create issue: <description>'."
---

# Create Issue

## When Invoked

### Step 0: Handle bare trigger

If the user said only `crew create issue` with no description, ask: **"What's the issue? Describe the problem or feature you have in mind."** Wait for their response, then continue to Step 1.

If the trigger includes a description (`crew create issue: <description>`), proceed directly to Step 1 with that description.

### Step 1: Identify the target repo

Ask: **"Which repo should this be filed in?"** Accept `OWNER/REPO` format. If the user gives a short name, resolve it with `gh repo view REPO --json nameWithOwner --jq '.nameWithOwner'`.

### Step 2: Auto-classify issue type

Read the user's description and classify as **bug** or **feature**:

- Bug: something broken, an error, unexpected behavior, regression, crash
- Feature: something new — a capability, workflow, integration, enhancement

Default to **bug** if ambiguous. Tell the user the classification: _"This reads as a **bug** (or **feature**). I'll use the bug/feature template."_

### Step 3: Check for repo templates

```bash
gh api repos/OWNER/REPO/contents/.github/ISSUE_TEMPLATE --jq '.[].name' 2>/dev/null
```

If the repo has its own issue templates, read and use the most relevant one instead of the defaults. Otherwise, use the templates in [issue-templates.md](./references/issue-templates.md).

### Step 4: Draft the issue

Structure the user's description into the selected template. Fill in every section you can from the information provided.

**Gap-filling questions** — check what's missing and ask only about gaps. Frame each question in terms of what crew-specwriter will need downstream:

- **Problem statement** missing → "crew-specwriter will need a clear problem statement for the spec's Context section. Can you describe what's going wrong / what need this addresses?"
- **Reproduction steps** missing (bugs only) → "To write a good spec, we'll need repro steps. How do you trigger this?"
- **Affected files/endpoints/UI paths** missing → "crew-specwriter maps these to repo touchpoints. Do you know which files, endpoints, or UI areas are involved?"
- **Acceptance criteria** missing → "The spec needs testable requirements. What does 'done' look like?"
- **Scope boundaries** missing → "crew-specwriter uses scope boundaries for non-regression criteria. Anything explicitly out of scope?"
- **Evidence** missing (bugs only) → "Error logs, API responses, or screenshots help crew-specwriter understand the failure. Do you have any?"

Only ask about information that is actually missing — skip questions the user's description already answers.

Present the draft:

```
**Title:** <title>

**Body:**
<formatted issue body>
```

Then ask: **"Want to change anything, or should I file it?"**

### Step 5: File the issue

After the user approves, create the issue:

```bash
gh issue create --repo OWNER/REPO --title "TITLE" --body "BODY"
```

No labels, projects, or assignees — title and body only.

### Step 6: Suggest next step

Print the issue URL and suggest the next pipeline step:

```
Filed: https://github.com/OWNER/REPO/issues/N

Next: `crew spec OWNER/REPO#N`
```

## Rules

- **2 turns only**: draft (Step 4) + confirm (Step 5). Step 0 is a pre-turn for bare triggers.
- **No labels, projects, or assignees.** Only title and body.
- **Prefer repo templates.** If `.github/ISSUE_TEMPLATE/` exists in the target repo, use those templates instead of the built-in defaults.
- **Always use `--repo OWNER/REPO`** explicitly — never assume the current repo.
- **Default to bug** when the classification is unclear.
- **Gap-filling is selective.** Don't ask about information the user already provided. Frame missing-info questions around what crew-specwriter needs.
- **Pipeline handoff uses full reference**: `crew spec OWNER/REPO#N`, not just `#N`.
- **No SESSION.md logging.**

## Auto-clarity override

Drop to plain language before:

- Calling `gh issue create` — show the complete title, body, and target repo in plain language; GitHub issues are public and permanent
- Any label or milestone assignment — confirm these are intentional, not inferred defaults

Resume compressed mode after the issue URL is returned.
