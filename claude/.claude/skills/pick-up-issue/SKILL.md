---
name: pick-up-issue
description: Pick up or resume a Linear issue. Fetches the issue, checks out the correct branch, surfaces assumptions, and agrees a plan with the user before touching any code.
disable-model-invocation: true
---

Pick up Linear issue: $ARGUMENTS

## Current state
- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Recent commits: !`git log --oneline -5`

## Steps

### 1. Fetch the issue
Use the Linear MCP tool to fetch the issue by ID (e.g. EDM-179). Extract:
- Title, description, and any linked documents or attachments
- `gitBranchName` (format: `{title-slug}-{identifier}`)
- Current status

### 2. Orient to the branch
- If already on the correct branch, confirm and continue.
- If not, check it out. If the branch doesn't exist yet, create it from the latest `origin/master` after rebasing.
- If the branch can't be checked out for any reason, stop and tell the user before proceeding.
- Rename the current branch to match `gitBranchName` if needed (`git branch -m`).

### 3. Rebase onto master
Fetch and rebase onto `origin/master` to ensure work starts from the latest code.

### 4. Read before forming a view
Read the files most likely relevant to the issue — don't guess based on the title alone. Use Glob and Grep to find the actual code involved. Understand what exists before proposing what to change.

### 5. Start a conversation — do not write any code yet
Present the following to the user and wait for their input:

**What the issue asks for** — a plain-English summary of what needs to be done.

**What I found** — relevant files, existing patterns, anything that shapes the approach.

**Assumptions I'd need to make** — anything that isn't specified in the issue and can't be derived from the code. URLs, file paths, copy, external identifiers, design decisions. List each one explicitly. Do not silently pick a value and proceed.

**Proposed plan** — a concrete, ordered list of changes. Be specific about which files and what will change in each.

**Questions** — anything that needs the user's input before work can start.

### 6. Wait for confirmation
Do not edit, create, or delete any files until the user has read the plan, answered any questions, and explicitly said to proceed. A vague "ok" is enough — but the conversation must happen first.
