---
name: writing-skills
description: Author or substantially revise a Claude skill to the house standard for shape, description, and structure. Use when creating a new skill, rewriting an existing one, or reviewing a skill's structure before it ships.
---

The baseline is [Anthropic's skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices); `references/best-practices.md` carries the delta — where community practice extends or contradicts it, how this collection resolves it, and a skeleton to copy. Read both before writing.

## Steps

### 1. Name the job — and the failure it prevents
State in one sentence what the skill is for and what goes wrong without it — a step skipped, a wrong-shaped output, a convention re-derived. If you cannot name the failure, do not write the skill.

### 2. Choose the form
Match the form to the failure, don't default to prose: process/workflow (ordered steps), reference (tables and recipes), or discipline (prohibitions for rules talked away under pressure). Most skills here are process/workflow. See `references/best-practices.md` for picking the form and why prohibitions backfire on output-shaping problems.

### 3. Write to the register
Every sentence is an instruction, a fact needed to follow one, or a statement of what the output is used for and who consumes it. Nothing else.

State a rule as an instruction in the step it governs. See `references/register.md` for cuts made under this rule.

### 4. Write the description
The description is the selection mechanism — it decides when the skill loads. Write it third-person, terse, and trigger-rich: **what it does + when to use it**, plus an exclusion clause if it's easily confused with a neighbour. Keep the *workflow* out.

### 5. Structure and budget
Keep `SKILL.md` short — tighter still for frequently-loaded skills. Push depth (long references, edge cases, examples, schemas) into a `references/` directory and point to each file by path with a one-line "open this when…". Point into canonical sources rather than restating them.

### 6. Decide model invocation
Leave the skill model-invocable by default so it triggers from the description. Set `disable-model-invocation: true` only for side-effecting or destructive skills that should run *only* when the user explicitly invokes them. Add `allowed-tools` only to scope what the skill may run.

## House conventions

Honour the working conventions in `~/.claude/CLAUDE.md`, chiefly the how/what boundary and the Linear issue as spec container. Skill-authoring specifics on top of those:

- **Pre-fill live facts.** Open a skill that acts on live git/issue state with a `## Current state` section that inlines the relevant shell output. See `references/best-practices.md` for the inline-command syntax, a worked example, and the load-time execution trap that comes with it.
- Skills live at `claude/.claude/skills/<name>/SKILL.md`, ship via stow, and take a gerund, verb-first name.
