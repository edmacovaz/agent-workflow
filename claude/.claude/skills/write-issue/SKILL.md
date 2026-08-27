---
name: write-issue
description: Write a clear, actionable Linear issue. Use when filing a new issue or substantially rewriting one — a bug, follow-up, or unit of work someone can pick up cold.
---

Write a Linear issue someone can pick up without you in the room. Describe the problem and the outcome; leave the implementation to whoever picks it up.

## Shape
- **Context** — the problem and its root cause, and where it surfaced (e.g. "found in EDM-317 device testing"). Concrete, not abstract.
- **Outcome** — what should be true when it's done. Describe the end state, not the implementation.
- **Scenarios** — the situations the outcome will be experienced in: who meets it, from where, and on what (convened from any session; against a plan or a diff). Situations of use, not test cases.
- **Notes** — constraints, options, related issues to link. A pointer to the relevant area is fine for orientation; a design is not.

## Always
- Lead with the outcome and the problem behind it — let whoever picks it up decide the how.
- Settle the scenarios before the outcome — they change what the outcome has to be.
- Scope to one coherent change; if it's several, split into separate issues.
- For anything touching schema, infra, external services, or a deployed contract: capture the production path (migration, rollout, breaking change, prod-only config) in scope, or explicitly state it's tracked elsewhere — never leave it implicit (see Definition of done).
- Set team, project, assignee, and relations.

## Never
- Write the implementation, a spec, or a design — that's the picker-upper's call.
- Write verification steps — a plan turns scenarios into verification, and that belongs on the plan.
- Bury a migration, breaking change, or rollout need as an afterthought.
- Pad with restated context or hypothetical future scope.

## Exploration issues
An exploration deliberately questions a settled decision or direction to see if a viable alternative exists. It is not a contradiction of the plan — if it finds something strong enough, the plan changes; that's its purpose.
- Prefix the title with `Exploration:`.
- Open with a blockquote naming the decision or direction it challenges (link the record it questions, e.g. the issue where the decision was made) and stating that findings may change the plan.
- Body stays an exploration: goal, what to explore, outcomes to report back. Note the switching cost a finding must outweigh if there is a dominant one; no trigger/gate machinery beyond that.
- Groom explorations by refreshing stale premises inside them — never cancel one as "stale because it contradicts the plan" (examples: STE-1, STE-3).
