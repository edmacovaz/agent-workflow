# agent-workflow

The agent loop — the jury runner, the juror agent, and the skills that carry the development
lifecycle. Delivered to `~` with [GNU Stow](https://www.gnu.org/software/stow/).

Project context for agents working here is in `AGENTS.md`.

## Packages

| Package | Tracks |
|---------|--------|
| `claude` | `~/.claude/skills/` (one symlink per skill), `~/.claude/rules/`, `~/.claude/scripts/`, `~/.claude/hooks/` |
| `opencode` | `~/.config/opencode/opencode.jsonc`, `~/.config/opencode/agents/`, `~/.config/opencode/plugins/` |

`~/.claude/settings.json` and `~/.claude/CLAUDE.md` are **not** here — they are personal
configuration and stay in `dotfiles`, which stows into the same `~/.claude/` directory.
Everything else in `~/.claude/` (sessions, memory, history, cache) is unmanaged, as is
opencode's plugin runtime in `~/.config/opencode/` (`node_modules`, `package*.json`, locks).

Secrets are never tracked.

## Setup on a new machine

**Prerequisites:** Homebrew, GNU Stow

```bash
brew install stow
```

**Clone and stow:**

```bash
git clone git@github.com:edmacovaz/agent-workflow.git ~/Documents/Code/agent-workflow
mkdir -p ~/.claude/skills
cd ~/Documents/Code/agent-workflow
stow claude opencode
```

**The `mkdir` is required, not tidiness.** `dotfiles` contributes the `sandbox` skill to the
same `~/.claude/skills/`, and stow will not install a second package into a directory another
stow tree owns as a single folded symlink — it aborts with `existing target is not owned by
stow`. Creating the directory first makes stow fold one level deeper instead, giving one
symlink per skill, which is what lets both repos contribute (LAB-79).

Stow the two repos in either order once that directory exists.

## Adding a skill, rule or script

Create it under the matching package path, then re-stow:

```bash
mkdir -p ~/Documents/Code/agent-workflow/claude/.claude/skills/<name>
# write SKILL.md
stow claude
```

Files *inside* an existing skill are live as soon as they are pushed — the symlink points at the
directory. A brand-new skill, rule or script is a new symlink, so it needs the re-stow.
