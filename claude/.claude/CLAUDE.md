# Working conventions

## Commit messages

Write commit messages as an imperative summary with the Linear issue identifier at the end, in parentheses, no hash:

```
Add README with setup instructions (EDM-185)
```

## Branches and worktrees

When given a PR or issue to work on, find the associated branch and check it out in the current worktree before doing anything else. If the checkout fails for any reason, stop and tell the user before proceeding. Never edit files in another worktree via absolute paths.

# User environment

## CLI tools

- `gh` (GitHub CLI) is at `/opt/homebrew/bin/gh` — use this full path, it is not on the default PATH in Claude Code sessions.
- `pnpm` / `node` are managed by nvm. Prefix bash commands with `source ~/.nvm/nvm.sh &&` to activate nvm before calling `node`, `npm`, `pnpm`, or `npx`. The `env.PATH` setting in settings.json does not carry through to Bash tool subshells.
- For `.claude/launch.json` (used by `preview_start`), processes are spawned directly without shell init — nvm won't be on PATH. Use `/bin/sh` with an explicit `cd` to the project root (required for worktrees — getcwd fails otherwise) and `. ~/.nvm/nvm.sh` to load nvm: `{ "runtimeExecutable": "/bin/sh", "runtimeArgs": ["-c", "cd /absolute/path/to/project && . ~/.nvm/nvm.sh && pnpm dev"] }`. The `launch.json` is gitignored so the hardcoded path is fine. Never use a hardcoded node version path — it breaks when the version changes.
- New git worktrees need `source ~/.nvm/nvm.sh && pnpm install` run before the dev server will work — `node_modules` is not shared between worktrees.

If a CLI tool isn't found on PATH, check `/opt/homebrew/bin/` before searching elsewhere. If found, use the full path and add it to this file for future sessions.
