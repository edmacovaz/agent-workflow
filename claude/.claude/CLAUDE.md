# Working conventions

## Definition of done

- "Done" means working in production — not written, reviewed, or merged. The path there (migrations, config/secrets, infra, deploy, clients already live) is part of the work by default.
- Scoping any of it out is a decision to state and get acknowledged — never an implicit omission.
- "Works in dev" is not "works in production." Reason about the delta: data, schema state, secrets/config, infra, and the clients already running against it.

## Keeping plans current

When a plan, Linear issue, or other living document has gone out of date, ask to **correct the document itself** — rewrite the description/body so it matches the current reality. Don't default to bolting on a comment or appendix that leaves the stale plan in place. A comment records a discussion; the canonical description should always reflect the current plan. Suggest the rewrite, not the comment.

## Commit messages

Write commit messages as an imperative summary with the Linear issue identifier at the end, in parentheses, no hash:

```
Add README with setup instructions (EDM-185)
```

## Branches and worktrees

Each issue/PR gets its **own git worktree** under `.claude/worktrees/<branch-name>` (nested inside the main checkout — this is the `EnterWorktree` tool's default location, and the preferred one), not just a branch in the current worktree. Do not use the older sibling `../sted-worktrees/` path for new worktrees. When given a PR or issue to work on:

- Look for an existing worktree for it first (`git worktree list`). If one exists, use it — cd in and do all work there. Editing that worktree's files by absolute path is expected; that's where the work lives.
- If none exists, create one with the `EnterWorktree` tool (`name: <branch-name>`). It branches off the latest `origin/main` and switches the session into the new worktree under `.claude/worktrees/`. The tool prefixes the branch with `worktree-`, so immediately `git branch -m <branch-name>` to match Linear's `gitBranchName` (needed for PR auto-linking). New worktrees need `npm install` / `pnpm install` before tooling works — `node_modules` isn't shared between worktrees.
- If the branch can't be checked out or the worktree can't be created, stop and tell the user before proceeding.
- Don't touch an *unrelated* worktree (one that isn't for the issue at hand).

Note: a worktree created this way won't appear in Zed's "Open Worktrees" picker (Zed only lists ones created through its own UI). To see it in Zed, use "Add Folders to Project". Mention this when creating one so the user isn't surprised it's missing from the picker.

# User environment

## CLI tools

- `gh` (GitHub CLI) is at `/opt/homebrew/bin/gh` — use this full path, it is not on the default PATH in Claude Code sessions.
- `node` / `npm` / `pnpm` / `npx` are managed by fnm, initialised via `~/.zshenv`. They should be on PATH in all subshells without any manual prefix.
- `tailscale` CLI ships inside the macOS app bundle at `/Applications/Tailscale.app/Contents/MacOS/Tailscale` — use this full path, it is not on PATH. (The user has an interactive-shell alias in `~/.zshrc`, but that isn't visible to non-interactive tool shells.)
- For `.claude/launch.json` (used by `preview_start`), processes are spawned directly without shell init. Use `/bin/sh` with an explicit `cd` to the project root (required for worktrees — getcwd fails otherwise) and `. ~/.zshenv` to load fnm: `{ "runtimeExecutable": "/bin/sh", "runtimeArgs": ["-c", "cd /absolute/path/to/project && . ~/.zshenv && pnpm dev"] }`. The `launch.json` is gitignored so the hardcoded path is fine.
- New git worktrees need `pnpm install` run before the dev server will work — `node_modules` is not shared between worktrees.

If a CLI tool isn't found on PATH, check `/opt/homebrew/bin/` before searching elsewhere. If found, use the full path and add it to this file for future sessions.
