#!/usr/bin/env bash
# Rebuild the isolated `sandbox` VM from scratch. DESTROYS any existing instance.
# After it finishes: connect from Zed and run `/login` in a Claude thread.
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"

NAME=sandbox
CPUS=4
MEMORY=8   # GiB
DISK=40    # GiB

if ! command -v limactl >/dev/null 2>&1; then
  echo "limactl not found — install Lima first: brew install lima" >&2
  exit 1
fi

# Clean rebuild: remove any existing instance of this name.
if limactl list --format '{{.Name}}' 2>/dev/null | grep -qx "$NAME"; then
  echo "Removing existing '$NAME'..."
  limactl stop "$NAME" 2>/dev/null || true
  limactl delete "$NAME"
fi

echo "Booting sealed vz VM '$NAME' (no host mounts)..."
limactl start --tty=false --vm-type=vz --mount-none \
  --cpus "$CPUS" --memory "$MEMORY" --disk "$DISK" \
  --name="$NAME" template:default

echo "Installing toolchain (git, gh, Node, Claude Code)..."
limactl shell "$NAME" -- sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
limactl shell "$NAME" -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git gh nodejs npm
limactl shell "$NAME" -- sudo npm install -g @anthropic-ai/claude-code
# Enable corepack so a project's declared package manager (pnpm/yarn) resolves per-repo.
limactl shell "$NAME" -- sudo corepack enable

# Give the VM a git author identity (mirror the host's) so commits in cloned repos succeed
# and PRs attribute correctly — gh auth sets push credentials, not author identity.
GIT_NAME="$(git config --global user.name 2>/dev/null || true)"
GIT_EMAIL="$(git config --global user.email 2>/dev/null || true)"
if [ -n "$GIT_NAME" ] && [ -n "$GIT_EMAIL" ]; then
  echo "Setting VM git identity ($GIT_NAME <$GIT_EMAIL>)..."
  limactl shell "$NAME" -- git config --global user.name "$GIT_NAME"
  limactl shell "$NAME" -- git config --global user.email "$GIT_EMAIL"
fi

# Provision the VM-specific agent profile: orientation CLAUDE.md + the VM-native
# `deliver` skill. Source-only dir, never stowed to the host.
GUEST_PROFILE="$HOME/dotfiles/sandbox-guest"
if [ -d "$GUEST_PROFILE/agent" ]; then
  echo "Provisioning guest agent profile (CLAUDE.md + VM skills)..."
  tar --no-xattrs -C "$GUEST_PROFILE/agent" -cf - . \
    | limactl shell "$NAME" -- sh -c 'mkdir -p ~/.claude/skills && tar -C ~/.claude -xf -'
fi

# Suppress inherited claude.ai account connectors. The VM's Claude is logged into the
# user's Anthropic account, which would otherwise sync in every account connector
# (Vercel, Gmail, Notion, …) — far more reach than the scoped GitHub + Linear we intend.
# This leaves explicitly-configured servers (our injected Linear) untouched.
echo "Disabling inherited claude.ai connectors in the VM..."
limactl shell "$NAME" -- node -e '
  const fs=require("fs"), p=process.env.HOME+"/.claude/settings.json";
  let c={}; try{c=JSON.parse(fs.readFileSync(p,"utf8"))}catch(e){}
  c.disableClaudeAiConnectors=true;
  fs.writeFileSync(p, JSON.stringify(c,null,2));
'

# Install the pre-push backstop as a global git hook (refuses pushes to main/master).
# Behavioural guard against an agent mistake — sted is a private free-plan repo, so
# server-side branch protection isn't available.
if [ -d "$GUEST_PROFILE/git-hooks" ]; then
  echo "Installing pre-push backstop (blocks main/master)..."
  tar --no-xattrs -C "$GUEST_PROFILE/git-hooks" -cf - . \
    | limactl shell "$NAME" -- sh -c 'mkdir -p ~/.git-hooks && tar -C ~/.git-hooks -xf - && chmod +x ~/.git-hooks/* && git config --global core.hooksPath ~/.git-hooks'
fi

# Inject scoped credentials from Doppler (sted/dev). The host pulls with its own
# Doppler auth; nothing Doppler-shaped ever enters the VM. Idempotent — safe to re-run.
if command -v doppler >/dev/null 2>&1; then
  echo "Injecting credentials from Doppler (sted/dev)..."
  GH_TOKEN="$(doppler secrets get GH_TOKEN -p sted -c dev --plain 2>/dev/null || true)"
  LINEAR_API_KEY="$(doppler secrets get LINEAR_API_KEY -p sted -c dev --plain 2>/dev/null || true)"

  if [ -n "$GH_TOKEN" ]; then
    printf '%s' "$GH_TOKEN" \
      | limactl shell "$NAME" -- sh -c 'gh auth login --with-token && gh auth setup-git' \
      && echo "  gh: authenticated"
  else
    echo "  gh: GH_TOKEN not found in sted/dev — skipped"
  fi

  if [ -n "$LINEAR_API_KEY" ]; then
    limactl shell "$NAME" -- claude mcp remove --scope user linear >/dev/null 2>&1 || true
    limactl shell "$NAME" -- claude mcp add --scope user --transport http linear \
      https://mcp.linear.app/mcp --header "Authorization: Bearer $LINEAR_API_KEY" >/dev/null \
      && echo "  linear MCP: added (user scope)"
  else
    echo "  linear MCP: LINEAR_API_KEY not found in sted/dev — skipped"
  fi
  unset GH_TOKEN LINEAR_API_KEY
else
  echo "doppler not found on host — skipping credential injection." >&2
fi

# Ensure the host SSH config includes Lima's generated config (idempotent, prepended).
SSH_CONFIG="$HOME/.ssh/config"
INCLUDE_LINE="Include ~/.lima/$NAME/ssh.config"
if [ ! -f "$SSH_CONFIG" ] || ! grep -qF "$INCLUDE_LINE" "$SSH_CONFIG"; then
  echo "Adding SSH Include for lima-$NAME..."
  mkdir -p "$HOME/.ssh"
  { printf '%s\n\n' "$INCLUDE_LINE"; [ -f "$SSH_CONFIG" ] && cat "$SSH_CONFIG"; } > "$SSH_CONFIG.tmp"
  mv "$SSH_CONFIG.tmp" "$SSH_CONFIG"
  chmod 600 "$SSH_CONFIG"
fi

# Scratch workspace so Zed has a folder to open.
limactl shell "$NAME" -- sh -c '
  mkdir -p ~/work/scratch && cd ~/work/scratch
  if [ ! -d .git ]; then
    git init -q
    git config user.email sandbox@local
    git config user.name sandbox
    printf "# scratch\n" > README.md
    git add -A && git commit -q -m "scratch workspace"
  fi'

WORKDIR="$(limactl shell "$NAME" -- sh -c 'echo ~/work/scratch')"

cat <<EOF

Done. '$NAME' is up and sealed (host filesystem not mounted). Next, in Zed:
  1. Open Remote -> Connect SSH Server -> 'ssh lima-$NAME' -> Open Folder $WORKDIR
  2. Agent Panel -> Claude -> new thread -> /login
  3. Confirm permission mode is Bypass Permissions (it persists in Zed settings; verify it stuck).
EOF
