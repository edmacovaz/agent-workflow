#!/usr/bin/env bash
# Delivers the working conventions as SessionStart context, replacing the stow-delivered
# ~/.claude/rules/agent-workflow.md that Claude Code used to load natively (LAB-80).
#
# Wired on `startup`, `compact` and `clear`, never on `resume`. The hook fires on every `--continue`,
# and the previous injection is still in the resumed conversation — measured — so a resume
# entry would add another copy of this file per resume, growing with the session.
#
# `compact` is not optional. additionalContext lives in the conversation, which compaction
# rewrites; measured twice, the rules survived only by being folded into the generated
# summary. That is lossy and model-dependent, so re-injecting on the boundary is what makes
# survival structural rather than lucky. `clear` starts a fresh conversation with nothing
# carried over, so it needs the same re-injection (LAB-80 review).
#
# Fails open, like the worktree guard beside it: an unreadable file or a Python that will not
# start emits `{}`, so a session begins without the conventions rather than not at all.
set -u

root=${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}
rules="$root/rules/agent-workflow.md"
[ -r "$rules" ] || { printf '{}\n'; exit 0; }

# The root, not a parsed version: an installed copy's path ends in its SHA, and a --plugin-dir
# session's names the worktree, whose basename alone would read as a version (LAB-97).
python3 - "$rules" "$root" 2>/dev/null <<'PY' || printf '{}\n'
import json, sys
body = f"The loop plugin in this session is loaded from `{sys.argv[2]}`.\n\n"
body += open(sys.argv[1], encoding="utf-8").read()
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": body,
}}))
PY
