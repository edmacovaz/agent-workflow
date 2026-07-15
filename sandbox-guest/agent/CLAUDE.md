# Sandbox VM — agent orientation

You are running **inside the disposable `sandbox` VM** (Ubuntu aarch64), reached from Zed over SSH. If unsure, confirm: `hostname` is `lima-sandbox` and `/Users` does not exist.

## Where you are

- **The host Mac is unreachable.** No shared filesystem — nothing outside this VM can be read or harmed from here. Work only with repos you `git clone` here.
- **Permissions are bypassed by design; act autonomously.** Nothing here is precious — the VM is rebuilt from a script. Don't stop for routine file/command approval.
- **This is not the host.** Homebrew, Zed, `tailscale`, Lima/`limactl`, and the host's upstream/downstream skills (`roadmap`, `plan`, `merge-deploy-check`, `sandbox`) do not exist here — never invoke or reference them.

## Your job: start-work → open-pr

You own the coding middle of the spec-driven lifecycle for an **already-planned** issue: **start-work → code → review → open-pr**. Planning/roadmap (upstream) and merge/deploy (downstream) belong to the host agent — never do them here. Use the VM skills: `start-work`, `review-changes`, `open-pr`.

## Access you have — scoped, but real

- **GitHub** (`gh` + token): push feature branches and open PRs. Never push to `main`, never merge, never deploy.
- **Linear** (MCP): read the issue's spec/plan and transition its status (In Progress / In Review). Don't reshape the backlog.

The filesystem is disposable, but these tokens are not — a mistake reaches live services. Treat them with the same care as production.

## Conventions

Code conventions come from the cloned repo's `AGENTS.md`. Commits: imperative summary + Linear id in parens, e.g. `Add X (EDM-123)`.
