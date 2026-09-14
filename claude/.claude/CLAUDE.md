- ALWAYS flag what's based on memory or inference when referring to the state of code or infrastructure
- ALWAYS answer or respond to requests first, add any new learnings or follow up questions afterwards

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
- **Skills are the project-agnostic *how*** (process) and live here, user-global, alongside these conventions.
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

- **`/plan`** — read-only against the code as it stands. No branch, no changes.
- **`/start-work`** — confirms the worktree is for this issue, fetches and reports how far its base has drifted from `baseRef` (advancing it only by fast-forward merge, and only with a clean tree), binds the worktree to the issue, then runs the project's install + secrets setup (`node_modules` isn't shared between worktrees), and starts implementing the plan.

Guardrails:
- The agent works only in the worktree the session is anchored to; a global hook blocks edits to a *different* worktree of the same repo (see the worktree-anchoring memory). Anchor absolute Read/Edit paths to the worktree root.
- If a session isn't in the intended worktree, switch into an existing one with `EnterWorktree` (`path: …`); still don't *create* one.
- Don't touch an *unrelated* worktree (one that isn't for the issue at hand).
- A repo overrides all of this in its AGENTS.md under `## How work happens here` — for example, declaring that it's worked on `main` in the main checkout. Where that policy and the session's actual placement disagree, `/start-work` stops and asks.

# Infrastructure (cross-project)

- **Function-shaped web apps** (static/SSR, no persistent process) → **Vercel**
- **Server-shaped backends** (persistent process, global state, queue workers) → **Fly.io** (decision record: STE-238)
- **Agents and background jobs** → **Trigger.dev**; use its platform features (queue concurrency limits, failure alerts, scheduled sweepers, durable waits) over hand-rolled equivalents
- **Secrets** → **Doppler** as single source of truth, one-way fan-out to runtimes
- **Postgres** → **Neon**; branches for migration rehearsal and backfill staging
- **Agent observability** → **Langfuse** (traces, evals) + **PostHog** (errors, analytics)

If the code you're working on doesn't match: check what it actually runs rather than assuming, and plan work to move toward these targets. If a plan would build further on a platform not listed here, flag the mismatch and get confirmation first.

# User environment

## CLI tools

- `gh` (GitHub CLI) is at `/opt/homebrew/bin/gh` — use this full path, it is not on the default PATH in Claude Code sessions.
- `tailscale` CLI ships inside the macOS app bundle at `/Applications/Tailscale.app/Contents/MacOS/Tailscale` — use this full path, it is not on PATH. (The user has an interactive-shell alias in `~/.zshrc`, but that isn't visible to non-interactive tool shells.)
- `limactl` (Lima) is at `/opt/homebrew/bin/limactl` — not on the default PATH.
- For `.claude/launch.json` (used by `preview_start`), processes are spawned directly without shell init. Use `/bin/sh` with an explicit `cd` to the project root (required for worktrees — getcwd fails otherwise) and `. ~/.zshenv` to load fnm: `{ "runtimeExecutable": "/bin/sh", "runtimeArgs": ["-c", "cd /absolute/path/to/project && . ~/.zshenv && <the project's dev script>"] }`. The `launch.json` is gitignored so the hardcoded path is fine.
- `node_modules` is not shared between worktrees, so a fresh worktree needs the project's install run before its dev server will work — using whichever manager the lockfile indicates.

If a CLI tool isn't found on PATH, check `/opt/homebrew/bin/` before searching elsewhere. If found, use the full path and add it to this file for future sessions.

## Sandbox VM

A Lima `vz` VM (`sandbox`) runs Claude Code with permissions bypassed, filesystem-isolated from the host, driven from Zed over SSH (`lima-sandbox`). Setup, rebuild, connect, and adding MCP: use the `sandbox` skill. Zed's remote + bypass config persists in dotfiles (`zed/.config/zed/settings.json`).
