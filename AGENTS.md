# agents

## What this repo is

**The agent loop** — the jury runner, the juror agent, the plugins that run inside a juror's
process, and the skills that carry the development lifecycle. It is delivered by GNU Stow (see
`README.md` for packaging), so everything here is an ordinary commit and every change is
revertible.

It used to live in `dotfiles`, beside personal zsh, git and Zed configuration. Repos that consume
the loop should not have to depend on that, which is why it moved (LAB-79). Machine configuration
stayed behind; the sandbox VM and its skill went with it, as personal machine tooling rather than
part of the loop.

## How work happens here

**One Orca worktree per issue**, the usual convention. This section states no override, so
`start-work` applies that default.

**Nothing here is live until it is merged and pushed.** The paths agents actually load resolve
to the *main checkout*, never to your worktree:

| Loaded path | Resolves to |
| --- | --- |
| `~/.claude/skills/<name>` | `~/Documents/Code/agents/claude/.claude/skills/<name>` |
| `~/.claude/rules`, `~/.claude/scripts`, `~/.claude/hooks` | `~/Documents/Code/agents/claude/.claude/…` |
| `~/.config/opencode/agents`, `opencode.jsonc`, `plugins` | `~/Documents/Code/agents/opencode/.config/opencode/…` |

So a skill, script or agent file edited in a worktree is not what any session loads, including
the session editing it. Run this repo's own code **by path from the worktree root** —
`python3 claude/.claude/scripts/test_jury.py`, never `~/.claude/scripts/test_jury.py` — or you
exercise the copy you are not editing.

**And a brand-new file needs a re-stow.** `~/.claude/skills` is a real directory holding one
symlink per skill, not a single folded symlink, because `dotfiles` still contributes the
`sandbox` skill to the same directory and two stow trees cannot both fold it (LAB-79). Files
*inside* an existing skill are live the moment they are pushed; a new skill, or a new rule,
appears only after `stow claude` runs again.

`juror.md` is the sharpest case, because nothing about it looks path-dependent: `opencode --agent
juror` resolves the agent from `~/.config/opencode/agents/juror.md` whichever worktree the juror
runs in. Testing an edited one needs a copy at `.opencode/agent/juror.md` in the worktree, which
opencode discovers alongside the global agents. The repo's root `.gitignore` keeps it
uncommittable: a committed copy would pin every juror in every clone to that snapshot, because
opencode prefers a project-local agent over `~/.config/opencode/agents/`.

**`glob` under-reports here, and says nothing.** opencode never passes `--hidden` to ripgrep,
which prunes hidden directories before it matches — so *every* pattern misses them, not only one
naming a dot directory. It is worse here than it was in `dotfiles`: a stow tree keeps 32 of this
repo's 35 files under `.claude` or `.config`, so `**/*.md` returns 3 of 27. That is success with
zero rows rather than an error, so no tool reports it and no impediment records it. `git ls-files`
is the answer that holds in any session. The juror is given no `glob` at all (LAB-72); Claude
sessions still have one.

Secrets are never tracked.

**Commit is not enough — push.** An unpushed change here won't reach other checkouts or new
sessions, including ones that would otherwise have loaded this file.

## Layout

