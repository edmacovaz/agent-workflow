---
name: merge-deploy-check
description: Merge an approved PR, deploy it, and verify it works in production — closing the Definition of done. Use as the final lifecycle step once the PR is approved. Executes and verifies the production cutover (review-changes only surfaces it); not for opening the PR — that's open-pr.
disable-model-invocation: true
---

Take an approved PR through to verified-in-production. The diff has already been reviewed (`/loop:review-changes`) and the PR opened (`/loop:open-pr`); this is where merge happens — and where "done = working in production" is actually settled, not assumed at merge.

## Current state
- Branch: !`git branch --show-current`
- PR: !`/opt/homebrew/bin/gh pr view --json number,title,state,reviewDecision,mergeStateStatus,url 2>/dev/null || echo "no PR found for this branch"`
- CI checks: !`/opt/homebrew/bin/gh pr checks 2>/dev/null || echo "no checks / no PR"`
- Default branch: !`git rev-parse --abbrev-ref origin/HEAD 2>/dev/null`

## Steps

### 1. Infer the issue and PR
Derive the issue identifier from the branch name — the suffix after the last `-` (e.g. `merge-deploy-check-ste-171` → `STE-171`). Fetch the issue from Linear for its title, description, and `## Plan`. Locate the open PR for the branch (see Current state).

### 2. Confirm it's ready to merge
Check the PR is approved and CI is green. If it isn't approved, or review hasn't happened, stop and point the user back to `/loop:review-changes` and `/loop:open-pr` — don't merge unreviewed or unapproved work.

### 3. Record the production cutover plan on the issue
Before merging, write (or confirm) a `## Production cutover` section on the Linear issue — the canonical, current home for it, the same way `/loop:plan` records `## Plan`. `/loop:review-changes` *surfaces* this dev→prod delta read-only; here it becomes the recorded plan you'll execute. Cover whatever applies:
- migrations + their order relative to the deploy; destructive/data-loss steps + the backup story
- prod-only config/secrets/infra to provision (mirroring dev)
- breaking changes to clients already in the field
- the dev→prod delta not yet verified

Pull the project's actual deploy mechanism and what "check in production" means from its AGENTS.md Deployment/Distribution section (or equivalent) — the skill stays generic about the *how*. If nothing beyond a plain deploy applies, say so in the section rather than leaving it blank. Anything being deferred is a decision to state and get acknowledged — never an implicit omission.

### 4. Merge
Squash-merge the PR: `gh pr merge --squash --delete-branch`. `--delete-branch` removes the merged branch (local and remote).

### 5. Deploy and confirm it landed
Trigger or confirm the deploy per the project's AGENTS.md Deployment/Distribution section. Don't assume merge = deployed — wait for the deploy to actually ship, and run the ordered cutover steps recorded in step 3 (migrations, config/secrets) at the right point relative to it.

### 6. Check in production
Verify it actually works *in production* — the project's definition of "check" from AGENTS.md — reasoning about the dev→prod delta (data, schema state, secrets/config, infra, live clients). `/verify` is a dev-only check; it does not stand in for confirming prod.

### 7. Close out
- Update the `## Production cutover` section to reflect what was *actually* done plus the verification result — keep it current, don't leave a stale plan in place.
- Set the Linear issue to **Done**. The Definition of done is met: it works in production.

The squash-merge already deleted the remote branch (`--delete-branch`, step 4). Don't remove the worktree or local branch here — this skill runs from *inside* the worktree, and worktree/branch pruning is cross-cutting housekeeping that belongs in its own skill run periodically from the main checkout, not bolted onto a per-issue deploy.

### 8. Catalogue follow-ups
Now that the work is verified in production, capture what taking it there surfaced:
- **Docs/stack drift** — anything that should be corrected in the project's AGENTS.md, `~/.claude/CLAUDE.md`, or the techstack (deployment notes, stack, conventions that the cutover proved wrong or incomplete). Fix it now or file it.
- **Other follow-ups** — any separate work the change turned up. File each as a Linear issue via `/loop:write-issue`; don't fold unrelated follow-ups back into this one.
