# Working conventions

## Spec-driven workflow

Work moves through a spec-driven lifecycle, carried by project-agnostic skills:

**roadmap → plan → start-work → (code) → review → open-pr → merge-deploy-check**

- **roadmap** — review and groom the backlog; shape and prioritise issues (builds on `write-issue`).
- **plan** — turn the issue into an agreed plan recorded *on the issue*; no code yet. Read-only — no branch, no changes.
- **start-work** — verify the worktree Orca created is for this issue, bring its base up to date, set it up (deps + secrets), orient, mark In Progress, and start implementing the plan. Cuts nothing.
- **code** — no skill of its own; the agreed plan + the conventions below (comments, commit messages) + the project's AGENTS.md (principles, stack, test strategy) + the built-in `/verify` and `/run` carry it.
- **review** — review the diff before shipping (the `review-changes` skill): judge it against the issue's intent, audit AGENTS.md conformance, and wrap the built-in `/code-review` / `/simplify`. Non-side-effecting, so run it in multiple passes.
- **open-pr** — commit, push, open the PR, set the issue to In Review.
- **merge-deploy-check** — merge, deploy, and confirm it works in production (closes the Definition of done).

### How vs what
- **Skills are the project-agnostic *how*** (process) and ship in the `loop` plugin alongside these conventions, reaching every repo that enables it.
- **Project docs (AGENTS.md / CLAUDE.md) are the project-specific *what/context*** — stack, test strategy, architecture, scope.
- A skill **points into AGENTS.md** for specifics rather than embedding them. If a skill names a stack, test command, or scope rule, that belongs in AGENTS.md instead.

### The spec lives on the issue
- The **Linear issue is the spec container.** The spec (specify) and the plan live on the issue and are read via the Linear MCP — not in repo markdown.
- **No in-repo `spec.md` / `plan.md` / `tasks.md`.** Don't create them.
- A throwaway `SPEC.md` is reserved for genuinely large, multi-session features only — delete it once the work lands.

## Definition of done

- "Done" means working in production — not written, reviewed, or merged. The path there (migrations, config/secrets, infra, deploy, clients already live) is part of the work by default.
- Scoping any of it out is a decision to state and get acknowledged — never an implicit omission.
- "Works in dev" is not "works in production." Reason about the delta: data, schema state, secrets/config, infra, and the clients already running against it.

## Dependencies and stack changes

Never install, add, upgrade or remove dependencies, or edit `package.json`, lockfiles, or build config, on your own initiative. It needs an explicit ask or an already-agreed plan — never folded into some other goal ("just to check it renders"). If something is missing, say so and stop. When an install *is* agreed, use whichever manager the project's lockfile indicates, and never add a second lockfile.

## Long-running jobs

Once a job is running — a review panel, a build, a deploy, a migration, a backfill — watching it is not the same as running it. **Never intervene unasked, and never offer to.** No "want me to stop it?", no unprompted cost commentary, no proposal to take a partial result. The caller asked for the job; an offer to cut it short is an intervention dressed as a question, and it arrives exactly when they are least able to judge it.

- **Report what changed, not what it might mean.** A step finishing is worth a sentence. Arithmetic, trajectories and predictions off a progress counter are not — a rising number looks identical whether the work is going well or badly.
- **Don't form the answer from partial output.** Wait for the job's own settle — the result file, the exit code, the summary it writes — before concluding anything. Consuming results in arrival order anchors the conclusion on whichever part finished first, which is a different answer from the one the job was asked for. Reading a log to answer a question that was actually asked is fine; what is barred is treating what has landed so far as the verdict.
- **Stopping it is the caller's call, and theirs to raise.** Answer fully when they ask.

## Keeping plans current

When a plan, Linear issue, or other living document has gone out of date, ask to **correct the document itself** — rewrite the description/body so it matches the current reality. Don't default to bolting on a comment or appendix that leaves the stale plan in place. A comment records a discussion; the canonical description should always reflect the current plan. Suggest the rewrite, not the comment.

## Comments

Comments justify decisions; they don't describe code. If deleting one would cost the reader nothing but a paraphrase of the line beneath it, it shouldn't be there.

- **Anchor it on the thing that needs justifying** — the constant, the branch, the ordering, the workaround. A comment floating over code that already reads plainly is noise.
- **Say what forced the decision, not that one was made.** Cite the run, issue identifier, or failure behind it: `# ... which is how a whole panel returned no count (LAB-58)`. A comment naming its cause survives the next edit; one asserting a preference gets overwritten.
- **Three lines is the cap.** Longer than that is a decision record, not a comment — it belongs on the Linear project, with the code carrying a one-line pointer to it.
- **Never narrate.** No restating a signature (type it), no describing what a test asserts (name the test), no logging what changed (that's the commit message).
- **A stale comment is worse than none.** Changing the code under a comment means correcting or deleting the comment, the same way a stale plan gets rewritten rather than annotated.

## Commit messages

Write commit messages as an imperative summary with the Linear issue identifier at the end, in parentheses, no hash:

```
Add README with setup instructions (EDM-185)
```

## Branches and worktrees

**Orca owns placement.** Each issue gets its own git worktree, and Orca creates it — already on its own branch, off the repo's base ref, and held as a record carrying `path`, `branch`, `baseRef`, `displayName` and `linkedLinearIssue`. Read it with `orca worktree current --json`. The agent never creates worktrees: not `orca worktree create`, not `EnterWorktree`-into-`.claude`.

Orca names the branch after the worktree (`edmacovaz/<name>`), so it carries the issue identifier only where the worktree was named for the issue. Linear's `gitBranchName` is **not** required — Linear links a PR by the identifier appearing in the branch name, the PR title, or a magic word plus identifier in the PR body. Don't rename Orca's branch to chase the exact name: the record stores the branch and has no way to follow a rename.

The flow, all inside that one worktree:

- **`/loop:plan`** — read-only against the code as it stands. No branch, no changes.
- **`/loop:start-work`** — confirms the worktree is for this issue, fetches and reports how far its base has drifted from `baseRef` (advancing it only by fast-forward merge, and only with a clean tree), binds the worktree to the issue, then runs the project's install + secrets setup (`node_modules` isn't shared between worktrees), and starts implementing the plan.

Guardrails:
- The agent works only in the worktree the session is anchored to; the plugin's worktree-anchor guard blocks edits to a *different* worktree of the same repo (see the worktree-anchoring memory). Anchor absolute Read/Edit paths to the worktree root.
- If a session isn't in the intended worktree, switch into an existing one with `EnterWorktree` (`path: …`); still don't *create* one.
- Don't touch an *unrelated* worktree (one that isn't for the issue at hand).
- A repo overrides all of this in its AGENTS.md under `## How work happens here` — for example, declaring that it's worked on `main` in the main checkout. Where that policy and the session's actual placement disagree, `/loop:start-work` stops and asks.
