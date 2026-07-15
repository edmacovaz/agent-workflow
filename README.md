# dotfiles

Personal dotfiles managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Packages

| Package | Tracks |
|---------|--------|
| `claude` | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills/` |
| `git`    | `~/.gitconfig`, `~/.config/git/ignore` |
| `zsh`    | `~/.zshenv`, `~/.zprofile`, `~/.zshrc` |
| `zed`    | `~/.config/zed/keymap.json`, `~/.config/zed/settings.json` |

Everything else in `~/.claude/` (sessions, memory, history, cache) is unmanaged.
Secrets are deliberately **not** tracked — notably `~/.config/gh/` (GitHub OAuth tokens).

`sandbox-guest/` is **not** a stow package — it's source-only, copied into the sandbox VM by
the `sandbox` skill's `rebuild.sh`. `agent/` (orientation `CLAUDE.md` + VM-native skills) lands
in the VM's `~/.claude/`; `git-hooks/` (a pre-push backstop that blocks `main`) lands in
`~/.git-hooks/`. It never symlinks into the host `~`, so the host and VM agents keep separate
instruction sets. Tokens are injected at rebuild time from Doppler (`sted/dev`), never committed here.

The `git` package's `~/.config/git/ignore` carries `**/.claude/settings.local.json`,
which keeps machine-local Claude Code permission files out of every repo.

> **Note:** these configs hard-code Apple Silicon paths (`/opt/homebrew`) and the
> Tailscale.app bundle, so they assume a macOS / Apple Silicon machine.

## Setup on a new machine

**Prerequisites:** Homebrew, GNU Stow

```bash
brew install stow
```

**Clone and stow:**

```bash
git clone git@github.com:edmacovaz/dotfiles.git ~/dotfiles
cd ~/dotfiles
stow claude git zsh zed
```

This creates symlinks in `~` pointing into the matching `~/dotfiles/<package>/` directories.

## Adding new packages

Create a directory matching the target structure, then stow it:

```bash
mkdir -p ~/dotfiles/<package>/<path>
# move files in
stow <package>
```
