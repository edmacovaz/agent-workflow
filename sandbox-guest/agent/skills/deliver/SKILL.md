---
name: deliver
description: Take an already-planned Linear issue all the way to a finished PR in the sandbox VM — assess the plan against the current state, implement the gap, simplify, open the PR, then adversarially review it and post the review and fixes as PR comments. Use to deliver a planned issue end to end. Not for planning or roadmap (host-only), and never merges or deploys (host-owned).
disable-model-invocation: true
---

Deliver Linear issue: $ARGUMENTS

One command takes a **planned** issue to a finished PR that carries its own review trail. Every hard stop happens **before** the PR opens — a missing plan, work that contradicts the plan, or a surprise you can't resolve within it. Once the PR is open, everything is a comment: a review, the fixes, and any open questions. Everything runs in the disposable sandbox, so there's no "wrong checkout" to protect.

## Current state
- Dir: !`pwd`
- Repo: !`git rev-parse --show-toplevel 2>/dev/null || echo "(not in a repo — clone it in step 2)"`
- Branch: !`git branch --show-current 2>/dev/null`
- Status: !`git status --short 2>/dev/null`

## Steps

### 1. Fetch the issue and gate on the plan
Use the Linear MCP to fetch the issue by ID (from $ARGUMENTS). Read the description and `## Plan` — this is the spec. **If the plan is missing, or has gaps you'd have to guess at to implement, stop and ask — never invent a plan.** Extract the title, `gitBranchName` (Linear's canonical branch name — the branch you cut must match it exactly for PR auto-linking), the current status, and which repository it targets.

### 2. Get the repo and branch ready
This VM has no host filesystem, so the repo has to be cloned in. If the target repo isn't already present (see Current state), clone it with `gh repo clone <owner>/<repo>` and `cd` into it. If the issue doesn't make the repo obvious and $ARGUMENTS doesn't name it, stop and ask rather than guessing.

Cut the issue's branch off an up-to-date base, named exactly Linear's `gitBranchName`:

```
git fetch origin
git switch -c <gitBranchName> origin/<default-branch>
```

If the branch already exists (you're resuming), switch to it instead. Then run the install and env/secrets steps the project's AGENTS.md specifies (e.g. `npm install` / `pnpm install`). Mark the issue **In Progress** via the Linear MCP (skip if already there).

### 3. Assess what's left to do
Compare the plan against the current branch state (`git diff` / `git log` vs the branch point):
- **Nothing implemented** → build the whole thing.
- **Partial work that follows the plan** → continue from where it is.
- **Work that contradicts the plan** → **stop and check in.** Don't paper over it.

### 4. Implement the gap
Code per the plan. When you hit something the plan didn't foresee: if you can resolve it **without violating the plan or the project's principles** (AGENTS.md), resolve it and add it to a running **deviations-handled** list for the PR body. If you can't resolve it within those bounds, **stop and ask**. Keep implementing until the plan is delivered.

### 5. Simplify
Run `/simplify` to fold in reuse/simplification/efficiency cleanups before the work is shown. Quality only — it doesn't hunt bugs; the review does that.

### 6. Open the PR
This is the last step before review — after it, everything is a PR comment.

Commit with an imperative summary + the Linear identifier (e.g. `Add contact buttons (EDM-179)`). Push the **feature branch only** (`git push --set-upstream origin <branch>`) — never push `main`, never merge, never deploy. Open the PR with `gh pr create` against the repo's default branch. The body should summarise what changed and why, and list the **deviations-handled** from step 4. Set the Linear issue to **In Review** via the MCP.

### 7. Adversarial review (fresh-context subagent)
Launch a subagent that did **not** write the code, so it reads the diff cold rather than rubber-stamping it. Give it only the diff, the issue + plan, and the project's AGENTS.md, and have it **report only — no edits**. It produces one consolidated report covering:

- **Intent / completeness / scope** — does the diff deliver what the plan asked, nothing missing, nothing extra that should be split out?
- **AGENTS.md conformance + production readiness** — stale instructions, test-strategy fit; for anything touching schema/infra/secrets/deployed contracts, flag what prod still needs **for the host agent** (merge/deploy is host-owned).
- **`/code-review`** run report-only inside the subagent — correctness bugs and reuse/simplification/efficiency cleanups, folded into the report.
- **Documentation & context boy-scouting** — stale AGENTS.md/README sections and outdated comments this change touches, proposed as concrete fixes. Leave the campsite cleaner than you found it.

Post the consolidated report as a **single review comment** on the PR (`gh pr comment`).

### 8. Apply the fixes
Apply the findings worth acting on — **code and doc boy-scout fixes**. Commit and push (this updates the PR). Post **one fixes comment** on the PR: what was fixed, and what was deferred and why.

### 9. Open questions (only if needed)
Anything that can't be resolved without the user's clarification → post **one open-question comment** on the PR. Skip this step if there are none.

### 10. Report back
Share the PR URL and note which comments were posted (review / fixes / open questions).
