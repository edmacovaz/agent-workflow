---
name: plan
description: Agree a plan for a Linear issue and record it on the issue before any code — the "no code yet" gate. Use after /start-work, when an issue needs a plan worked out and written down before implementation. Not for environment setup — that's /start-work.
---

Plan the work for a Linear issue before writing any code. The issue is the spec container — read it via the Linear MCP and record the agreed plan back onto it. Do **not** create in-repo `spec.md` / `plan.md` / `tasks.md` files.

## Current state
- Branch: !`git branch --show-current`

## Steps

### 1. Read the issue
Take the issue identifier from $ARGUMENTS, or infer it from the branch name (the suffix after the last `-`, e.g. `...-edm-179` → `EDM-179`). Fetch it via the Linear MCP and read the description, any linked documents, attachments, and comments. This is the spec.

### 2. Read before forming a view
Read the files most likely relevant to the issue — don't guess from the title alone. Use Glob and Grep to find the actual code involved, and read AGENTS.md for the project's principles, code style, test strategy, and scope. Understand what exists before proposing what to change.

### 3. Interview the user to a proposal — do not write any code yet
Present the following in chat and discuss until you've converged:

**What the issue asks for** — a plain-English summary of what needs to be done.

**What I found** — relevant files, existing patterns, anything that shapes the approach.

**Assumptions I'd need to make** — anything not specified in the issue and not derivable from the code: URLs, file paths, copy, external identifiers, design decisions. List each one explicitly. Do not silently pick a value and proceed.

**Proposed plan** — a concrete, ordered list of changes. Be specific about which files change and how.

**Questions** — anything that needs the user's input before work can start.

Treat this as a conversation, not a one-shot. Iterate on the proposal until the user agrees.

### 4. Record the agreed plan on the issue
Once agreed, write the plan into the Linear issue as a `## Plan` section in the description (via the Linear MCP). The issue — not a repo file — is the canonical home for the plan. If the issue already carries a plan that's gone stale, rewrite that section to match what was just agreed rather than appending a second one — keep the canonical description current.

### 5. Hold the gate
Do not edit, create, or delete any code until the plan is agreed and recorded on the issue, and the user has explicitly said to proceed. A vague "ok" is enough — but the conversation and the recorded plan must come first.
