---
name: writing-skills
description: Author or substantially revise a Claude skill to the house standard for shape, description, and structure. Use when creating a new skill, rewriting an existing one, or reviewing a skill's structure before it ships.
---

Write a skill to one consistent, evidence-based standard so its shape, description, and structure don't drift. The baseline is [Anthropic's skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices); `references/best-practices.md` carries the delta — where community practice extends or contradicts it, how this collection resolves it, and a skeleton to copy. Read both before writing.

## Steps

### 1. Name the job — and the failure it prevents
State in one sentence what the skill is for and what goes wrong without it. A skill earns its place by preventing a concrete failure — a step skipped, a wrong-shaped output, a convention re-derived. If you can't name the failure, the skill may not be needed.

### 2. Choose the form
Match the form to the failure, don't default to prose: process/workflow (ordered steps), reference (tables and recipes), or discipline (prohibitions for rules talked away under pressure). Most skills here are process/workflow. See `references/best-practices.md` for picking the form and why prohibitions backfire on output-shaping problems.

### 3. Write the description
The description is the selection mechanism — it decides when the skill loads. Write it third-person, terse, and trigger-rich: **what it does + when to use it**, plus an exclusion clause if it's easily confused with a neighbour. Keep the *workflow* out — summarising the steps there makes Claude follow the summary instead of reading the skill.

### 4. Structure for progressive disclosure
Keep `SKILL.md` short — a table of contents, not an encyclopedia. Push depth (long references, edge cases, examples, schemas) into a `references/` directory and point to each file by path with a one-line "open this when…".

### 5. Decide model invocation
Leave the skill model-invocable by default so it triggers from the description. Set `disable-model-invocation: true` only for side-effecting or destructive skills that should run *only* when the user explicitly invokes them. Add `allowed-tools` only to scope what the skill may run.

### 6. Keep it lean and current
Cut any sentence whose removal wouldn't confuse a competent reader, and budget words tightly — tighter still for frequently-loaded skills. Stay time-insensitive: **point into canonical sources rather than restating them**, so the skill doesn't rot when they change. Prune any "known gotchas" list — stale entries send Claude chasing problems that no longer exist.

## House conventions

Honour the working conventions in `~/.claude/CLAUDE.md` — chiefly the how/what boundary (skills are the project-agnostic *how*; a skill **points into AGENTS.md** for stack, test, and scope specifics rather than embedding them) and the Linear issue as spec container (no in-repo `spec.md` / `plan.md` / `tasks.md`). Skill-authoring specifics on top of that:

- **Pre-fill live facts.** Open a skill that acts on live git/issue state with a `## Current state` section that inlines the relevant shell output, so it starts already oriented instead of spending a step finding its bearings. See `references/best-practices.md` for the inline-command syntax, a worked example, and the load-time execution trap that comes with it.
- Skills live at `claude/.claude/skills/<name>/SKILL.md`, ship via stow, and take a gerund, verb-first name.

## Reference

- `references/best-practices.md` — the delta beyond Anthropic's baseline: where community practice extends or contradicts it (with this collection's resolution), and the discipline-skill-vs-process-skill caveat.
