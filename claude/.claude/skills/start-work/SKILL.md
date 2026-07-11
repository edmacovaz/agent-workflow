---
name: start-work
description: The gate between planning and coding a Linear issue — cut its branch off latest main and set up the worktree. Use after /plan, from inside the worktree you created in Zed, when you're ready to start changes. Not for planning — that's /plan.
disable-model-invocation: true
---

Start work on Linear issue: $ARGUMENTS

Run this **inside the worktree you created in Zed's picker**, after `/plan` has agreed a plan on the issue. This skill is the gate between planning and coding: `/plan` ran read-only against the latest `main`; `start-work` now cuts the issue's branch and prepares the worktree, then hands off to coding. It does **not** create worktrees — you make those in Zed.

## Current state
- Toplevel: !`git rev-parse --show-toplevel`
- Branch: !`git branch --show-current`
- Worktrees: !`git worktree list`
- Status: !`git status --short`

## Steps

### 1. Fetch the issue
Use the Linear MCP to fetch the issue by ID (from $ARGUMENTS, or infer from the context). Extract the title, description, `gitBranchName` (Linear's canonical branch name — the branch you cut must match it exactly for PR auto-linking), and current status.

### 2. Confirm you're in a dedicated worktree, not the main checkout
This skill cuts a branch, so it must run in the Zed worktree for this issue — never the primary checkout. In `git worktree list`, the first entry is the primary checkout; if the current toplevel is that one (or you're sitting on the default branch with no dedicated worktree), **stop** and tell the user to create a worktree in Zed's picker and open it, then re-run. Don't cut the branch in the main checkout.

Quick fit check while here: does the issue's work primarily involve this repo (compare it to `git remote get-url origin`)? If it belongs elsewhere, or you're unsure, stop and ask — don't touch git.

### 3. Cut the issue's branch off latest main
`/plan` looked at the latest `main`; now cut the branch from an up-to-date base, named exactly Linear's `gitBranchName`:

```
git fetch origin
git switch -c <gitBranchName> origin/<default-branch>
```

Zed's generated worktree *name* stays as-is — only the branch follows Linear's naming. If the branch already exists (you're resuming), switch to it instead (`git switch <gitBranchName>`). If uncommitted changes block the switch, stop and ask rather than forcing it.

### 4. Prepare the worktree
A fresh worktree shares no `node_modules` or secrets setup with the main checkout. Run the install **and env/secrets** steps the project's AGENTS.md specifies (e.g. `npm install` / `pnpm install`, then a secrets-manager `setup`/login so secret-backed commands resolve). Skip only if the project needs none.

### 5. Get your bearings
A quick lay of the land, not deep analysis: skim AGENTS.md / README and locate the area the issue touches. The real read-before-forming-a-view research already happened in `/plan` — don't re-do it here.

### 6. Mark the issue In Progress
Move the Linear issue to its started state via the Linear MCP (skip if already there). Only after step 2 confirmed the issue belongs here — never flip the status of an issue you've bounced back to the user.

### 7. Hand off
The branch is live and the worktree is set up. Start implementing per the plan recorded on the issue. (No Zed "Add Folders" step — you created the worktree in Zed, so it's already open there.)
