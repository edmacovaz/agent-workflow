---
name: sandbox
description: Set up, rebuild, connect to, and safely extend the isolated Lima vz "sandbox" VM that runs Claude Code with permissions bypassed — filesystem-isolated from the host and driven from Zed over SSH. Use when bringing up, restoring, connecting to, or adding MCP/credentials to the sandbox VM. Not for general Lima/Docker questions or dev containers.
---

# Sandbox VM

An isolated Lima `vz` VM (`sandbox`) for running Claude Code with `--dangerously-skip-permissions` safely. Booted with `--mount-none`, so the host filesystem is unreachable — a runaway agent can only trash the disposable VM. Driven from Zed as an SSH remote project, so the agent process executes *in the VM*.

## Current state

!`/opt/homebrew/bin/limactl list`

## Facts

- **`limactl`**: `/opt/homebrew/bin/limactl` (not on the default PATH).
- **Guest**: Ubuntu aarch64; home `/home/edmacovaz.guest`; workspace `~/work/scratch`. Node 22 / git / Claude Code installed globally.
- **SSH**: host alias `lima-sandbox`, via `Include ~/.lima/sandbox/ssh.config` at the top of `~/.ssh/config` (tracks the dynamic port). Connect with `ssh lima-sandbox`.
- **Zed client config** — the remote connection and `"mode": "bypassPermissions"` — persists in dotfiles at `zed/.config/zed/settings.json`, so it restores with dotfiles; only the VM itself needs rebuilding.

## Connect from Zed

1. Open Remote → Connect SSH Server → `ssh lima-sandbox` → Open Folder (`/home/edmacovaz.guest/work/scratch`, or a repo cloned into the VM).
2. Agent Panel → Claude → new thread → `/login`.
3. Confirm permission mode is **Bypass Permissions** — Zed bug #39392 can silently revert it; a bash command running with no prompt confirms it's on.

## Lifecycle

- Pause / resume: `limactl stop sandbox` / `limactl start sandbox`.
- **Rebuild from scratch** — `scripts/rebuild.sh`, then re-`/login` in Zed. Use after a `limactl delete` or on a new machine. **It destroys any existing `sandbox` instance**, so only run it to rebuild, never to reconnect.
  - Host prerequisites: Lima installed (`brew install lima`) and the Doppler CLI authed (`doppler login`), with `GH_TOKEN` + `LINEAR_API_KEY` present in `sted/dev` (credentials are pulled from there, never committed). Without Doppler the VM builds but comes up uncredentialed.
  - The only manual step after it runs is `claude /login` in the VM (interactive Anthropic auth — unscriptable).

## Getting code in

`git clone` inside the VM (no host mount). Use a dedicated, repo-scoped token or deploy key — never host git credentials.

## Adding MCP

Claude Code manages its own MCP from the VM's `~/.claude.json`, independent of Zed (so Zed's remote-MCP handling is irrelevant). The filesystem is sealed, but **any token placed in the VM is a capability bypass-mode Claude fully holds** — add least-privilege / read-only tokens only, never primary personal creds. Configure with `claude mcp add` inside the VM; OAuth servers (e.g. Linear) need the localhost callback forwarded with `ssh -L`.
