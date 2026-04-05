---
name: open-pr
description: Commit remaining changes, push, open a PR, and update the Linear issue status. Use when work on an issue is ready for review.
---

Open a PR for the current branch.

## Current state
- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Unpushed commits: !`git log origin/master..HEAD --oneline`
- Diff: !`git diff HEAD`

## Steps

### 1. Infer the Linear issue
Derive the issue identifier from the branch name — it's the suffix after the last `-` (e.g. `buttons-and-links-edm-179` → `EDM-179`). Fetch the issue from Linear to get the title and description.

### 2. Commit any uncommitted changes
If there are uncommitted changes, commit them. The commit message must reference the Linear issue identifier (e.g. `Add contact buttons (EDM-179)`).

If there's nothing to commit and nothing unpushed, stop and tell the user — there may be nothing to PR.

### 3. Push to origin
Push the branch to `origin`. If the branch has no upstream yet, set it with `--set-upstream`.

### 4. Review and clean up
Before opening the PR, review the full diff (`git diff origin/master..HEAD`) and check:

**Code quality** — anything left rough, commented out, or that could be cleaner before a reviewer sees it.

**Instructions** — read AGENTS.md in full. For each section, check whether the diff invalidates anything: Stack (new tools, removed tools), Development commands (package manager, script names), Workflow, Key Decisions. Do the same spot-check for `~/.claude/CLAUDE.md` (tooling conventions, CLI paths, worktree setup). If anything is stale, update it and include the changes in this commit.

**Skills** — did this work surface a pattern, workflow step, or hard-won lesson that would be worth encoding as a user-level skill (`~/.claude/skills/`) or project skill (`.claude/skills/`)? If so, create or update the skill now.

If you make any changes in this step, commit them before pushing.

### 5. Open the PR
Create a PR with `gh pr create`. The PR should:
- Have a concise title that matches what was built (not just the issue title verbatim)
- Reference the Linear issue URL in the body
- Include a brief summary of what changed and why
- Note anything the reviewer should pay attention to, if relevant

Target branch is `master`.

### 6. Update the Linear issue status
Mark the Linear issue as "In Review".

### 7. Report back
Share the PR URL with the user.
