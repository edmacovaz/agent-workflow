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

# A juror's line is written every 60s, so a file older than this stopped being written to
# rather than being quiet between heartbeats.
STALE_AFTER = 150

# `LAB-83-diff-20260921-205609-54672` -> `LAB-83-diff`. The timestamp is what jury.py appends
# to make a run id unique, so it is the seam; everything before it is what the caller named.
RUN_ID = re.compile(r"^(.*?)-\d{8}-\d{6}")


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


# A juror stops being live when its row says it settled, however it settled. Kinds this does
# not know are ignored rather than guessed at, which is what let LAB-83's `spend` rows appear
# without this needing to be told about them.
SETTLED = ("returned", "absent", "timeout")


def render(path, now=None):
    """The status line for one run, or "" when there is nothing to say.

    Nothing is said once `settled` is in the file: a finished panel is not a running one, and
    the agent's own report is what carries it from there."""
    rows = rows_of(path)
    if not rows or any(r.get("kind") == "settled" for r in rows):
        return ""

    reported = {r.get("model") for r in rows if r.get("kind") in SETTLED}
    reported.discard(None)
    live = {}
    for r in rows:
        if r.get("kind") == "working" and r.get("model") not in reported:
            live[r["model"]] = r.get("message", "")

    dispatched = next((r["message"] for r in rows if r.get("kind") == "dispatched"), "")
    head = re.match(r"\s*(\d+)", dispatched)
    # the count of models dispatched, falling back to what has been seen: a panel that named
    # no total is still worth rendering, and `N of ?` says which half is missing
    total = head.group(1) if head else (len(reported | set(live)) or "?")

    run = os.path.basename(path)[: -len(".progress.jsonl")]
    name = RUN_ID.match(run)
    out = [f"⚖ {name.group(1) if name else run} — {len(reported)} of {total} reported"]

    try:
        age = int((now or time.time()) - os.path.getmtime(path))
    except OSError:
        age = 0
    if age > STALE_AFTER:
        # a runner that died leaves its last state behind looking live, and a display that
        # simply vanished would read as a panel that finished
        out[0] += f" · last change {age // 60}m ago"

    # the runner's own line, verbatim. Reformatting it here would be a second copy of
    # working_line()'s format, free to drift from the one jury.py actually writes.
    out += [f"  {message}" for message in live.values() if message]
    return "\n".join(out)


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
