# Beyond the Anthropic baseline

The baseline is [Anthropic's Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) — read it first; it covers frontmatter, progressive disclosure, naming, and the line budget. This file is **only the delta**: what community practice adds or contradicts, how this collection resolves it, and a skeleton to start from. It deliberately doesn't restate the baseline.

Sources for the delta: [obra/superpowers `writing-skills`](https://github.com/obra/superpowers/tree/main/skills/writing-skills) (the most opinionated; treats skills as executable documentation) and [generativeprogrammer.com](https://generativeprogrammer.com/p/skill-authoring-patterns-from-anthropics) (a failure-mode synthesis).

## Where community practice contradicts Anthropic

| Topic | Anthropic | Community | Resolution here |
|---|---|---|---|
| Description content | what **+** when | **when only** — a workflow summarised in the description gets followed *instead of* the skill | what + when, kept terse, **workflow kept out** |
| Fixing bad behaviour | strong "MUST" broadly | **match form to failure**; prohibitions backfire on output-shaping | match form to failure (below) |
| Length unit | <500 **lines** | **words**, tiered by load frequency: <150 getting-started, <200 frequently-loaded, <500 otherwise | Anthropic's line ceiling; the word tiers only where a skill loads every conversation (below) |
| Testing | evals recommended | a failing test is a **hard gate** | evals where they pay off; not a hard gate for process skills |

The description row is the one that bites in practice: superpowers traced a real bug to it (a description that summarised the steps made the agent do one review where the skill required two). Keep a brief "what", but never the step list.

## Length: the ceiling, and what actually triggers a split

**Measure in lines. The ceiling is Anthropic's: `SKILL.md` body under 500.**

**The word tiers apply only to a skill that loads into every conversation.** That is the condition superpowers attaches them to — its `<150` and `<200` exist because getting-started and frequently-referenced skills are injected on every turn, and its `<500` for everything else is hedged in the original as "still be concise". Nothing here is injected: only `name` and `description` are preloaded, and a body is read when the skill becomes relevant. So the tiers have no members in this collection today. Apply them to any skill that becomes always-on; measure every other skill against the line ceiling.

Measured at `e1af234` across `claude/.claude/skills/`: **8 of 12 skills exceed 500 words; 0 of 12 exceed 500 lines**, the longest being 142. (`sandbox-guest/` carries a separate collection — source-only, copied into the sandbox VM, never symlinked into the host `~` — and is not counted here.) An earlier version of the row above prescribed the word tiers unconditionally, which made two-thirds of the collection non-conforming against a limit nothing was near, and sent three rounds of trimming at `jury` that bought nothing. Don't reintroduce a flat word budget.

**For a skill loaded on invocation the budget is a reading budget, not a token budget.** The failure is the skim — the caller misses a rule the skill exists to enforce — and it shows up structurally, as *"'I think we are finished' at step four of six"*. So check step count and how much each step bundles.

**Split on these triggers, not on a count:**

- **Heavy reference — 100+ lines** of API surface, schemas or tables → its own file.
- **A mechanism consulted at a moment** rather than read to understand the skill → its own file. This is altitude, not size: implementation detail sitting among caller-level instructions is a defect at any length.
- **A code pattern under ~50 lines stays inline.** Moving a short recipe out costs a hop and buys nothing.
- **Every reference one hop from `SKILL.md`.** A file reached through another file gets previewed with `head -100` and acted on as a fragment.
- **A reference over 100 lines opens with a table of contents**, for the same reason. Measured at `e1af234`, 4 of 11 references exceed 100 lines and none carries one — `langfuse/references/` `instrumentation.md`, `sdk-upgrade.md`, `prompt-migration.md`, `judge-calibration.md`. The rule binds new and rewritten references; retrofitting those four is a separate job.

Point at a reference imperatively, from inside the step that needs it — not as a trailing "see also". A bundled file Claude never opens is either unnecessary or badly signalled.

## Match the form to the failure

Anthropic says write clearly; the community insight is to pick *structure* by the failure you're correcting, not by habit:

| Failure mode | Form that fixes it |
|---|---|
| A step gets skipped or mis-ordered | Numbered workflow with the slot made explicit |
| Output comes out the wrong shape | Positive recipe / contract showing the right shape |
| A rule gets rationalized away under pressure | Prohibition + rationalization table pairing each excuse with reality |
| Behaviour depends on a condition | Conditional keyed to the predicate |

**Prohibitions backfire on output-shaping problems** — a single "unless it matters" clause reopens negotiation, so use positive recipes for shape and save strong "MUST" for genuine discipline rules. Flowcharts only for non-obvious decisions, tempting early-exit loops, or "A vs B" — never for reference (use tables), code, or linear steps.

## Two habits worth stealing

- **Exclusion clause.** Selection is push-out (what the skill is *not* for) competing with pull-in (triggers). When a skill has a close neighbour, naming the exclusion is often the highest-value line in the description.
- **"Known gotchas", maintained.** A gotchas list is among the most valuable content of a mature skill — but prune it; a stale entry sends Claude chasing a problem that no longer exists.

## Pre-fill live facts — and the load-time execution trap

A skill that acts on live git or issue state can pre-fill a `## Current state` section so it loads already oriented: write a shell command wrapped in backticks with an exclamation mark immediately before the opening backtick, and on load Claude Code runs it and pastes the output in place.

**Never write that span out in a skill or reference, even as an example** — the loader runs every one it sees (fenced or not), so a literal example executes itself on load and breaks the skill. Describe the syntax in prose, as here.

**Keep pre-fills to simple commands — the load-time sandbox blocks command substitution.** A span containing `$(…)` (or similar) is rejected, and the whole skill fails to load. So `` !`git diff $(git merge-base origin/HEAD HEAD)` `` doesn't just misbehave — it stops the skill loading at all. Pre-fills are for cheap orientation facts (branch, `git status`, a plain ref); push anything that needs substitution — or any bulky output like a full diff — into a *step*, where the agent runs it via the Bash tool and substitution is allowed.

## Caveat: discipline skills vs. process skills

superpowers is tuned for *discipline-enforcing* skills (TDD, verification) — hence its absolutism about failing-test gates and rationalization tables. This collection's skills are mostly *process/workflow* skills, so the high-value transfers are the **"when only" description discipline**, **exclusion clauses**, **match-form-to-failure**, and the **gotchas habit** — not the full rationalization-table machinery. Reach for that apparatus only when you're actually writing a discipline skill.
