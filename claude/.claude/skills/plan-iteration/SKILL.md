---
name: plan-iteration
description: Plan the next iteration of work already under way, from review findings. Use after a jury or code review on a diff whose issue already carries an agreed plan. Not the first plan for an issue (that is `plan`).
disable-model-invocation: true
---

Produces an `### Iteration N` section on the issue's `## Plan` — what the implementer builds from, and what a later review judges the diff against. Nothing is implemented until this iteration is recorded.

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
- any change to what was already agreed: an earlier iteration, an Outcome bullet, or a `Not in scope` entry

## 6. Record

Append `### Iteration N` under `## Plan`. Do not rewrite earlier iterations. Name the file for each item. Include assumptions and what is not being taken. Leave the issue's status unchanged.
