---
name: crew-create-issue
description: "Structure a rough idea into a well-formed GitHub issue and file it. Trigger: 'crew create issue' or 'crew create issue: <description>'."
---

# Create Issue

Synthesize the issue from the current session conversation. Do not ask questions to fill gaps.

## Mode

Scan the conversation for an explicit issue reference (URL or bare `#N`). If found, **update** that issue. Otherwise, **create** a new one. If ambiguous, confirm in one line: `"Fill out existing #N, or open a new issue?"`

## Target repo

```bash
git remote get-url origin 2>/dev/null \
  | sed 's|.*github\.com[:/]\(.*\)\.git|\1|; s|.*github\.com[:/]\(.*\)|\1|'
```

If that returns `OWNER/REPO`, use it. If a repo is mentioned in the conversation (via URL or `org/repo`), use that. If genuinely unresolvable, ask exactly one question: **"Which repo? (OWNER/REPO)"**

## Format

Classify as **bug** or **feature** per Template Selection in [issue-templates.md](./references/issue-templates.md); default to Default (feature) when ambiguous. Check for repo templates first:

```bash
GH_PAGER=cat gh api repos/OWNER/REPO/contents/.github/ISSUE_TEMPLATE --jq '.[].name' 2>/dev/null
```

If the repo has its own templates, use the most relevant one.

## Auth (only when a project URL is in the conversation)

Check scopes before any project work:

```bash
gh auth status 2>&1 | grep -i "token scopes"
```

If `read:project` or `project` is missing, prompt once:

```
Run: gh auth refresh -h github.com -s read:project,project
Then complete device auth at https://github.com/login/device
```

Continue writing the issue body while waiting. Never hit a scope error mid-session.

## Commands

**Create:**
```bash
GH_PAGER=cat gh issue create --repo OWNER/REPO --title "TITLE" --body "BODY"
```

**Update (fetch existing body first, then merge with session content):**
```bash
GH_PAGER=cat gh issue view N --repo OWNER/REPO --json title,body
GH_PAGER=cat gh issue edit N --repo OWNER/REPO --body "NEW_BODY"
```

**Add to project + set Status (optional — only when project URL is in conversation):**
```bash
GH_PAGER=cat gh project item-add PROJECT_NUMBER --owner OWNER --url ISSUE_URL

# Get item ID and Status field options, then:
GH_PAGER=cat gh project item-edit \
  --project-id PROJECT_ID --id ITEM_ID \
  --field-id FIELD_ID --single-select-option-id OPTION_ID
```

Status inference: **"In Review"** for open PRs · **"Ready"** for merged · **"In Progress"** for active work.

## Draft and confirm

Show the complete title, body, and target repo before filing. One question: `File this? (yes / edit / cancel)`. If "edit", apply their corrections and re-present — do not ask what to change.

## After filing

```
Filed/Updated: https://github.com/OWNER/REPO/issues/N
```

- **Create mode** → `Next: crew spec OWNER/REPO#N`
- **Update mode** → suggest next step based on context (implement, review, or done)
