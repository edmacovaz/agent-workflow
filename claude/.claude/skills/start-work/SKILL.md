---
name: start-work
description: Set up to work on a Linear issue before any planning or coding — sync git and create its worktree. Use when picking up or resuming an issue; stops at a clean worktree, ready for /plan. Not for planning or writing code — that's /plan.
disable-model-invocation: true
---

Set up to work on Linear issue: $ARGUMENTS

## Current state
- Branch: !`git branch --show-current`
- Worktrees: !`git worktree list`
- Status: !`git status --short`

## Steps

### 1. Fetch the issue
Use the Linear MCP tool to fetch the issue by ID (e.g. EDM-179). Extract:
- Title, description, and any linked documents or attachments
- `gitBranchName` (format: `{title-slug}-{identifier}`)
- Current status

### 2. Assess context fit
Before touching git, determine whether this issue belongs to the current repo.

Use the issue description and the current repo's remote URL (`git remote get-url origin`) to judge. An issue belongs here if the work primarily involves files in this repository. It doesn't belong here if the work is in a different repo, or involves no repo at all (system setup, shell config, machine-level tasks).

If it doesn't belong, or you're unsure, stop and tell the user — explain what you found and ask how they'd like to proceed. Do not create worktrees, rename branches, or touch git.

### 3. Find or create the worktree
Each issue gets its own git worktree under `.claude/worktrees/<gitBranchName>` — the worktree-per-issue convention in `~/.claude/CLAUDE.md` (and AGENTS.md where present). Do **not** do a plain branch checkout in the current worktree.

- Check `git worktree list` for an existing worktree for this issue. If one exists, switch into it (`EnterWorktree` with its `path`) and skip creation — that's where the work lives.
- Otherwise create one with the `EnterWorktree` tool (`name: <gitBranchName>`). It branches off the latest `origin/<default-branch>` and switches the session into the new worktree. The tool prefixes the branch with `worktree-`, so immediately `git branch -m <gitBranchName>` to match Linear's `gitBranchName` (needed for PR auto-linking).
- If the worktree can't be created or the branch can't be checked out, stop and tell the user before proceeding.

### 4. Prepare the worktree
A fresh worktree doesn't share `node_modules` or other build artefacts with the main checkout. Run whatever install **and env/secrets** setup steps the project's AGENTS.md specifies before tooling will work (e.g. `pnpm install`; a secrets-manager `setup`/login so secret-backed commands resolve). Skip if the project needs none.

### 5. Get your bearings
Take a quick lay of the land so the worktree is oriented, not deeply analysed: read AGENTS.md / README, and locate the area the issue touches. Leave the real read-before-forming-a-view research to `/plan` — don't start designing here.

### 6. Mark the issue In Progress
Now that setup has succeeded, move the Linear issue to "In Progress" (the started state) via the Linear MCP — work has begun. Skip if it's already there. Do this only after step 2 confirmed the issue belongs here; never flip the status of an issue you've bounced back to the user.

### 7. Hand off
The new worktree won't appear in Zed's "Open Worktrees" picker (Zed only lists ones created through its own UI). Tell the user to add it via **Add Folders to Project** if they want it open there — this is the part that can't be automated mid-flow.

Then stop. Setup is done. Point the user to run `/plan` to turn the issue into an agreed plan. Do not plan or write code in this skill.
