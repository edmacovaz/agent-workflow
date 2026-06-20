---
name: write-issue
description: Write a clear, actionable Linear issue. Use when filing a new issue or substantially rewriting one — a bug, follow-up, or unit of work someone can pick up cold.
---

Write a Linear issue someone can pick up without you in the room. Describe the problem and the outcome; leave the implementation to whoever picks it up.

## Shape
- **Context** — the problem and its root cause, and where it surfaced (e.g. "found in EDM-317 device testing"). Concrete, not abstract.
- **Outcome** — what should be true when it's done. Describe the end state, not the implementation.
- **Notes** — constraints, options, related issues to link. A pointer to the relevant area is fine for orientation; a design is not.

## Always
- Lead with the outcome and the problem behind it — let whoever picks it up decide the how.
- Scope to one coherent change; if it's several, split into separate issues.
- For anything touching schema, infra, external services, or a deployed contract: capture the production path (migration, rollout, breaking change, prod-only config) in scope, or explicitly state it's tracked elsewhere — never leave it implicit (see Definition of done).
- Set team, project, assignee, and relations.

## Never
- Write the implementation, a spec, or a design — that's the picker-upper's call.
- Bury a migration, breaking change, or rollout need as an afterthought.
- Pad with restated context or hypothetical future scope.
