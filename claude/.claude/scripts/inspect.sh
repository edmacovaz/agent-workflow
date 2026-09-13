#!/bin/sh
# Read-only repository inspection for jurors, exposed as fixed verbs.
#
# The verbs exist because opencode's bash permission is a pattern over command text, not a
# capability boundary: a pattern ending in a wildcard also matches a redirect, whose target is
# never path-checked, so `git log*` allowed `git log > /tmp/LAB56_REDIRECT_TEST` and created
# it. The allowlist names these invocations exactly, which a redirect cannot match — and the
# options carrying the same reach (`--output`, `--no-index`) are rejected here rather than
# enumerated there (LAB-56).
set -eu

usage() {
    cat <<'EOF'
inspect.sh — read-only repository inspection

  status            working tree and branch
  log               the last 20 commits, one line each
  diff              what this branch changes against its base, as a stat
  files             tracked files
  show <rev>        one commit, as a stat
  ignored <path>    which rule ignores a path, if one does
  help orca [cmd]   orca's own help, for checking a claim about its flags
EOF
}

# Every git primitive that reads or writes outside the repository arrives as an option:
# `--output=<path>` writes, `--no-index <path>` reads. Verbs take operands, never options.
operand() {
    case "${1-}" in
        "") echo "inspect.sh: missing argument" >&2; exit 2 ;;
        -*) echo "inspect.sh: arguments may not start with '-'" >&2; exit 2 ;;
    esac
}

verb="${1-}"
[ "$#" -gt 0 ] && shift

case "$verb" in
    status)
        exec git status --short --branch
        ;;
    log)
        exec git log --oneline --no-decorate -20
        ;;
    diff)
        # Against the base, not HEAD: a review runs on committed work, where `git diff HEAD` is
        # empty and a juror reads that silence as the artifact describing changes that are not
        # there (LAB-56).
        base=$(git merge-base origin/HEAD HEAD 2>/dev/null) || base=HEAD
        exec git diff --stat "$base"
        ;;
    files)
        exec git ls-files
        ;;
    show)
        operand "${1-}"
        exec git show --stat "$1"
        ;;
    ignored)
        operand "${1-}"
        # `--` so a path that looks like a revision is still read as a path
        exec git check-ignore -v -- "$1"
        ;;
    help)
        # `orca` alone: jurors reached for `orca worktree --help` to check a diff's claims about
        # its flags, and never once for git's — which they cannot run anyway (LAB-56).
        operand "${1-}"
        [ "$1" = "orca" ] || { echo "inspect.sh: help is available for orca only" >&2; exit 2; }
        shift
        # At most one noun. Anything longer builds a command path (`worktree rm <name> --help`),
        # which is safe only while orca keeps short-circuiting on --help before dispatch — a
        # property of another binary that nothing here pins (LAB-56).
        [ "$#" -le 1 ] || { echo "inspect.sh: help takes at most one orca command" >&2; exit 2; }
        [ "$#" -eq 0 ] || operand "$1"
        exec orca "$@" --help
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
