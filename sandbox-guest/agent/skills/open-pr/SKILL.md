---
name: open-pr
description: Commit, push the feature branch, open a PR, and set the Linear issue to In Review — from the sandbox VM. Use when an issue's work is reviewed and ready. Shipping only — review with /review-changes first; it never merges or deploys (host-owned).
disable-model-invocation: true
---

Open a PR for the current branch. This is the shipping path — it assumes the diff was already reviewed with `review-changes`. If it hasn't, run that first.

Push **only the feature branch** and open a PR against the default branch. Never push to `main`, never merge, never deploy — those belong to the host agent.

## Current state
- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Unpushed commits: !`git log origin/HEAD..HEAD --oneline`
- Diff overview: !`git diff --stat HEAD`

## Steps

### 1. Infer the Linear issue
Derive the issue identifier from the branch name — the suffix after the last `-` (e.g. `buttons-and-links-edm-179` → `EDM-179`). Fetch the issue from Linear for the title and description.

### 2. Commit any uncommitted changes
Commit with a message referencing the Linear identifier (e.g. `Add contact buttons (EDM-179)`). If there's nothing to commit and nothing unpushed, stop and tell the user — there may be nothing to PR.

### 3. Push the feature branch
Confirm you're on the feature branch (not `main`), then push to `origin`, setting upstream if needed: `git push --set-upstream origin <branch>`.

### 4. Open the PR
Create it with `gh pr create` against the repo's default branch (find it with `git remote show origin | grep 'HEAD branch'`). The PR should:
- Have a concise title matching what was built (not the issue title verbatim)
- Reference the Linear issue URL in the body
- Summarise what changed and why, and note anything the reviewer should focus on

### 5. Set the Linear issue to In Review
Via the Linear MCP.

### 6. Report back
Share the PR URL.
