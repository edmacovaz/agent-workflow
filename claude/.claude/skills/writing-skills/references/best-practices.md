# Beyond the Anthropic baseline

The baseline is [Anthropic's Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) — read it first; it covers frontmatter, progressive disclosure, naming, and word budgets. This file is **only the delta**: what community practice adds or contradicts, how this collection resolves it, and a skeleton to start from. It deliberately doesn't restate the baseline.

Sources for the delta: [obra/superpowers `writing-skills`](https://github.com/obra/superpowers/tree/main/skills/writing-skills) (the most opinionated; treats skills as executable documentation) and [generativeprogrammer.com](https://generativeprogrammer.com/p/skill-authoring-patterns-from-anthropics) (a failure-mode synthesis).

## Where community practice contradicts Anthropic

| Topic | Anthropic | Community | Resolution here |
|---|---|---|---|
| Description content | what **+** when | **when only** — a workflow summarised in the description gets followed *instead of* the skill | what + when, kept terse, **workflow kept out** |
| Fixing bad behaviour | strong "MUST" broadly | **match form to failure**; prohibitions backfire on output-shaping | match form to failure (below) |
| Length unit | <500 **lines** | <~500 **words** normal, <~200 for hot skills | word budgets; lines as the ceiling |
| Testing | evals recommended | a failing test is a **hard gate** | evals where they pay off; not a hard gate for process skills |

The description row is the one that bites in practice: superpowers traced a real bug to it (a description that summarised the steps made the agent do one review where the skill required two). Keep a brief "what", but never the step list.

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

## Caveat: discipline skills vs. process skills

superpowers is tuned for *discipline-enforcing* skills (TDD, verification) — hence its absolutism about failing-test gates and rationalization tables. This collection's skills are mostly *process/workflow* skills, so the high-value transfers are the **"when only" description discipline**, **exclusion clauses**, **match-form-to-failure**, **word-budgeting**, and the **gotchas habit** — not the full rationalization-table machinery. Reach for that apparatus only when you're actually writing a discipline skill.
