---
name: open-pr
description: Commit remaining changes, push, open a PR, and update the Linear issue status. Use when work on an issue is ready for review. Shipping only — review the diff with /review-changes first; this skill does not review.
disable-model-invocation: true
---

Open a PR for the current branch. This is the shipping path — it assumes the diff has already been reviewed with `/review-changes`. If it hasn't, run `/review-changes` first.

This opens a PR for the **current repo's** branch only — every step below reads the current working directory. If an issue's work spans multiple repos/branches (e.g. app code plus a skill change in the `agents` repo), run this once from each repo.

## Current state
- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Unpushed commits: !`git log origin/HEAD..HEAD --oneline`
- Diff: !`git diff HEAD`

## Steps

### 1. Infer the Linear issue
Derive the issue identifier from the branch name — it's the suffix after the last `-` (e.g. `buttons-and-links-edm-179` → `EDM-179`). Fetch the issue from Linear to get the title and description.

### 2. Commit any uncommitted changes
If there are uncommitted changes, commit them. The commit message must reference the Linear issue identifier (e.g. `Add contact buttons (EDM-179)`).

If there's nothing to commit and nothing unpushed, stop and tell the user — there may be nothing to PR.

### 3. Push to origin
Push the branch to `origin`. If the branch has no upstream yet, set it with `--set-upstream`.

### 4. Open the PR
Create a PR with `gh pr create`. The PR should:
- Have a concise title that matches what was built (not just the issue title verbatim)
- Reference the Linear issue URL in the body
- Include a brief summary of what changed and why
- Note anything the reviewer should pay attention to, if relevant

Target branch is the repo's default branch (use `git remote show origin | grep 'HEAD branch'` to determine it).

### 5. Update the Linear issue status
Mark the Linear issue as "In Review".

### 6. Report back
Share the PR URL with the user.
