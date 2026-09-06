---
name: start-work
description: The gate between planning and coding a Linear issue — verify the worktree Orca already created, bring its base up to date, and prepare it. Use after /plan, when you're ready to start changes. Not for planning — that's /plan. Never creates worktrees, never cuts or renames a branch.
disable-model-invocation: true
---

Start work on Linear issue: $ARGUMENTS

Run this after `/plan` has agreed a plan on the issue. `/plan` ran read-only; `start-work` confirms where you are, brings the base up to date, prepares the environment, and hands off to coding.

**Orca owns placement.** The worktree and its branch already exist — Orca created them. This skill verifies and prepares what is there. It never runs `orca worktree create`, never cuts a branch, and never renames Orca's branch.

## Current state
- Orca: !`orca worktree current --json 2>/dev/null || echo '{"ok":false}'`
- Toplevel: !`git rev-parse --show-toplevel`
- Branch: !`git branch --show-current`
- Worktrees: !`git worktree list`
- Status: !`git status --short`

## Steps

A step may not cite another step as its condition — the reduced path below skips steps, and a step citing a skipped one can never run. Each step states its own condition instead. The section that defines the reduced path names steps freely; it cannot say which it skips otherwise.

### 1. Read the issue
Fetch the issue by identifier (from $ARGUMENTS, or ask) via the Linear MCP. Take its title, description, and current status. The plan agreed in `/plan` is on the description — read it; it is what you are about to build.

### 2. Establish placement
Orca is the authority. From the record above, take `path`, `branch`, `baseRef`, `displayName`, `isMainWorktree`, and `linkedLinearIssue`.

`orca worktree current` resolves the directory you are in, so its `path` should equal `git rev-parse --show-toplevel`. Where the two differ, say so and stop — something is nested or symlinked in a way that makes the rest of this skill's reasoning unsound.

If there is no Orca record, fall back to git's own view (`git rev-parse --show-toplevel`, `git branch --show-current`, `git worktree list`).

**Resolve the base ref here and call it `<base>` from now on.** Orca's `baseRef` where there is a record; otherwise `git symbolic-ref refs/remotes/origin/HEAD`. Where neither answers, stop and ask rather than guessing `origin/main` — the default branch is not always called that.

**Say which authority answered.** Every later step reads placement, so a silent fallback hides why the skill did what it did.

### 3. Read the repo's worktree policy
Read AGENTS.md for any statement of where work happens in this repo — for example, that it is worked on `main` in the main checkout. `## How work happens here` is the conventional section for it; look there first, but a policy stated elsewhere in AGENTS.md still counts.

Where AGENTS.md states no policy, or there is no AGENTS.md, the default applies: **work happens in the Orca worktree for the issue, on the branch Orca created.** Say which of the two you are following.

### 4. Confirm this worktree is for this issue
The worktree matches when `linkedLinearIssue` names the issue, or the identifier appears in the branch name or `displayName`.

**A `linkedLinearIssue` naming a different issue is a mismatch**, whatever the branch says — a link is a deliberate record and outranks a name that merely looks right. Where the link is stale rather than wrong, say so and name the remedy: clear or update it with `orca worktree set --worktree current --linear-issue <ID>`.

On any mismatch — a different issue's worktree, or the wrong repo (compare against `git remote get-url origin`) — **stop and report.** Change nothing in git, and do not move the issue's status. Adopting someone else's worktree is worse than bouncing.

**Separately, whenever the branch name does not contain the identifier**, say so and name the remedies: recreate the worktree under the issue's identifier, or carry the identifier on the PR. This is reported even when the match succeeded by link or display name. Linear links a PR by the identifier appearing in the branch name, the PR title, or a magic word plus identifier in the PR body. So a branch without the identifier means the PR will be unlinked *unless* it carries the identifier itself — which is what the second remedy is for. Do not rename the branch to fix this; Orca's record stores the branch name and has no way to follow a rename.

### 5. Bring the base up to date
```
git fetch origin
git rev-list --count HEAD..<base>
git status --porcelain
git merge --ff-only <base>
```

**Always report the drift** — how far behind `<base>` this branch is. `/plan` read the code as it stood; the branch was cut whenever Orca created it, which may be much earlier.

**Two separate guards, each doing its own job.** `--ff-only` refuses where the branch carries commits of its own, so the advance can never rewrite history or leave a merge commit. It does **not** protect the working tree: with uncommitted changes to files the incoming commits don't touch, a fast-forward succeeds and moves `HEAD` underneath them. So `git status --porcelain` must come back empty before the merge runs — that is what refuses on a dirty tree.

Where either guard refuses, report the drift and stop. Do not reach for a rebase or a plain merge instead: rebasing over work in progress is git surgery nobody asked for, and a merge commit dies in the eventual squash.

### 6. Bind the worktree to the issue
```
orca worktree set --worktree current --linear-issue <ID>
```

This makes the worktree-to-issue link a record rather than something every later step re-derives from a branch name, and it is what `orca linear issue --current` resolves. Skip it where placement fell back to git — with no Orca record there is nothing to bind.

Do not set `--workspace-status`: Linear already holds the issue's status, and a second copy only drifts.

### 7. Prepare the environment
Run the install **and env/secrets** steps the project's AGENTS.md specifies (e.g. `npm install` / `pnpm install`, then a secrets-manager `setup`/login so secret-backed commands resolve). Skip only where the project needs none.

In a worktree this is required rather than optional: `node_modules` and secrets setup are not shared with the main checkout. In the main checkout, run whatever AGENTS.md asks for and expect most of it to be in place already.

### 8. Get your bearings
A quick lay of the land, not deep analysis: skim AGENTS.md / README and locate the area the issue touches. The read-before-forming-a-view research already happened in `/plan` — don't re-do it here.

### 9. Mark the issue In Progress
Move the issue to its started state via the Linear MCP (skip where it is already there).

**Only where placement was confirmed** — either this worktree was confirmed to be the issue's, or the repo's policy says no worktree is expected. Never flip the status of an issue you have bounced back to the user.

### 10. Hand off
Report where you are, which authority said so, and what the base drift was. Start implementing per the plan recorded on the issue.

## Repos worked on `main`

Where AGENTS.md declares that the repo is worked on `main` in the main checkout, there is no branch and no worktree to verify. Skip steps 4, 5 and 6; run the rest as written. Step 9 still moves the status — the policy read in step 3 is what confirms placement here.

Where AGENTS.md declares that policy **but Orca reports `isMainWorktree: false`**, the two disagree: the repo says work happens in the main checkout and the session is in a worktree. Stop and ask which to follow — do not pick one silently. A repo that states this policy generally also states what to do about it; follow what it says.
