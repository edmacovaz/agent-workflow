---
name: start-work
description: The gate between planning and coding an already-planned Linear issue in the sandbox VM — clone the repo if needed, cut the issue's branch off latest main, and prepare it. Use when picking up an issue to code here. Not for planning or roadmap (host-only), and not for opening the PR — that's open-pr.
disable-model-invocation: true
---

Start work on Linear issue: $ARGUMENTS

The issue is already planned — planning happens on the host. This skill is the gate between that plan and coding: it gets the repo and branch ready in this VM, then hands off to implementation. Everything runs inside the sandbox and every clone is disposable, so there is no "wrong checkout" to protect.

## Current state
- Dir: !`pwd`
- Repo: !`git rev-parse --show-toplevel 2>/dev/null || echo "(not in a repo — clone it in step 2)"`
- Branch: !`git branch --show-current 2>/dev/null`
- Status: !`git status --short 2>/dev/null`

## Steps

### 1. Fetch the issue
Use the Linear MCP to fetch the issue by ID (from $ARGUMENTS). Read the description and `## Plan` — this is the spec. Extract the title, `gitBranchName` (Linear's canonical branch name — the branch you cut must match it exactly for PR auto-linking), the current status, and which repository it targets.

### 2. Ensure the repo is here
This VM has no host filesystem, so the repo has to be cloned in. If the target repo isn't already present (see Current state), clone it with `gh repo clone <owner>/<repo>` and `cd` into it. If the issue doesn't make the repo obvious and $ARGUMENTS doesn't name it, stop and ask rather than guessing.

### 3. Cut the issue's branch off latest main
Cut from an up-to-date base, named exactly Linear's `gitBranchName`:

```
git fetch origin
git switch -c <gitBranchName> origin/<default-branch>
```

If the branch already exists (you're resuming), switch to it instead. If uncommitted changes block the switch, stop and ask.

### 4. Prepare the repo
Run the install and env/secrets steps the project's AGENTS.md specifies (e.g. `npm install` / `pnpm install`). Skip only if the project needs none.

### 5. Get your bearings
A quick lay of the land, not deep analysis: skim AGENTS.md / README and locate the area the issue touches. The read-before-forming-a-view research already happened during planning — don't redo it.

### 6. Mark the issue In Progress
Move the Linear issue to its started state via the Linear MCP (skip if already there).

### 7. Hand off
The branch is live and the repo is prepared. Implement per the plan on the issue, then review with `review-changes`.
