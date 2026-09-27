---
name: plan-iteration
description: Plan the next iteration of work already under way, from review findings. Use after a jury or code review on a diff whose issue already carries an agreed plan. Not the first plan for an issue (that is `plan`).
disable-model-invocation: true
---

Produces an `### Iteration N` section on the issue's `## Plan`, and brings that plan up to date — what the implementer builds from, and what a later review judges the diff against. Nothing is implemented until this iteration is recorded.

## 1. Verify

Check each finding against the source. Record which findings you dropped.

## 2. Locate the mechanism

For each finding you keep, answer and record with the item:

- Where else does this mechanism occur?
- If the fix adds a delete, stop, close or overwrite, what decides it fires?
- If the fix changes when or where state is written, what reads that state?

## 3. Check for recurrence

If this class of finding has appeared before on this issue, fix the mechanism that permits the class rather than the cited instance.

## 4. Check the Outcome

Re-read the issue's Outcome. Name any bullet the work has not delivered, and either take it as an item or record it as deferred.

## 5. Raise before recording

Put to the caller, and wait for an answer:

- a feature whose findings keep accumulating — whether to keep it
- any change to what was already agreed: a statement in the canonical plan, an earlier iteration, an Outcome bullet, or a `Not in scope` entry

Every change to what was already agreed is recorded under **Amendments** in step 7. A decision that changes nothing is recorded with the assumptions.

## 6. Bring the plan up to date

Rewrite the statements this iteration supersedes — in `## Plan`, and in the Outcome or `Not in scope` where the caller agreed a change there — so the issue states what is now being built.

Linear's description history is not reachable through the MCP. A superseded statement survives only where step 7 records it.

## 7. Record

Write the step 6 revision and `### Iteration N` in one `save_issue` call. Do not rewrite earlier iterations. Leave the issue's status unchanged.

Open `## Plan` with one line stating that the section is the current plan and the iterations below record what changed.

Open the iteration with a **From** line: the review it answers — jury run id and mode, the caller, or a self-check — and the plan version the reviewed diff was built from.

Then two groups:

- **Corrections** — the work did not match what was agreed.
- **Amendments** — what was agreed moves. Each names what it supersedes — the `## Plan` statement, earlier iteration, Outcome bullet or `Not in scope` entry — how that now reads, and that the caller agreed it.

Record an item that both corrects and amends as two items, one in each group. A Correction never supersedes an agreed statement; anything that does is an Amendment.

Name the file for each item. Include assumptions and what is not being taken.
