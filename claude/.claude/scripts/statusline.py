#!/usr/bin/env python3
"""Render a running panel's state into the Claude Code status line.

LAB-75 took the 60s heartbeats out of stdout so a panel stops costing a turn per line. They
still reach `agents/out/<run>.progress.jsonl`; this renders that record where the caller can
see it without asking and without the agent speaking (LAB-86).

The status line is the surface because it is the only one that costs nothing. Measured 21 Sep
2026: it ticks while the agent sleeps, while a background subagent absorbing the same 45 lines
spent ~48k tokens per line — including the heartbeats it was told to say nothing about, because
a Monitor event forces a turn whether or not the agent speaks.

The slot this runs in was Orca's: its script POSTs the same payload to Orca's hook port so the
pane knows what the session is doing, then prints nothing. Taking the slot without forwarding
would cost every Claude session on the machine its pane telemetry — so the settings command
pipes the payload to Orca's script *first* and to this second. Deliberately there rather than
here: `~/.claude/scripts/` resolves to the main checkout, so this file does not exist on a
machine where the change has not merged yet, and a forward that lived in it would take Orca's
telemetry down with it. Measured on 21 Sep 2026, by doing exactly that.

Read on stdin: Claude Code's status-line payload. Written to stdout: nothing at all when no
panel is running, or a header line plus one line per juror still working.
"""
import json, os, re, sys, time

# `LAB-83-diff-20260921-205609-54672` -> `LAB-83-diff`. The run id is built by the jury skill as
# `<ISSUE>-<timestamp>-<pid>`; jury.py takes `--run-id` verbatim and falls back to a bare
# `<timestamp>-<pid>`, which this deliberately does not match — there is no name in it to show.
RUN_ID = re.compile(r"^(.+)-\d{8}-\d{6}")

# Only a juror that wrote a verdict has *reported*. `absent` and `timeout` settle a juror
# without one, and the jury skill keeps those apart for the same reason: a panel where every
# juror died must never read as four verdicts landing.
REPORTED = ("returned",)
SETTLED = ("returned", "absent", "timeout")

# Fallbacks, used only for a file written before jury.py recorded `artifact` and `pid`. Both
# are guesses at facts the runner now states outright, so neither governs a current run.
STALE_AFTER = 150            # a juror line is written every 60s
ABANDONED_AFTER = 40 * 60    # past the runner's own 30-minute backstop, nothing is coming


def newest_progress(payload):
    """The run to render: the most recently written progress file under the session's own
    directories. `agents/out` is relative to wherever the runner was invoked, which is the
    session's cwd, so those are the only two places to look."""
    workspace = payload.get("workspace") or {}
    seen, found = set(), []
    for key in ("current_dir", "project_dir"):
        d = workspace.get(key)
        if not d or d in seen:
            continue
        seen.add(d)
        out = os.path.join(d, "agents", "out")
        try:
            names = os.listdir(out)
        except OSError:
            continue
        for name in names:
            if name.endswith(".progress.jsonl"):
                path = os.path.join(out, name)
                try:
                    found.append((os.path.getmtime(path), path))
                except OSError:
                    pass
    return max(found)[1] if found else None


def rows_of(path):
    """Every line the runner has written so far.

    A torn final line is normal rather than exceptional: the runner appends while this reads,
    and both happen several times a minute. It is skipped, and everything before it still
    renders — a half-written line must never cost the caller the whole display."""
    rows = []
    try:
        fh = open(path)
    except OSError:
        return rows
    with fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def current_artifact(rows):
    """The rows belonging to the artifact being reviewed now.

    One progress file covers a whole run, and a run reviews each `--artifact` in turn with the
    same four models. Reading the file as one panel made artifact 1's settled jurors count
    against artifact 2 — every live juror filtered out, the header frozen at `4 of 4`, for up
    to the backstop. `artifact` on each row is jury.py saying which is which (LAB-86)."""
    named = [r for r in rows if r.get("artifact")]
    if not named:
        return rows                  # a file from before the field existed: one panel, as read
    return [r for r in rows if r.get("artifact") == named[-1]["artifact"]]


def is_running(rows, path, now):
    """Whether the panel is still alive, and how stale its last line is.

    A SIGKILLed runner writes no `settled` — that is written in a `finally`, which SIGKILL
    skips — and nothing prunes `agents/out`, so its file stays the newest one in the directory.
    Asking the OS about the runner's pid answers this outright; mtime only ever guessed, and
    guessed for up to half an hour (LAB-86)."""
    age = int(now - os.path.getmtime(path))
    pid = next((r["pid"] for r in reversed(rows) if isinstance(r.get("pid"), int)), None)
    if pid is None:
        return age < ABANDONED_AFTER, age      # pre-`pid` file: the old guess, bounded
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, age
    except OSError:
        pass                         # EPERM: a live process this user may not signal
    return True, age


def render(path, now=None):
    """The status line for one run, or "" when there is nothing to say.

    Nothing is said once `settled` is in the file: a finished panel is not a running one, and
    the agent's own report is what carries it from there."""
    rows = rows_of(path)
    if not rows or any(r.get("kind") == "settled" for r in rows):
        return ""
    now = time.time() if now is None else now
    try:
        running, age = is_running(rows, path, now)
    except OSError:
        return ""
    if not running:
        return ""
    rows = current_artifact(rows)

    settled = {r.get("model") for r in rows if r.get("kind") in SETTLED}
    settled.discard(None)
    reported = {r.get("model") for r in rows if r.get("kind") in REPORTED}
    reported.discard(None)
    live = {}
    for r in rows:
        if r.get("kind") == "working" and r.get("model") not in settled:
            live[r["model"]] = r.get("message", "")

    dispatched = next((r["message"] for r in rows if r.get("kind") == "dispatched"), "")
    head = re.match(r"\s*(\d+)", dispatched)
    # the count of models dispatched, falling back to what has been seen: a panel that named
    # no total is still worth rendering, and `N of ?` says which half is missing
    total = head.group(1) if head else (len(settled | set(live)) or "?")

    run = os.path.basename(path)[: -len(".progress.jsonl")]
    name = RUN_ID.match(run)
    line = f"⚖ {name.group(1) if name else run} — {len(reported)} of {total} reported"
    absent = len(settled) - len(reported)
    if absent > 0:
        line += f", {absent} absent"
    if age > STALE_AFTER:
        # the runner is alive but has not written for minutes; say so rather than showing a
        # stale juror line as though it were current
        line += f" · last change {age // 60}m ago"

    # the runner's own line, verbatim, and unindented: the status line renders each line
    # through `d.trim()`, so leading space is dropped before anyone sees it.
    return "\n".join([line] + [m for m in live.values() if m])


def main():
    try:
        parsed = json.loads(sys.stdin.read())
    except ValueError:
        return
    path = newest_progress(parsed)
    if not path:
        return
    line = render(path)
    if line:
        print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # The slot runs this several times a minute in every session on the machine. A
        # traceback in it would be noise in a place the caller cannot dismiss, and the panel
        # display is never worth that.
        pass
