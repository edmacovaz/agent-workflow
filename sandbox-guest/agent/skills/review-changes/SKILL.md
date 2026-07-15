---
name: review-changes
description: Review the branch diff in the sandbox VM before shipping — judge it against the issue's intent, audit it for AGENTS.md conformance, and run the built-in /code-review. Use after coding and before open-pr; safe to run in multiple passes and to fan out to subagents. Read-only — it does not commit, push, or open the PR (that's open-pr).
---

Review the work on the current branch before it ships. This skill only reads and reports — no commits, pushes, or status changes — so run as many passes as you like (it pairs well with subagents reviewing different angles in parallel). When the review is clean, hand off to `open-pr`.

## Current state
- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Branch point: !`git merge-base origin/HEAD HEAD`

## Steps

### 1. Establish the intent
Derive the issue identifier from the branch name — the suffix after the last `-` (e.g. `buttons-and-links-edm-179` → `EDM-179`). Fetch the issue from Linear and read its description, `## Plan`, and comments. This is the spec you review the diff against.

### 2. Fresh-context review against intent
Pull the full diff — `git diff $(git merge-base origin/HEAD HEAD)`, covering committed and uncommitted changes vs the branch point (run `--stat` first for a file overview). Read it cold and adversarially, as a reviewer who didn't write it:
- **Completeness** — is anything the issue/plan asked for missing or half-done?
- **Correctness against intent** — does the code do what the issue asked, or something subtly different?
- **Scope** — anything in the diff the issue didn't ask for, that should be split out or removed?

Surface the one or two genuinely doubtful calls explicitly rather than waving them through.

### 3. AGENTS.md-conformance audit
Audit the diff against the project's own rules. Each part ends in a one-line-per-section report posted in chat — that's what makes the check auditable; without it the step is invisible when nothing changed and gets quietly skipped.

**Instructions** — read AGENTS.md in full. For each section (Stack, Development commands, Workflow, Key Decisions), check whether the diff invalidates anything and flag what's stale. Report one bullet per section — "unchanged" or what's stale.

**Testing** — map each new or changed test to a Critical Area in AGENTS.md's Testing Strategy. Call out critical areas left untested (a gap) and anything tested that the strategy marks Manual-Only or Not-Testing (over-testing).

**Architecture & stack** — for each architectural or stack change (new seam, dependency, framework mechanism, data shape, persistence pattern), give a one-line verdict against the Engineering Principles — *holds up* / *debatable (state the trade-off)* / *revisit*.

**Production readiness** — the change is done when it works in production, not at merge. For anything touching schema, infra, external services, secrets, or a deployed contract, identify what prod still needs and **flag it for the host agent** (merge/deploy is host-owned): migrations + ordering + backup story; prod-only infra/config/secrets; breaking changes to live clients; the dev→prod delta not yet verified. One line per item ("n/a" or what's required and where it's tracked).

### 4. Run the built-in /code-review
Run `/code-review` for correctness bugs and reuse/simplification/efficiency cleanups, and surface its findings. Leave it report-only here (no `--fix`) so this skill stays non-side-effecting. If it turns up cleanups worth applying, apply them with `/simplify` as a **separate step after** the review — keep the review itself read-only so passes stay comparable. Keep this a thin wrap: `/code-review` and `/simplify` own the review logic; don't re-implement it.
