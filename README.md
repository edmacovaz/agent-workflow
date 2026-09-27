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

claude plugin marketplace add edmacovaz/agent-workflow
claude plugin install loop@agent-workflow

stow -t ~ claude opencode
```

The plugin brings the skills (invoked namespaced — `/loop:plan`, `/loop:review-changes`), the
worktree-anchor guard, the working conventions, and `jury.py`.

**The marketplace is the GitHub repo, not the checkout.** A directory source is a path on one
machine, so no cloud session can follow it, and a repo enabling the loop names the GitHub source
— two sources under one marketplace name would compete. Cloning it needs the same GitHub
credential you cloned this repo with.

**`-t ~` is required for stow, and its absence fails silently.** Stow's default target is the
*parent of the stow directory* — which is `~` only for a repo cloned directly into `~`. From
`~/Documents/Code/agent-workflow` the default is `~/Documents/Code`, so a bare `stow claude
opencode` installs there, reports success, and leaves `~` untouched (LAB-79).

## What stow still delivers, and why

| Package | Tracks | Why not the plugin |
|---------|--------|--------------------|
| `claude` | `~/.claude/scripts/inspect.sh`, `~/.claude/scripts/statusline.py` | Configuration outside the plugin names both by literal path — `juror.md`'s bash allow patterns, which opencode matches as literal text, and `settings.json`'s `statusLine.command`, which `plugin.json` rejects as an unknown field. An installed plugin sits at a path that changes on every update, so pointing either at it breaks on every `plugin update`. |
| `opencode` | `~/.config/opencode/opencode.jsonc`, `agents/`, `plugins/`, `skills/` | opencode's plugin format carries hooks and custom tools only — it cannot carry an agent definition or config (LAB-78). `skills/` symlinks the two standards a juror loads, `plan` and `review-changes`, because opencode never reads the Claude plugin cache. |

`~/.claude/settings.json` and `~/.claude/CLAUDE.md` are **not** here — they are personal
configuration and stay in [`dotfiles`](https://github.com/edmacovaz/dotfiles), which stows into
the same `~/.claude/`. The one reference crossing the boundary is the status-line slot, which
names this repo's `statusline.py`. Everything else in `~/.claude/` (sessions, memory, history,
the plugin cache) is unmanaged, as is opencode's plugin runtime (`node_modules`, `package*.json`).

Secrets are never tracked.

## Moving from the old stow-only install

A machine that stowed the loop before it became a plugin has symlinks in `~/.claude/skills/`,
`~/.claude/rules/` and `~/.claude/hooks/` pointing into `claude/.claude/`. Pulling this change
deletes their targets, so **unstow before pulling** — stow needs the files present to know what
to remove:

```bash
cd ~/Documents/Code/agent-workflow
stow -D -t ~ claude
git pull
claude plugin marketplace add edmacovaz/agent-workflow
claude plugin install loop@agent-workflow
stow -t ~ claude opencode
```

Then, in the same sitting, remove the worktree-guard `PreToolUse` block from
`~/.claude/settings.json` in `dotfiles`: the plugin carries that hook now, and the old entry
names a file that no longer exists. Restart Claude Code afterwards — skills are namespaced
(`/loop:plan`) from the next session.

Pull first and the links dangle: no lifecycle skills, no conventions, and a hook that fails on
every edit until the plugin is installed. Install first and everything loads twice — the rules
from both routes, and each skill as both `/plan` and `/loop:plan`.

## Updating

An installed plugin is a **hard copy** fetched from GitHub, at a path that changes on every
update, so it updates from what is pushed to `main`, not from your checkout:

```bash
claude plugin marketplace update agent-workflow && claude plugin update loop
git -C ~/Documents/Code/agent-workflow pull   # the stow side still follows the checkout
stow -t ~ claude opencode                      # only if a stow-side file was added or removed
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