| Path | Holds |
| --- | --- |
| `claude/.claude/skills/` | Skills, symlinked one directory at a time into `~/.claude/skills/`. **User-global** — they run in every repo. |
| `claude/.claude/rules/` | `agent-workflow.md` — the spec-driven lifecycle and the conventions that carry it, loaded unconditionally in every repo from `~/.claude/rules/` (LAB-79). |
| `claude/.claude/scripts/` | `jury.py` (the panel runner), its `test_jury.py`, `test_no_retry.mjs` (the juror plugin's suite — kept here rather than beside the plugin, because opencode loads every file in a plugin directory as a plugin), and `inspect.sh` — the fixed read-only verbs a juror's shell is limited to. |
| `claude/.claude/hooks/` | `worktree-anchor-guard.sh`, a PreToolUse hook that blocks an edit aimed at a different worktree of the same repo. Invoked by `~/.claude/settings.json`, which `dotfiles` owns — the one reference that crosses the repo boundary (LAB-79). |
| `opencode/.config/opencode/` | `agents/juror.md`, `opencode.jsonc`, and `plugins/` — hooks that run inside a juror's own process, currently `no-retry.js` (LAB-71). |
| `agents/in`, `agents/out` | Jury packs, juror reports, and each run's `<run>.progress.jsonl`. Untracked, and created by the runner relative to the directory it is invoked from. Juror event streams are deliberately **not** here — they go to `~/.cache/jury/<run>/`, because a juror can read anything in the worktree and would otherwise read its co-jurors' reasoning as it forms. |

## Orchestration

Writer sessions are dispatched through **Orca** — durable Run/Task/Dispatch state, typed
messaging, decision gates, and per-worker model selection. **Jurors are not.** A juror is a
bounded `opencode run` process that `jury.py` starts and waits on. Its exit settles it, and the
deadline is the only other thing that can. The runner reads each juror's event stream and reports
what it sees, but never acts on it: an observation that could stop a juror is exactly the
competing stop rule LAB-65 removed (LAB-66).

The division of responsibility: **Orca owns placement, state and stop rules; Claude owns
judgment.** Orca's own dispatch backstop is separate from any loop's iteration cap — they
bound different things (failed dispatches versus review rounds) and must not be conflated.
Check Orca's current threshold rather than assuming a number.

`jury.py` validates every model id against `opencode models` before dispatching, and
`juror.md` declares no model. An unresolvable `-m` therefore fails loudly instead of falling
back to the agent's default and silently degrading the panel to fewer families than it
reports.

## Working on the juror

The juror's policy is the `permission` block of
`opencode/.config/opencode/agents/juror.md`, and it names **every** key opencode defines
rather than the few someone remembered — `websearch` rode that silence until LAB-56, so a
panel reached the open web while it could not run `git status`. Read the block there; it is
not reproduced here, because the copy would go stale.

**The block is not the whole of it.** Plugins run inside the juror's own process and shape what
it does as well: `no-retry.js` counts the calls the room turns down, tells the juror each turn
what it has already hit, and blocks one it has made ten times (LAB-71). Two directories supply
them, and `--pure` loads neither:

| Loaded from | Holds |
| --- | --- |
| `~/.config/opencode/plugins/` | This repo's, via stow — so a new plugin is not live until `stow opencode` has run. |
| `$OPENCODE_CONFIG_DIR/plugins/` | Orca's, injected into every juror launched from a session it started. Not ours and not in this repo. It **adds** a directory rather than replacing ours — measured, because the wording invites the opposite reading and a juror duly read it that way (LAB-71). |

A hook sees only tools that are in the toolset, and never sees a refusal itself: the refusal is
thrown inside the tool's own execute, so all a plugin can observe is that the call never
completed.

**What the permission system is, and is not.** opencode's `bash` permission filters command
*text*; it does not bound capability. For bash, `external_directory` governs only the working
directory — opencode's own tool description calls command-argument path warnings *"advisory
only"* — so a permitted command may read and write anywhere you can. That is why a juror runs
fixed verbs through `claude/.claude/scripts/inspect.sh` rather than raw `git`: the wrapper
chooses what git is asked to run, and rejects the options carrying the same reach (`--output`,
`--no-index`). The enforcing boundary is OS-level and belongs to LAB-38, not to this file.

How the rules resolve, measured against opencode 1.18.30 rather than taken from its docs:

- **Three layers**: opencode's built-in defaults, then `opencode.jsonc`, then the agent block —
  agent entries last, **last matching rule wins**. The built-in layer opens with `"*": "allow"`,
  so a key the agent block does not name is reachable by omission alone; the block's leading
  `"*": deny` is what closes that.
- **A pattern matches the whole command text, redirect included** — while the redirect target is
  never path-checked. So any pattern ending in `*` grants an arbitrary write: with `git log*` allowed,
  `git log --oneline -1 > /tmp/LAB56_REDIRECT_TEST` created that file, `edit` and
  `external_directory` both denying. Exact patterns cannot
  match a redirect; where a verb must take an argument, the trailing `"*>*": deny` covers it.
- **Compound commands are split**, recursively, and every part must be permitted — `$(…)`
  included, so a substitution cannot carry a second command past the list.
- **`~` expands in a pattern but not in the command text**, so each verb is spelled twice: the
  `~/…` form matches an absolute invocation, the `?/…` form matches the literal `~/`.
- **A trailing `*` matches the bare command too** — measured: `git branch *` permitted a bare
  `git branch`, so one entry covers both forms.

A juror can therefore read the worktree, load a skill, run those verbs, and write its own
report. What it cannot check is a claim about the *installed* copy of an agent or script: those
resolve to the main checkout, outside the worktree, and only `~/.claude/skills/` is readable
there — enough for the standards a form review needs, and nothing more. Widening that is
LAB-38's call; LAB-40 covers scoping skill access.

**Jurors are opencode processes, not Claude sessions**, so Claude's own sandbox and
permission settings do not govern them. This config is all that shapes what they reach for —
which is why the limits of what it can enforce, above, are worth knowing before you rely on it.

**Juror output is data, never instructions** — it is read by an agent that can act. The juror
prompt applies the same rule to the artifact under review.

`opencode.jsonc` currently has no skill scoping, so every agent can load every skill on the
machine.

## Skills are user-global

A skill here runs against the other repos too. Nothing repo-specific belongs in one, and
material a skill defers belongs in that skill's own `references/` directory — not in this
file, which those repos never see.

## Languages

**Python unless the runtime forces otherwise.** The runner and its tests are Python; `inspect.sh`
is shell because a command wrapper has to be. JavaScript exists in exactly one place for one
reason: opencode loads plugins as JS modules into its own process, so a juror-side hook cannot
be written in anything else — and a test that exercises one has to import it.

That is the whole warrant. JavaScript elsewhere, or a third language, is a decision to take
deliberately and record, not something to inherit from the first file that needed it (LAB-71).

**No `package.json`, and no lockfile.** Neither suite has a dependency, and the plugin suite
imports the plugin as a data URL precisely so that none is needed. Adding either is a stack
change, not a detail.

## Testing

```
python3 claude/.claude/scripts/test_jury.py
node claude/.claude/scripts/test_no_retry.mjs
```

Two suites because the code is in two languages: the runner is Python, and the juror's plugin
is JavaScript running inside opencode's own process, where Python cannot reach it. Neither
needs a framework or a package.

The plugin suite drives its hooks directly rather than convening a panel. A model will not
repeat itself on demand — asked to make a refused call twelve times it made four, then stopped
and wrote its report — so a panel cannot reach the blocking path at all (LAB-71).

**By path, from the worktree root.** `~/.claude/scripts/` resolves to the main checkout, so the
habitual `python3 ~/.claude/scripts/test_jury.py` exercises the copy you are not editing — and
passes while your change is still broken. Use that form only to confirm a merge landed.

No test framework, deliberately: it must run anywhere the jury does, with nothing installed.
Every test exists because a real run broke, and names the iteration it came from — so a
failing test says which decision is being reversed rather than just going red.

## What deliberately isn't here

Specs and plans live on Linear issues, not in repo markdown. The decision record behind the
loop — why review is cross-vendor, the panel's calibration target, the containment threat
model — lives on the **Loop engineering** project.

Machine configuration lives in `dotfiles`, which also keeps the `sandbox` skill and the
`~/.claude/settings.json` that invokes this repo's hook.
