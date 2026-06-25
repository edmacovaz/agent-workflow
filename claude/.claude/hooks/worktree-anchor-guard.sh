#!/usr/bin/env bash
# Worktree-anchor guard — PreToolUse on Edit|Write|MultiEdit.
#
# Blocks editing a file that lives in a DIFFERENT work-tree of the SAME repo
# than the session's cwd — i.e. editing the main checkout (or a sibling
# worktree) from inside a worktree session. That mistake is otherwise silent:
# when both trees sit at the same commit the file exists identically in each,
# so the Read/Edit "succeeds" against the wrong tree and the slip only surfaces
# at `git branch` much later.
#
# Fails OPEN on anything uncertain (missing jq, non-git paths, git errors,
# different repos) so it never wedges legitimate work — the baseline is zero
# protection, so "occasionally doesn't fire" beats "occasionally blocks".

command -v jq >/dev/null 2>&1 || exit 0

input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -n "$file" ] && [ -n "$cwd" ] || exit 0

# The file may not exist yet (Write to a new path) — walk up to the nearest
# existing ancestor directory so git has something to resolve against.
dir=$(dirname "$file")
while [ -n "$dir" ] && [ ! -d "$dir" ]; do
  parent=$(dirname "$dir")
  [ "$parent" = "$dir" ] && break
  dir=$parent
done
[ -d "$dir" ] || exit 0

# Absolute, symlink-resolved common git dir (identifies the repo) and work-tree
# root (identifies which checkout). Going through `cd … && pwd -P` for both the
# file side and the cwd side keeps the comparison symlink-consistent on macOS
# (/tmp -> /private/tmp etc.), so equal/!= never misfire on path form alone.
common() { ( cd "$1" 2>/dev/null && cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P ); }
toplevel() {
  local t
  t=$( cd "$1" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null ) || return 1
  ( cd "$t" 2>/dev/null && pwd -P )
}

file_common=$(common "$dir");  [ -n "$file_common" ] || exit 0
cwd_common=$(common "$cwd");   [ -n "$cwd_common" ]  || exit 0
file_top=$(toplevel "$dir");   [ -n "$file_top" ]    || exit 0
cwd_top=$(toplevel "$cwd");    [ -n "$cwd_top" ]     || exit 0

# Same repo (shared common git dir) but different work-tree -> mis-anchored.
if [ "$file_common" = "$cwd_common" ] && [ "$file_top" != "$cwd_top" ]; then
  reason="Mis-anchored edit blocked (worktree guard). The target is in work-tree:
  $file_top
but this session is anchored to:
  $cwd_top
(same repo, different work-tree). Re-point the path to the current worktree — swap the '$file_top' prefix for '$cwd_top', then retry."
  jq -n --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
fi
exit 0
