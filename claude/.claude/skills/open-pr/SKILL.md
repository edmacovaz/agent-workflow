---
name: open-pr
description: Commit remaining changes, push, open a PR, and update the Linear issue status. Use when work on an issue is ready for review.
---

Open a PR for the current branch.

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

### 4. Review and clean up
Before opening the PR, review the full diff against the default branch and check:

**Code quality** — anything left rough, commented out, or that could be cleaner before a reviewer sees it.

**Instructions** — read AGENTS.md in full. For each section, check whether the diff invalidates anything: Stack (new tools, removed tools), Development commands (package manager, script names), Workflow, Key Decisions. Do the same spot-check for `~/.claude/CLAUDE.md` (tooling conventions, CLI paths, worktree setup). If anything is stale, update it and include the changes in this commit.

**Post a one-line audit report in chat before continuing** — one bullet per AGENTS.md section, saying either "unchanged" or what you updated. Same for CLAUDE.md as a single line. Example:

> - Stack: unchanged
> - Development commands: added `eval:extraction` and `eval:resolve`
> - Workflow: unchanged
> - Key Decisions: unchanged
> - ~/.claude/CLAUDE.md: unchanged

This makes the check auditable. Without it the step is invisible to the user when nothing changes, and gets quietly skipped on subsequent PRs.

**Testing** — map each new or changed test in the diff to a Critical Area in AGENTS.md's Testing Strategy. Call out anything in a critical area left untested (a real gap), and anything tested that the strategy marks Manual-Only or Not-Testing (over-testing). Judge the finished tests, not the plan.

**Architecture & stack** — for each architectural or stack change in the diff (new abstraction/seam, dependency, framework mechanism, data shape, persistence pattern), give a one-line verdict against the Engineering Principles — *holds up* / *debatable (state the trade-off)* / *revisit* — based on reading the finished implementation, not the intent. Surface the one or two genuinely debatable calls explicitly rather than waving them through; this is a review, not a rubber stamp.

**Post both verdicts in chat before continuing**, in the same auditable form as the instructions audit — a one-line testing verdict plus any gaps, and one line per architectural/stack change. Example:

> **Testing:** aligned — round-trip covers Codable-for-export; gather covers relationship integrity. Gap: nothing asserts the on-disk JSON is ISO-8601 (the cross-language contract).
> **Architecture/stack:** `LocationExtracting` protocol — holds up (idiomatic test seam). `ShareSheet` UIKit wrapper vs native `ShareLink` — debatable (error-surfacing vs "prefer the framework mechanism"). Stack: unchanged.

Raise the debatable calls with the user rather than silently deciding them. Don't gate the PR on this unless something is clearly wrong — the point is to make the choices visible, not to block.

**Production readiness** — the change is done when it works in production, not at merge (merging usually deploys). For anything touching schema, infra, external services, secrets, or a deployed contract, identify what prod still needs and who owns it:
- migrations + order relative to the deploy; destructive/data-loss steps + their backup story
- prod-only infra/config/secrets to provision (mirroring dev)
- breaking changes to clients already in the field
- the dev→prod delta not yet verified

Capture it in a "Production cutover" PR section or a tracked issue, and confirm anything deferred is explicitly acknowledged — not assumed. **Post a one-line-per-item audit in chat before continuing** (migrations / infra+secrets / ordering / breaking changes), each "n/a" or what's required and where it's tracked.

**Skills** — did this work surface a pattern, workflow step, or hard-won lesson that would be worth encoding as a user-level skill (`~/.claude/skills/`) or project skill (`.claude/skills/`)? If so, create or update the skill now.

If you make any changes in this step, commit them before pushing.

### 5. Open the PR
Create a PR with `gh pr create`. The PR should:
- Have a concise title that matches what was built (not just the issue title verbatim)
- Reference the Linear issue URL in the body
- Include a brief summary of what changed and why
- Note anything the reviewer should pay attention to, if relevant

Target branch is the repo's default branch (use `git remote show origin | grep 'HEAD branch'` to determine it).

### 6. Update the Linear issue status
Mark the Linear issue as "In Review".

### 7. Report back
Share the PR URL with the user.
