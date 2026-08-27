- ALWAYS flag what's based on memory or inference when referring to the state of code or infrastructure
- ALWAYS answer or respond to requests first, add any new learnings or follow up questions afterwards

# Working conventions

## Spec-driven workflow

Work moves through a spec-driven lifecycle, carried by project-agnostic skills:

**roadmap → plan → start-work → (code) → review → open-pr → merge-deploy-check**

- **roadmap** — review and groom the backlog; shape and prioritise issues (builds on `write-issue`).
- **plan** — turn the issue into an agreed plan recorded *on the issue*; no code yet. Runs inside the worktree you created in Zed, against the latest `main` — no branch, no changes.
- **start-work** — the gate between planning and coding: cut the issue's branch (Linear naming) off latest `main`, set up the worktree (deps + secrets), orient, mark In Progress. Runs in the same Zed worktree the plan ran in.
- **code** — no skill of its own; the agreed plan + the project's AGENTS.md (principles, code style) + the built-in `/verify` and `/run` carry it.
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

## Commit messages

Write commit messages as an imperative summary with the Linear issue identifier at the end, in parentheses, no hash:

```
Add README with setup instructions (EDM-185)
```

## Branches and worktrees

Each issue/PR gets its **own git worktree**, and **you (the user) create it in Zed's picker** — not the agent. Zed generates the worktree's name and location; that's fine, leave it. The agent never creates worktrees (no `EnterWorktree`-into-`.claude`), and there's no "Add Folders to Project" step — you already opened it in Zed.

**Exception — `~/dotfiles` is worked directly on `main`.** Stow symlinks point at the main checkout, so a worktree there would edit a copy nothing consumes. Don't create one, don't expect one, and don't treat being in the primary checkout as a mistake to correct. Commit on `main` — and push: worktrees are cut from `origin/main`, so an unpushed dotfiles change is invisible to every new session. Repo context is in `~/dotfiles/AGENTS.md`.

The flow, all inside that one Zed worktree:

- **Create + open** the worktree in Zed, off the latest `main`. Run the Claude session there.
- **`/plan`** runs against latest `main` — read-only, no branch, no changes.
- **`/start-work`** is the gate that cuts the branch: it fetches, creates the issue's branch (named exactly Linear's `gitBranchName`, for PR auto-linking) off latest `origin/main`, then runs the project's install + secrets setup (`node_modules` isn't shared between worktrees). Coding starts after this.

Guardrails:
- The agent works only in the worktree the session is anchored to; a global hook blocks edits to a *different* worktree of the same repo (see the worktree-anchoring memory). Anchor absolute Read/Edit paths to the worktree root.
- If a session isn't in the intended worktree, switch into an existing one with `EnterWorktree` (`path: …`); still don't *create* one.
- `/start-work` must not cut a branch in the **main checkout** — if it detects the primary worktree, it stops and asks you to create/open a Zed worktree (dotfiles excepted — see above).
- Don't touch an *unrelated* worktree (one that isn't for the issue at hand).

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
