---
name: review-changes
description: Review the branch diff before shipping — judge it against the issue's intent, audit it for AGENTS.md conformance, and run the built-in /code-review. Use after coding and before /open-pr; safe to run in multiple passes and to fan out to subagents. Read-only — it reviews but does not commit, push, or open the PR (that's /open-pr).
---

Review the work on the current branch before it ships. This skill only reads and reports — it makes no commits, pushes, or status changes, so run it as many passes as you like (and it pairs well with subagents reviewing different angles in parallel). When the review is clean, hand off to `/open-pr`.

## Current state
- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Diff under review (committed + uncommitted, vs the branch point): !`git diff $(git merge-base origin/HEAD HEAD)`

## Steps

### 1. Establish the intent
Derive the issue identifier from the branch name — the suffix after the last `-` (e.g. `buttons-and-links-edm-179` → `EDM-179`). Fetch the issue from Linear and read its description, `## Plan`, and comments. This is the spec you review the diff against.

### 2. Fresh-context review against intent
Read the diff cold and adversarially, as a reviewer who didn't write it. Judge the finished implementation, not the plan:
- **Completeness** — is anything the issue/plan asked for missing or only half-done?
- **Correctness against intent** — does the code actually do what the issue asked, or something subtly different?
- **Scope** — anything in the diff the issue didn't ask for, that should be split out or removed?

Surface the one or two genuinely doubtful calls explicitly rather than waving them through. This is a review, not a rubber stamp.

### 3. AGENTS.md-conformance audit
Audit the diff against the project's own rules. Each part below ends in a **one-line-per-section report posted in chat** — this is what makes the check auditable; without it the step is invisible when nothing changed and gets quietly skipped next time.

**Instructions** — read AGENTS.md in full. For each section, check whether the diff invalidates anything: Stack (new/removed tools), Development commands (package manager, script names), Workflow, Key Decisions. Do the same spot-check for `~/.claude/CLAUDE.md` (tooling conventions, CLI paths, worktree setup). Flag anything stale. Report one bullet per AGENTS.md section — "unchanged" or what's stale — plus one line for CLAUDE.md:

> - Stack: unchanged
> - Development commands: `eval:extraction` and `eval:resolve` added in the diff but not documented
> - Workflow: unchanged
> - Key Decisions: unchanged
> - ~/.claude/CLAUDE.md: unchanged

**Testing** — map each new or changed test in the diff to a Critical Area in AGENTS.md's Testing Strategy. Call out anything in a critical area left untested (a real gap), and anything tested that the strategy marks Manual-Only or Not-Testing (over-testing). Judge the finished tests, not the plan.

**Architecture & stack** — for each architectural or stack change in the diff (new abstraction/seam, dependency, framework mechanism, data shape, persistence pattern), give a one-line verdict against the Engineering Principles — *holds up* / *debatable (state the trade-off)* / *revisit* — from reading the finished implementation. Surface the genuinely debatable calls rather than waving them through.

Post the testing and architecture verdicts together, in the same auditable one-line form:

> **Testing:** aligned — round-trip covers Codable-for-export; gather covers relationship integrity. Gap: nothing asserts the on-disk JSON is ISO-8601 (the cross-language contract).
> **Architecture/stack:** `LocationExtracting` protocol — holds up (idiomatic test seam). `ShareSheet` UIKit wrapper vs native `ShareLink` — debatable (error-surfacing vs "prefer the framework mechanism"). Stack: unchanged.

**Production readiness** — the change is done when it works in production, not at merge. For anything touching schema, infra, external services, secrets, or a deployed contract, identify what prod still needs and who owns it:
- migrations + order relative to the deploy; destructive/data-loss steps + their backup story
- prod-only infra/config/secrets to provision (mirroring dev)
- breaking changes to clients already in the field
- the dev→prod delta not yet verified

Post a one-line-per-item audit (migrations / infra+secrets / ordering / breaking changes), each "n/a" or what's required and where it's tracked. Raise debatable calls with the user rather than silently deciding them; don't gate on this unless something is clearly wrong — the point is to make the choices visible.

### 4. Run the built-in /code-review
Run the built-in `/code-review` for correctness bugs and reuse/simplification/efficiency cleanups, and surface its findings. Leave it report-only here (no `--fix`) so this skill stays non-side-effecting. If it (or the audit above) turns up quality cleanups worth applying, recommend the user run `/simplify` — don't run it yourself, since it edits the tree. Keep this a thin wrap: `/code-review` and `/simplify` own the review logic; don't re-implement it.
