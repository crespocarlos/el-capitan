---
disable-model-invocation: true
name: crew-create-issue
description: "Structure a rough idea into a well-formed GitHub issue and file it. Trigger: 'crew create issue' or 'crew create issue: <description>'."
---

# Create Issue

Synthesize the issue from the current session conversation. Do not ask questions to fill gaps.

**This skill produces GitHub issues, not design docs or specs.** Session analysis (tables, numbered problem lists, Option A/B proposals) must be **restructured** into the template sections — never pasted as freeform top-level headings.

## When Invoked

### Step 1: Mode and target repo

Scan the conversation for an explicit issue reference (URL or bare `#N`). If found, **update** that issue. Otherwise, **create** a new one. If ambiguous, confirm in one line: `"Fill out existing #N, or open a new issue?"`

```bash
git remote get-url origin 2>/dev/null \
  | sed 's|.*github\.com[:/]\(.*\)\.git|\1|; s|.*github\.com[:/]\(.*\)|\1|'
```

If that returns `OWNER/REPO`, use it. If a repo is mentioned in the conversation (via URL or `org/repo`), use that. If genuinely unresolvable, ask exactly one question: **"Which repo? (OWNER/REPO)"**

### Step 2: Load the template (mandatory)

**Read** [issue-templates.md](./references/issue-templates.md) before drafting. Do not rely on memory.

Check for repo-native templates:

```bash
GH_PAGER=cat gh api repos/OWNER/REPO/contents/.github/ISSUE_TEMPLATE --jq '.[].name' 2>/dev/null
```

- If templates exist → read the most relevant one and use its sections.
- If the command 404s or returns nothing → use the fallback templates in `issue-templates.md`.

Classify as **bug** or **feature** per Template Selection in `issue-templates.md`; default to Default (feature) when ambiguous.

### Step 3: Draft title, body, and labels

**Title** — follow [Title conventions](./references/issue-templates.md#title-conventions) in `issue-templates.md`. Infer prefix/style from recent issues in the target repo; do not hardcode org- or workstream-specific patterns.

**Body** — use **only** the section headings from the chosen template, with emoji headers exactly as written (`## 📓 Summary`, `## ✔️ Acceptance criteria`, etc.). Map session content into these sections:

| Session material | Goes in |
|---|---|
| Problem statement, context, why it matters | `## 📓 Summary` (1–2 paragraphs) |
| What "done" looks like — outcomes, not implementation steps | `## ✔️ Acceptance criteria` (checkbox bullets) |
| File paths, risky areas, merge order, approach notes | `## 💡 Implementation hints` (grouped by area) |
| Repro steps, logs (bugs only) | Bug template sections |

**Do not add** top-level sections such as `## Domain hierarchy`, `## Issues`, `## Proposed fix`, or `## Options`. Fold that content into Summary, Acceptance criteria, or Implementation hints.

**Labels** — infer from content using [Label conventions](./references/issue-templates.md#label-conventions) in `issue-templates.md`. List available labels with `gh label list --repo OWNER/REPO` when unsure.

### Step 4: Self-check before presenting

Reject and rewrite the draft if any of these fail:

- [ ] Body uses exact template section headings (emoji included)
- [ ] No extra top-level `##` sections beyond the template
- [ ] Acceptance criteria are observable outcomes, not "update file X"
- [ ] Title matches repo convention

### Step 5: Draft and confirm

Show the complete **title**, **body**, **target repo**, and **labels** before filing. One question: `File this? (yes / edit / cancel)`. If "edit", apply their corrections and re-present — do not ask what to change.

### Step 6: File

**Auth (only when a project URL is in the conversation):**

```bash
gh auth status 2>&1 | grep -i "token scopes"
```

If `read:project` or `project` is missing, prompt once:

```
Run: gh auth refresh -h github.com -s read:project,project
Then complete device auth at https://github.com/login/device
```

Continue writing the issue body while waiting. Never hit a scope error mid-session.

**Create:**

```bash
GH_PAGER=cat gh issue create --repo OWNER/REPO --title "TITLE" --body "$(cat <<'EOF'
BODY
EOF
)" --label "label1" --label "label2"
```

Omit `--label` flags when no label applies.

**Update** (fetch existing body first, then merge with session content):

```bash
GH_PAGER=cat gh issue view N --repo OWNER/REPO --json title,body
GH_PAGER=cat gh issue edit N --repo OWNER/REPO --body "$(cat <<'EOF'
NEW_BODY
EOF
)"
```

**Add to project + set Status (optional — only when project URL is in conversation):**

```bash
GH_PAGER=cat gh project item-add PROJECT_NUMBER --owner OWNER --url ISSUE_URL

GH_PAGER=cat gh project item-edit \
  --project-id PROJECT_ID --id ITEM_ID \
  --field-id FIELD_ID --single-select-option-id OPTION_ID
```

Status inference: **"In Review"** for open PRs · **"Ready"** for merged · **"In Progress"** for active work.

### Step 7: After filing

```
Filed/Updated: https://github.com/OWNER/REPO/issues/N
```

- **Create mode** → `Next: crew spec OWNER/REPO#N`
- **Update mode** → suggest next step based on context (implement, review, or done)

## Invariants

- Read `issue-templates.md` every invocation — never draft from memory
- Output shape matches the template, not the shape of the conversation
- Confirm before `gh issue create` — never file without `yes`
- This skill does **not** explore the codebase; depth belongs in `crew spec`
