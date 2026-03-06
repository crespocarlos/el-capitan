# PR Review Commands

Reference commands for each review step. Replace `OWNER/REPO`, `NUMBER` with actual values.

## Step 1: Fetch PR Metadata

```bash
# Full PR metadata
gh pr view NUMBER --repo OWNER/REPO --json title,body,labels,baseRefName,headRefName,additions,deletions,changedFiles,comments,reviews

# Linked issue (if referenced in PR body)
gh issue view ISSUE_NUMBER --repo OWNER/REPO --json title,body,labels
```

## Step 2: Fetch the Diff

```bash
# Full diff
gh pr diff NUMBER --repo OWNER/REPO
```

### Large diffs (>500 lines changed)

Don't read the entire diff at once. Triage by file first:

```bash
# File-level summary — which files changed and by how much
gh pr view NUMBER --repo OWNER/REPO --json files --jq '.files[] | "\(.additions)+\(.deletions) \(.path)"' | sort -rn

# Diff for a single file
gh pr diff NUMBER --repo OWNER/REPO -- path/to/file.ts

# Only show changed function signatures (TypeScript/JavaScript)
gh pr diff NUMBER --repo OWNER/REPO | grep -E '^[+-].*(export |function |class |interface |type )' | head -30
```

### Very large diffs (>1500 lines)

Identify the spine first — don't try to review everything:

```bash
# New files (likely the main feature)
gh pr view NUMBER --repo OWNER/REPO --json files --jq '[.files[] | select(.status == "added")] | map(.path)'

# Most-changed files (likely the key decisions)
gh pr view NUMBER --repo OWNER/REPO --json files --jq '.files | sort_by(-.additions) | .[0:5] | map(.path)'

# Test files (review separately)
gh pr view NUMBER --repo OWNER/REPO --json files --jq '[.files[] | select(.path | test("test|spec|__tests__"))] | map(.path)'
```

## Step 4: Find Consumers

For changed exports, public functions, or type definitions — find who uses them:

```bash
# Find imports of a changed module
rg "from ['\"].*module_name" --type ts --type tsx -l

# Find call sites of a changed function
rg "functionName\(" --type ts --type tsx -l

# Find type usage
rg "TypeName" --type ts --type tsx -l

# Find interface implementations
rg "implements InterfaceName" --type ts -l
```

### If the repo is not checked out locally

```bash
# Search via GitHub API (less precise but works remotely)
gh api search/code -f q="functionName repo:OWNER/REPO" --jq '.items[].path' | head -20
```

## Step 5: Verify Tests

```bash
# List test files changed in the PR
gh pr view NUMBER --repo OWNER/REPO --json files --jq '[.files[] | select(.path | test("test|spec|__tests__"))] | map(.path)'

# Check if a changed source file has a corresponding test file
# For path/to/module.ts, look for:
#   path/to/module.test.ts
#   path/to/__tests__/module.test.ts
#   path/to/module.spec.ts

# Diff of test files only
gh pr diff NUMBER --repo OWNER/REPO -- '*.test.ts' '*.test.tsx' '*.spec.ts' '*.spec.tsx'
```

## Step 6: Check Project Conventions

```bash
# Look for contributing guides
ls AGENTS.md CLAUDE.md .claude/CLAUDE.md CONTRIBUTING.md .github/CONTRIBUTING.md 2>/dev/null

# Check if there's a linter config
ls .eslintrc* .prettierrc* tsconfig.json biome.json 2>/dev/null
```

## Existing Review Comments

```bash
# Read existing review comments (don't duplicate them)
gh api repos/OWNER/REPO/pulls/NUMBER/comments --jq '.[] | {path, line: .original_line, body: .body[0:200], author: .user.login}' | head -50
```
