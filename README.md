# agent-workflow

The agent loop — the skills that carry the development lifecycle, the jury runner, and the
juror agent. The Claude side ships as the **`loop` plugin**, from a marketplace this repo
hosts; the opencode side is still delivered with [GNU Stow](https://www.gnu.org/software/stow/).

Project context for agents working here is in `AGENTS.md`.

## Install

**Prerequisites:** Claude Code, and GNU Stow for the opencode half.

```bash
git clone git@github.com:edmacovaz/agent-workflow.git ~/Documents/Code/agent-workflow
cd ~/Documents/Code/agent-workflow

claude plugin marketplace add .
claude plugin install loop@agent-workflow

stow -t ~ claude opencode
```

The plugin brings the skills (invoked namespaced — `/loop:plan`, `/loop:review-changes`), the
worktree-anchor guard, the working conventions, and `jury.py`.

**`-t ~` is required for stow, and its absence fails silently.** Stow's default target is the
*parent of the stow directory* — which is `~` only for a repo cloned directly into `~`. From
`~/Documents/Code/agent-workflow` the default is `~/Documents/Code`, so a bare `stow claude
opencode` installs there, reports success, and leaves `~` untouched (LAB-79).

## What stow still delivers, and why

| Package | Tracks | Why not the plugin |
|---------|--------|--------------------|
| `claude` | `~/.claude/scripts/inspect.sh`, `~/.claude/scripts/statusline.py` | Configuration outside the plugin names both by literal path — `juror.md`'s bash allow patterns, which opencode matches as literal text, and `settings.json`'s `statusLine.command`, which `plugin.json` rejects as an unknown field. An installed plugin's path is version-stamped, so pointing either at it breaks on every `plugin update`. |
| `opencode` | `~/.config/opencode/opencode.jsonc`, `agents/`, `plugins/` | opencode's plugin format carries hooks and custom tools only — it cannot carry an agent definition or config (LAB-78). |

`~/.claude/settings.json` and `~/.claude/CLAUDE.md` are **not** here — they are personal
configuration and stay in [`dotfiles`](https://github.com/edmacovaz/dotfiles), which stows into
the same `~/.claude/`. The one reference crossing the boundary is the status-line slot, which
names this repo's `statusline.py`. Everything else in `~/.claude/` (sessions, memory, history,
the plugin cache) is unmanaged, as is opencode's plugin runtime (`node_modules`, `package*.json`).

Secrets are never tracked.

## Updating

An installed plugin is a **version-stamped hard copy**, not a symlink, so pulling is not enough:

```bash
git -C ~/Documents/Code/agent-workflow pull
claude plugin marketplace update agent-workflow && claude plugin update loop
stow -t ~ claude opencode   # only if a stow-side file was added
```

## Working on the loop

Test an edit without installing anything:

```bash
claude --plugin-dir ./plugins/loop
```

That session loads the plugin from your worktree — no install, no copy, and no effect on any
other session. It is also what makes `${CLAUDE_PLUGIN_ROOT}` in the jury skill resolve to the
runner you are editing rather than the installed one.

```bash
python3 tests/test_jury.py
node tests/test_no_retry.mjs
claude plugin validate plugins/loop --strict && claude plugin validate .
```

## Using the loop in another repository

Commit a `.claude/settings.json` naming the marketplace and enabling the plugin; a session that
clones the repo then has the loop, whether or not it runs on this machine.

```json
{
  "extraKnownMarketplaces": {
    "agent-workflow": { "source": { "source": "github", "repo": "edmacovaz/agent-workflow" } }
  },
  "enabledPlugins": { "loop@agent-workflow": true }
}
```
