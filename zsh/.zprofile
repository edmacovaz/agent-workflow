eval "$(/opt/homebrew/bin/brew shellenv zsh)"

# Must be evaluated after brew: Homebrew ships its own node, and the last eval
# wins on PATH — otherwise fnm's per-project .node-version pins are ignored.
eval "$(/opt/homebrew/bin/fnm env --use-on-cd --shell zsh)"

# Version-manager-independent user binaries (Claude Code's native install lands
# here). Previously only present via the GUI apps' inherited environment, so
# these tools went missing in terminals launched any other way.
export PATH="$HOME/.local/bin:$PATH"
