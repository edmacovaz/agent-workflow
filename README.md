# dotfiles

Personal dotfiles managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Packages

| Package | Tracks |
|---------|--------|
| `claude` | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills/` |

Everything else in `~/.claude/` (sessions, memory, history, cache) is unmanaged.

## Setup on a new machine

**Prerequisites:** Homebrew, GNU Stow

```bash
brew install stow
```

**Clone and stow:**

```bash
git clone git@github.com:edmacovaz/dotfiles.git ~/dotfiles
cd ~/dotfiles
stow claude
```

This creates symlinks in `~` pointing into `~/dotfiles/claude/`.

## Adding new packages

Create a directory matching the target structure, then stow it:

```bash
mkdir -p ~/dotfiles/<package>/<path>
# move files in
stow <package>
```
