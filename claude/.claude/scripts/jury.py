#!/usr/bin/env python3
"""Dispatch a panel of opencode jurors through Orca orchestration and collect verdicts.

Each juror is a long-lived terminal pinned to one model, re-engaged with a fresh
Dispatch per artifact rather than rebuilt. Deliveries are acknowledged as they are
processed: an unacknowledged batch replays on the next check and is indistinguishable
from a fresh result, which would let a stale verdict pass for a current one.

Orca owns placement, state and stop rules; this runner owns none of them. It asks what
each worker is doing and passes the answer through — it does not decide from a clock that
a worker is finished, and it does not read a transcript to decide whether one is stuck.
"""
import argparse, datetime, json, os, shutil, subprocess, sys, time


def event(msg):
    """Wake the caller. Monitor renders only its own description, never these lines, so a
    wake means only "something changed, go and look".

    What changed is no longer only the reports directory: progress() routes heartbeat,
    state-change, stale and question lines through here too, and none of those is a
    file appearing. The rule is one line per change and nothing between changes — a wake
    the caller cannot account for is the silence this replaced."""
    print(msg, flush=True)


# Set once per run. The progress file lives beside the reports so the directory the caller
# already watches is the one that changes; no second watch is needed.
PROGRESS = {"path": None}


def progress(kind, message, **fields):
    """One caller-facing line: printed to wake Monitor, and appended to the run's progress
    file so that *what* changed can actually reach the caller.

    Monitor renders only its own description, so a wake says "something changed" and no
    more. Before this, the only thing a waiting caller could see was which report files had
    appeared — never that a juror was alive and working, which is the one thing they are
    waiting to know. Iteration 1 removed the false "time remains" signal without adding the
    true one.

    Flushed per line: a buffered write would leave the caller watching an empty file until
    the run ended, which is the silence this replaces. A progress line is never worth ending
    a run for, so a write that fails is dropped."""
    event(message)
    path = PROGRESS["path"]
    if not path:
        return
    row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "message": message}
    row.update({k: v for k, v in fields.items() if v is not None})
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(row) + "\n")
            fh.flush()
    except OSError:
        pass

# Four distinct families, deliberately. `ox-alpha-free` sat here for five runs and does
# not exist: opencode fell back to the agent's declared model, so the panel was luna twice
# and nothing said so. Hence check_models below.
PANEL = ["opencode-go/gpt-5.6-luna", "opencode-go/deepseek-v4-flash",
         "opencode-go/qwen3.7-plus", "opencode-go/glm-5.3-flash"]

# opencode retitles its own terminal from the task it is given, overwriting whatever
# --title we pass, so a title can never identify a terminal. Handles are the only
# stable identity, and they die with the process unless written down — hence these files,
# which let a later run reclaim terminals a crashed one leaked. One per run, stamped with
# the pid, so concurrent runs neither clobber each other nor reclaim each other's live
# terminals. They also carry the Orca run and its dispatch ids, which is what lets a later
# run settle the records a crashed one abandoned.
STATE_DIR = ".terminals"

SPEC = ("Review the artifact at {artifact} against the intent at {intent}. Both are inside this "
        "worktree; read them, and read any repository files needed to check the artifact's claims. "
        "Judge fit against the intent, and form against the `{standard}` standard — load it with the "
        "skill tool and judge against what it actually says. Label every finding with its dimension. "
        "Write your findings JSON to {report}, then report worker_done with --outcome succeeded and "
        "--report-path {report}")

# One wait window. Inspection happens between windows, so this is how long the runner can
# go without asking Orca anything — not how long a juror is allowed to take.
WINDOW_MS = 60000

# A worker Orca still calls `ready` that has been silent this long is a case to read, not a
# verdict to reach. The runner captures it and says so; the caller decides.
STALE_HEARTBEAT_S = 300

# Orca completes a dispatch *because* a valid worker_done arrived, so a dispatch reading
# `succeeded` is notification that the message exists, not evidence in its own right. This
# is how long the runner waits for it before writing the completion down itself. Without
# the wait the two race, inspection wins whenever it happens to be mid-round, and the
# message is then discarded unread — which is how a whole panel returned no count (LAB-58).
COMPLETION_GRACE_S = 120

# A backstop, not a stop rule. Orca treats 15-60 minutes as ordinary for real work, and
# the old 7 minutes was a competing stop rule that reported working jurors as silent.
DEFAULT_TIMEOUT_MS = 1800000

# A juror blocked on `ask` waits for a coordinator that is a script and cannot answer it.
# Saying so costs one message; leaving it blocked costs the whole backstop.
NO_ANSWER = ("No coordinator is available to answer questions on this run. Review with what "
             "you have and report worker_done, or send an escalation if you cannot.")


def decode(text):
    """The receipt is one JSON object. None means this was not JSON at all, which is a
    different thing from an error receipt and has to be reported differently."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def drop_keepalives(text):
    """`--wait` streams `{"_keepalive":true,...}` to stderr every 15 seconds. They are
    liveness, not output, and a tail of them buries whatever else was said."""
    return "\n".join(line for line in (text or "").splitlines()
                     if line.strip() and '"_keepalive"' not in line).strip()


def failure_reason(body, stdout, stderr):
    """Orca reports failures as JSON on stdout with exit 1, and puts nothing on stderr but
    the keepalive stream. Reading stderr first therefore reports a heartbeat as the reason
    for any failure that waited longer than 15 seconds: LAB-38-20260830-125849 died with
    180 seconds of `{"_keepalive":true,...}` where its error should have been (LAB-47)."""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            parts = [p for p in (err.get("code"), err.get("message")) if p]
            if parts:
                return ": ".join(str(p) for p in parts)
        if isinstance(err, str) and err.strip():
            return err.strip()
    return (drop_keepalives(stderr) or (stdout or "").strip() or "no output")[-400:]


def orca(*args, timeout=120):
    proc = subprocess.run(["orca", *args, "--json"], capture_output=True, text=True, timeout=timeout)
    body = decode(proc.stdout)
    op = " ".join(args[:2])
    if proc.returncode != 0:
        raise RuntimeError(f"orca {op} failed: {failure_reason(body, proc.stdout, proc.stderr)}")
    if body is None:
        # exit 0 with something that is not a receipt: say what arrived rather than
        # raising a decoder error that names a column instead of a cause
        raise RuntimeError(f"orca {op} returned unreadable output: "
                           f"{(proc.stdout or '').strip()[:400] or 'nothing'}")
    return body.get("result", {})


def read_report(path):
    """Returns a juror row for a report file, or None if it is not there. A file that will
    not parse keeps its text: a real finding should not vanish with the parse failure."""
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path))
    except Exception as exc:
        row = {"parse_ok": False, "error": f"unreadable report: {exc}"}
    else:
        if is_report(data):
            return {"parse_ok": True, "report": data}
        row = {"parse_ok": False, "error": "not a juror report"}
    try:
        with open(path) as fh:
            row["raw"] = fh.read(4000)
    except OSError:
        pass
    return row


def salvage(out, run_id, artifact, models):
    """Recover verdicts a crashed run already collected. The settle file is the caller's
    only record, and a crash inside collect() would otherwise hand them an empty one
    sitting next to perfectly good report files."""
    name = os.path.basename(artifact).replace(".md", "")
    rows = []
    for model in models:
        row = read_report(report_path(out, run_id, name, model))
        if row:
            rows.append(dict(model=model, salvaged=True, **row))
    return rows


def check_models(models):
    """An unresolvable model id does not fail the dispatch — opencode falls back to the
    agent's declared model and the panel quietly becomes that model twice. Five runs went
    by before a juror's own session gave it away, so the ids are checked before spending."""
    # homebrew's bin is missing from PATH in some Claude Code sessions, and a lookup that
    # fails here would abort every run rather than the bad ones
    exe = shutil.which("opencode") or next(
        (c for c in ("/opt/homebrew/bin/opencode", "/usr/local/bin/opencode",
                     os.path.expanduser("~/.opencode/bin/opencode")) if os.path.exists(c)), None)
    if not exe:
        raise RuntimeError("cannot find the opencode binary; cannot verify juror models")
    proc = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        # else an empty stdout blames every model for the command having failed
        raise RuntimeError(f"`opencode models` failed: {proc.stderr[-300:]}")
    known = set(proc.stdout.split())
    unknown = [m for m in models if m not in known]
    if unknown:
        raise RuntimeError(f"unknown model(s): {', '.join(unknown)} — see `opencode models`")


def resolve_worktree(root):
    """Orca's bare `current` selector resolves the terminal *pane's* identity, stamped when
    the pane was created and never reconciled with the process's working directory. A
    session whose pane was made in another repo dispatches jurors into that repo — or fails
    outright once that worktree is gone, which is how this was found. `worktree current`
    answers from the directory instead (LAB-46)."""
    wt = orca("worktree", "current")["worktree"]
    if os.path.realpath(wt["path"]) != os.path.realpath(root):
        raise RuntimeError(
            f"Orca resolves this directory to {wt['path']}, but the repository root is "
            f"{root} — jurors would run against the wrong repository")
    return wt["id"]


def report_path(out, run_id, name, model):
    return f"{out}/{run_id}.{name}.{model.split('/')[-1]}.json"


def is_finding(f):
    return (isinstance(f, dict) and f.get("dimension") in ("fit", "form")
            and f.get("severity") in ("blocker", "should-fix", "nit")
            and f.get("claim") and f.get("evidence"))


def is_report(obj):
    """A parseable file is not a report and an unlabelled finding is not a finding.
    Counting either as a verdict is the same error as counting silence as approval, which
    this whole run exists to avoid. Strict on purpose: one bad finding costs the report,
    but the raw text is kept, so nothing is lost except the count."""
    return (isinstance(obj, dict) and obj.get("verdict") in ("pass", "revise", "block")
            and isinstance(obj.get("findings"), list)
            and all(is_finding(f) for f in obj["findings"]))


def payload_of(msg):
    p = msg.get("payload") or {}
    return json.loads(p) if isinstance(p, str) else p


def model_of(meta):
    return meta["model"] if isinstance(meta, dict) else meta


def age_seconds(stamp):
    """`last_heartbeat_at` comes back as 'YYYY-MM-DD HH:MM:SS' in UTC. None rather than 0
    for an absent or unparseable stamp: 'no heartbeat yet' and 'a heartbeat just now' are
    opposite answers to the only question this field is asked."""
    if not stamp:
        return None
    try:
        t = datetime.datetime.strptime(str(stamp).replace("T", " ").rstrip("Z"),
                                       "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return max(0.0, (now - t).total_seconds())


def classify(info):
    """Read all of what Orca said, not one field of it.

    `worker.state` alone left a dispatch Orca had already marked `failed` sitting `ready`
    until the backstop — thirty minutes, where the deadline it replaced would have given up
    after seven. Both fields are answers to different questions and the pair is what the
    plan named.

    Anything not proven otherwise is alive. An inspection that returns nothing is not
    evidence a juror died — orcastra's rule, and the one the 7-minute deadline broke: if
    you cannot verify it, do not infer it."""
    state = (info or {}).get("state")
    status = (info or {}).get("dispatchStatus")
    if state in ("failed", "stopped", "abandoned") or status == "failed":
        return "dead"
    # `completed` before `outcome_unknown`: Orca completes a dispatch on a valid
    # worker_done, so a completed dispatch has succeeded whatever its worker state reads.
    # Checked the other way round, it routed into resolve_unknown, which stopped a finished
    # worker — and the post-stop inspection then read `stopped`, which is dead, so the
    # juror's verdict was recorded as a failure.
    if state == "succeeded" or status == "completed":
        return "succeeded"
    if state == "outcome_unknown":
        return "unknown"
    return "alive"


def worker_show(dispatch):
    """What Orca says about one worker. `last_heartbeat_at` is why this is enough to answer
    'is it stalled' without reading a transcript: the phase the juror reported reaches us
    as a timestamp, consuming no messages and requiring no interpretation."""
    r = orca("orchestration", "worker-show", "--dispatch", dispatch)
    d, w = r.get("dispatch") or {}, r.get("worker") or {}
    return {"state": w.get("state"), "stage": w.get("stage"),
            "dispatchStatus": d.get("status"), "failure": d.get("last_failure"),
            "heartbeat": d.get("last_heartbeat_at"),
            "heartbeat_age": age_seconds(d.get("last_heartbeat_at"))}


def worker_read(dispatch, limit=40):
    """Bounded output for a worker whose state is ambiguous — evidence for a judgement this
    runner does not make. Best effort: failing to collect it must not end the panel.

    Must be taken while the terminal is alive. Orca preserves an inspectable archive when
    it releases a worker it owns, but jury terminals are external to it, so once we close
    one `worker-read` answers `worker_identity_changed` and the output is gone.

    The row shape is not pinned down here: Orca returns a proven transcript for the agents
    it hooks (Codex, Claude, OpenClaude, Grok) and labelled terminal output with a typed
    `fallbackReason` otherwise, which is the path opencode takes."""
    try:
        r = orca("orchestration", "worker-read", "--dispatch", dispatch, "--limit", str(limit))
    except Exception as exc:
        return {"error": str(exc)}
    rows = r.get("rows") or r.get("lines") or r.get("output") or r.get("text") or ""
    if isinstance(rows, list):
        rows = "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in rows)
    return {"source": r.get("source"), "fallbackReason": r.get("fallbackReason"),
            "excerpt": str(rows)[-2000:]}


def worker_release(dispatch):
    """Settles one worker's terminal accounting. Only `release_unknown` is a failure;
    `retained`, `release_pending` and `already_released` all succeed.

    Jury terminals always come back `retained`. The runner creates them itself and passes
    `--terminal`, so Orca records the resource as `external` and will not close something
    it does not own — close_terminal below remains what frees them. The call is bookkeeping,
    and bookkeeping is the thing that was missing."""
    try:
        r = orca("orchestration", "worker-release", "--dispatch", dispatch)
    except Exception as exc:
        return f"release failed: {exc}"
    state = r.get("terminalState") or r.get("releaseState")
    if state == "release_unknown":
        # Orca exits 1 on this today, so the raise above catches it — but depending on an
        # exit code to enforce what this function promises leaves the promise unmade if a
        # receipt ever arrives with exit 0
        return "release failed: release_unknown"
    # never the word "released": run LAB-49-20260830-183854 recorded `release=released`
    # for four workers whose terminals Orca had retained as external, which is the same
    # habit of claiming more than Orca said that this whole issue is about
    return state or "release accepted"


def quietly(*args):
    """A settle step whose failure is worth recording and never worth raising."""
    try:
        orca(*args)
        return None
    except Exception as exc:
        return str(exc)


def resolve_unknown(dispatch, who, info):
    """`outcome_unknown` is not an outcome. Orca's recovery is to stop and inspect again,
    or to abandon and accept that resources may still be live. A stop that does not take is
    itself the thing to report, not a silence to pass on."""
    info = dict(info)
    stop_failed = quietly("orchestration", "worker-stop", "--dispatch", dispatch)
    if stop_failed:
        info["stop_error"] = stop_failed
    try:
        after = worker_show(dispatch)
    except Exception:
        after = {}
    kind = classify(after) if after else "unknown"
    if kind == "succeeded":
        # a stop can reveal a juror that had already finished. Calling that failed reports
        # the wrong outcome for a juror whose verdict is on disk
        info.update(after)
        progress("succeeded", f"{who} — was outcome_unknown, stopped, and Orca reports it "
                 f"succeeded", state=after.get("state"))
        return dict(info, result="done", outcome="succeeded", reconstructed=True,
                    note="revealed as succeeded by the stop; its worker_done was not "
                         "observed by this runner")
    if kind == "dead":
        info.update(after)
        progress("stopped", f"NO REPORT from {who} — was outcome_unknown, stopped, now "
                 f"{after.get('state')}", state=after.get("state"))
        return dict(info, result="failed")
    abandon_failed = quietly("orchestration", "worker-abandon", "--dispatch", dispatch)
    note = (f"abandon failed: {abandon_failed}" if abandon_failed
            else "abandoned after outcome_unknown; resources may still be live")
    progress("abandoned", f"NO REPORT from {who} — {note}")
    return dict(info, result="abandoned", note=note)


def handle_message(m, dispatches, settled, watch, seen):
    """Only `worker_done` and `escalation` settle a juror.

    Keying off the payload alone settled it on anything carrying a dispatch id, and a
    `heartbeat` carries exactly the same taskId/dispatchId pair — which is how a juror that
    had sent nothing but a heartbeat was announced as returned while its task sat `ready`
    and its report was never written (LAB-48).

    The one exception is a `worker_done` for a record marked `reconstructed` — one the
    runner built from Orca's state precisely because the message had not arrived. The
    message outranks it and corrects it."""
    # a Delivery replays until it is acknowledged. `d in settled` guards only the types
    # that settle, so a replayed heartbeat emitted a duplicate line and a replayed question
    # was answered twice.
    mid = m.get("id")
    if mid:
        if mid in seen:
            return
        seen.add(mid)
    kind, p = m.get("type"), payload_of(m)
    d = p.get("dispatchId")
    if d not in dispatches:
        return
    # a settled dispatch is closed to everything but the one message that outranks how it
    # was settled: a worker_done over a completion the runner reconstructed without it.
    late = d in settled
    if late and not (kind == "worker_done" and settled[d].get("reconstructed")):
        return
    who = model_of(dispatches[d]).split("/")[-1]
    if kind == "worker_done":
        settled[d] = {"result": "done", "type": kind, "outcome": p.get("outcome"),
                      "reportPath": p.get("reportPath"), "body": m.get("body")}
        progress("returned", f"{who} reported done — {len(settled)} of {len(dispatches)}"
                 + (" (its message arrived after the runner wrote it down itself)"
                    if late else ""),
                 model=model_of(dispatches[d]), outcome=p.get("outcome"),
                 late=late or None)
    elif kind == "escalation":
        settled[d] = {"result": "escalated", "type": kind, "body": m.get("body")}
        progress("escalated", f"NO REPORT from {who} — escalated",
                 model=model_of(dispatches[d]))
    elif kind == "question":
        # it is blocked on an answer no script can give; leaving it blocked burns the
        # whole backstop, so say so and let it finish or escalate
        failed = quietly("orchestration", "reply", "--id", m.get("id") or "", "--body", NO_ANSWER)
        watch.setdefault(d, {})["question"] = m.get("body") or m.get("subject")
        progress("question",
                 f"{who} asked a question — answered that no coordinator is available"
                 if not failed else
                 f"{who} asked a question and could not be answered: {failed}",
                 model=model_of(dispatches[d]))
    elif kind == "heartbeat" and p.get("phase"):
        # not a settle (LAB-48) — but the phase is the answer to "is this stalled", so it
        # goes to the caller now rather than only in the settle file
        watch.setdefault(d, {})["phase"] = p.get("phase")
        progress("heartbeat", f"{who} — {p['phase']}", model=model_of(dispatches[d]),
                 phase=p.get("phase"))


def inspect_round(dispatches, settled, watch, deadline):
    """Ask Orca what every unsettled worker is doing, and say something only when the answer
    changed. Every line here costs the caller a Monitor wake, so silence between changes is
    deliberate — but a silence the caller cannot explain is what this replaces, and the
    explanation is now the worker's own state rather than a countdown.

    `deadline` is the run's backstop, and it bounds the completion grace below: a wait that
    outlived it would hand the caller `unsettled` for a juror Orca had proved finished, and
    settle_all would then stop a dispatch that had already completed."""
    for d, meta in dispatches.items():
        if d in settled:
            continue
        who = model_of(meta).split("/")[-1]
        try:
            info = worker_show(d)
        except Exception as exc:
            watch.setdefault(d, {})["inspection_error"] = str(exc)
            continue                             # cannot ask: keep waiting, never conclude
        prev = watch.get(d) or {}
        kind = classify(info)
        if kind == "dead":
            reason = f"Orca reports {info.get('state')}"
            if info.get("failure"):
                reason += f": {info['failure']}"
            settled[d] = dict(info, result="failed")
            progress("failed", f"NO REPORT from {who} — {reason}", model=model_of(meta),
                     state=info.get("state"), dispatchStatus=info.get("dispatchStatus"))
        elif kind == "unknown":
            settled[d] = resolve_unknown(d, who, info)
        elif kind == "succeeded":
            # the dispatch completed, so its worker_done reached Orca and is on its way
            # here. Wait for it rather than settling: the message carries the outcome, the
            # report path and the juror's own summary, and a dispatch settled here is one
            # the message can no longer be counted for.
            now = time.monotonic()
            seen_at = prev.get("completed_seen_at", now)
            watch[d] = {**prev, **info, "completed_seen_at": seen_at}
            if now - seen_at < COMPLETION_GRACE_S and now < deadline:
                continue                     # not silence: a message known to be in flight
            # it never came. Reconcile rather than carrying it to the backstop and calling
            # it silence, but say that this is the runner's own reconstruction — which is
            # what makes the line worth reading when it does appear.
            settled[d] = dict(info, result="done", outcome="succeeded",
                              reconstructed=True,
                              note="Orca reports the dispatch succeeded; no worker_done "
                                   f"arrived in the {COMPLETION_GRACE_S}s after")
            progress("succeeded", f"{who} — Orca reports it succeeded, but no worker_done "
                     f"arrived in {COMPLETION_GRACE_S}s", model=model_of(meta),
                     state=info.get("state"))
        else:
            age = info.get("heartbeat_age")
            if age is not None and age >= STALE_HEARTBEAT_S and not prev.get("stale_reported"):
                info["needs_reading"] = worker_read(d)
                info["stale_reported"] = True
                progress("stale", f"{who} — Orca still reports "
                         f"{info.get('state') or 'working'}, last heartbeat {int(age)}s ago",
                         model=model_of(meta), state=info.get("state"),
                         heartbeat_age=int(age), phase=prev.get("phase"))
            elif prev.get("state") and info.get("state") != prev.get("state"):
                progress("state", f"{who} — now {info.get('state')}", model=model_of(meta),
                         state=info.get("state"))
            watch[d] = {**prev, **info}


def collect(dispatches, timeout_ms, run):
    """Wait on Orca's signals, and between waits ask it what each worker is doing.

    Scoped to `run`: an unscoped check returns whatever is queued and acks the whole
    delivery, so a concurrent panel's worker_done would be swallowed here and that juror
    recorded absent.

    What ends the wait is every dispatch settling — by a worker_done, by an escalation, by
    a failure Orca proves, or by a stop this runner asked for. The deadline is a backstop:
    a worker Orca still calls `ready` is working, and stopping to tell the caller that time
    ran out says nothing about the juror.

    Returns a record for every dispatch, including the ones still running at the backstop —
    absence is never left to be inferred by whoever reads this."""
    settled, watch, ack, seen = {}, {}, None, set()
    deadline = time.monotonic() + timeout_ms / 1000
    while len(settled) < len(dispatches):
        now = time.monotonic()
        if now >= deadline:
            break
        wait_ms = int(max(1.0, min(WINDOW_MS / 1000.0, deadline - now)) * 1000)
        args = ["orchestration", "check", "--run", run, "--wait",
                "--types", "worker_done,escalation,question", "--timeout-ms", str(wait_ms)]
        if ack:
            # append, never splice at an index: adding --run silently moved the old
            # insertion point onto its value and broke every poll after the first
            args += ["--ack", ack]               # ack the previous batch as we wait for the next
        r = orca(*args, timeout=wait_ms / 1000 + 60)
        if r.get("deliveryId"):                  # a window may time out with nothing to ack
            ack = r["deliveryId"]
        for m in r.get("messages") or []:
            handle_message(m, dispatches, settled, watch, seen)
        inspect_round(dispatches, settled, watch, deadline)
    if ack:
        # a failed closing ack must not cost the verdicts already collected
        quietly("orchestration", "check", "--run", run, "--ack", ack)
    for d in dispatches:                         # what the backstop found, not that it expired
        rec = settled.get(d) or dict(watch.get(d) or {}, result="unsettled")
        rec.update({k: v for k, v in (watch.get(d) or {}).items() if k not in rec})
        settled[d] = rec
    return settled


def settle_all(records):
    """Settle every dispatch before any terminal closes.

    Closing first is what produced `stage: terminal_missing` and "The assigned worker
    terminal is no longer live after orchestration recovery" on LAB-38-20260830-125849:
    Orca was not reaping a crashed coordinator, it was reacting to this runner closing a
    live worker's terminal out from under it."""
    for d, rec in records.items():
        if rec.get("result") in (None, "unsettled"):
            failed = quietly("orchestration", "worker-stop", "--dispatch", d)
            if not failed:
                rec["settled_by"] = "stopped at the backstop"
            else:
                abandon_failed = quietly("orchestration", "worker-abandon", "--dispatch", d)
                rec["settled_by"] = (f"stop failed ({failed}); abandon failed: {abandon_failed}"
                                     if abandon_failed else f"abandoned; stop failed: {failed}")
        rec["release"] = worker_release(d)


def close_terminal(handle):
    subprocess.run(["orca", "terminal", "close", "--terminal", handle, "--json"],
                   capture_output=True, text=True)


def ensure_ignored(root):
    """Reports must be uncommittable in a fresh clone, not merely on a machine whose global
    git config happens to ignore agents/. A directory that ignores itself needs no
    cooperation from the repository it lands in.

    Append rather than write: writing only when absent leaves reports committable behind a
    .gitignore that ignores something else, and truncating destroys rules the repository
    put there. Both were filed as findings; neither extreme is right."""
    os.makedirs(root, exist_ok=True)
    marker = os.path.join(root, ".gitignore")
    try:
        with open(marker) as fh:
            existing = fh.read()
    except OSError:
        existing = None
    if existing is None:
        with open(marker, "w") as fh:
            fh.write("*\n")
    elif "*" not in existing.split():
        with open(marker, "a") as fh:
            fh.write("" if existing.endswith("\n") or not existing else "\n")
            fh.write("*\n")


def record_handles(path, handles, run=None, dispatches=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"pid": os.getpid(), "handles": sorted(handles),
                   "run": run, "dispatches": sorted(dispatches)}, fh)


def running(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def settle_abandoned_run(run, dispatches):
    """Close the books on a run whose coordinator died.

    Orca reclaims worker *terminals* on its own. It does not settle task or dispatch
    records, and nothing else did either: 26 of them accumulated across 18 runs, the oldest
    four days stale, and were cleared by hand.

    Records only — `worker-abandon` performs no process or filesystem action, which is the
    right instrument for a run this process does not own and whose terminals may already
    belong to someone else.

    Must run before this run's own run-create. `run-use` rebinds the coordinator terminal,
    and binding another run while a panel of ours was waiting would fence it outright:
    `consumer_fenced: This coordinator terminal is bound to <other run>`."""
    if not run or not dispatches:
        return
    if quietly("orchestration", "run-use", "--id", run):
        return                                   # cannot bind it: leave its records alone
    for d in dispatches:
        try:
            state = classify(worker_show(d))
        except Exception:
            state = None            # cannot ask: still settle it. Release is bookkeeping,
        if state not in ("dead", "succeeded"):   # and bookkeeping is what was missing.
            quietly("orchestration", "worker-abandon", "--dispatch", d)
        worker_release(d)


def reclaim_orphans(state_dir, mine):
    """Close terminals a previous run left behind, and settle what it left in Orca. Titles
    cannot identify them, so the handles are read back from disk. A run whose pid is still
    alive is left alone: pid reuse then leaks a terminal rather than closing a live panel's.
    Silent — reclaiming is not news, and every line here costs the caller a wake."""
    if not os.path.isdir(state_dir):
        return
    for entry in sorted(os.listdir(state_dir)):
        path = os.path.join(state_dir, entry)
        if path == mine:
            continue
        try:
            with open(path) as fh:
                stale = json.load(fh)
        except (json.JSONDecodeError, OSError):
            stale = {}
        if running(stale.get("pid")):
            continue
        settle_abandoned_run(stale.get("run"), stale.get("dispatches") or [])
        for h in stale.get("handles") or []:
            close_terminal(h)
        try:
            os.remove(path)
        except OSError:
            pass                                 # another run reclaimed the same entry first


def absence_reason(rec):
    """Why a juror's verdict is missing, in Orca's words.

    Never "never reported": that is the inference this whole issue exists to stop. Three of
    four jurors on LAB-38-20260830-125849 were still `ready` when they were written down as
    silent."""
    result = rec.get("result")
    if result == "escalated":
        return "escalated"
    if result == "failed":
        reason = f"Orca reports {rec.get('state') or 'failed'}"
        return f"{reason}: {rec['failure']}" if rec.get("failure") else reason
    if result == "abandoned":
        return rec.get("note") or "abandoned after outcome_unknown"
    if result == "done":
        return "reported done but wrote no report"
    state = rec.get("state")
    if classify(rec) == "succeeded":
        # Orca completed the dispatch and the message had not arrived; neither half is this
        # runner's to assert without the other. Asked through classify so it cannot drift
        # from the branch that produced the record — `completed` with `outcome_unknown` is
        # a real state, and reading `state` alone called that one "still outcome_unknown".
        return ("Orca reports the dispatch succeeded; its worker_done had not arrived "
                "when the backstop expired")
    if state:
        line = f"still {state} when the backstop expired"
        age = rec.get("heartbeat_age")
        return f"{line}, last heartbeat {int(age)}s ago" if age is not None else line
    return "no report, and Orca could not be asked for its state"


# loop bookkeeping, never a caller-facing field. Everything else on a record reaches the
# caller by default; hiding a field is a deliberate act.
INTERNAL_FIELDS = {"stale_reported", "completed_seen_at"}


def juror_row(model, dispatch, rec, report):
    """One juror, reconciled. A juror counts as returned only when it reported done *and*
    left a parseable report; anything else names which half is missing.

    Both halves were internally consistent and disagreed with each other: the progress
    stream was built from messages and the verdict from files on disk, so one announced a
    juror that wrote nothing while the other carried a report nobody had announced
    (LAB-48). They are now the same table."""
    # copy by exclusion, not by enumeration: an allow-list drops every field nobody
    # remembered to add, and it has done so twice — `retry`/`retry_of`, then `stop_error`
    row = {"model": model, "dispatchId": dispatch, "returned": False}
    for k, v in rec.items():
        if k not in INTERNAL_FIELDS and v is not None:
            row[k] = v
    if report is None:
        row.update(parse_ok=False, error=absence_reason(rec))
    else:
        row.update(report)
        if rec.get("result") != "done":
            row["unconfirmed"] = "report on disk, but no worker_done"
    row["returned"] = bool(rec.get("result") == "done" and row.get("parse_ok"))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", action="append", required=True,
                    help="repo-relative artifact path; repeatable")
    ap.add_argument("--intent", action="append", required=True,
                    help="repo-relative intent path, paired with --artifact by position")
    ap.add_argument("--standard", required=True,
                    help="skill name the juror loads to judge form, e.g. plan or review-changes")
    ap.add_argument("--models", nargs="*", default=PANEL)
    ap.add_argument("--out", default="agents/out",
                    help="directory jurors write reports into")
    ap.add_argument("--run-id", help="prefixes this run's reports and handles; "
                                     "defaults to a timestamp")
    ap.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS,
                    help="backstop, not a budget: inspection ends the wait, this only bounds it")
    ap.add_argument("--results", help="defaults to <out>/<run-id>.jury-result.json")
    ap.add_argument("--objective", default="jury review",
                    help="Orca Run objective; name the issue under review")
    args = ap.parse_args()
    if len(args.artifact) != len(args.intent):
        sys.exit("--artifact and --intent must be given the same number of times")

    # The juror's terminal opens at the worktree root and its edit permission is the
    # relative glob `agents/out/*`, so relative has to mean the same thing on both sides.
    # Absolute paths would settle it too, but whether they satisfy that glob is unverified.
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip()
    if root:
        os.chdir(root)

    # The run id prefixes filenames rather than adding a directory: the juror's edit
    # permission is `agents/out/*`, and whether that glob crosses a slash is unverified.
    # Isolation between concurrent runs holds only as far as their run ids differ — and no
    # further: the Run binding is per *coordinator terminal*, so two panels launched from
    # one session fence each other however their ids differ.
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    results_path = args.results or os.path.join(args.out, f"{run_id}.jury-result.json")
    state = os.path.join(args.out, STATE_DIR, f"{run_id}.json")
    PROGRESS["path"] = os.path.join(args.out, f"{run_id}.progress.jsonl")

    run, terminals, ready, results, records, rows = None, {}, {}, [], {}, {}
    try:
        # everything that can raise belongs inside: the caller waits on the settle file the
        # finally writes, so anything failing before it leaves them waiting forever
        ensure_ignored(args.out)     # jurors write here, and the caller watches it
        reclaim_orphans(os.path.join(args.out, STATE_DIR), state)   # before run-create: it rebinds
        check_models(args.models)
        worktree = resolve_worktree(root)
        run = orca("orchestration", "run-create", "--objective", args.objective)["run"]["id"]

        boot_failed = {}
        for model in args.models:
            try:
                h = orca("terminal", "create", "--worktree", worktree,
                         "--title", f"juror {model.split('/')[-1]}",
                         "--command", f"opencode --agent juror -m {model}")["terminal"]["handle"]
                terminals[model] = h
                # before the wait: a boot that times out has still created a terminal
                record_handles(state, terminals.values(), run, records)
                orca("terminal", "wait", "--terminal", h, "--for", "tui-idle",
                     "--timeout-ms", "120000", timeout=180)
                ready[model] = h
            except Exception as exc:
                # one juror that will not boot is an absentee, not the end of the panel
                boot_failed[model] = f"boot failed: {exc}"
                progress("boot_failed", f"NO REPORT from {model.split('/')[-1]} — boot "
                         f"failed", model=model)

        for artifact, intent in zip(args.artifact, args.intent):
            name = os.path.basename(artifact).replace(".md", "")
            started, dispatches, dead = time.monotonic(), {}, dict(boot_failed)
            for model, handle in ready.items():
                report = report_path(args.out, run_id, name, model)
                if os.path.exists(report):
                    os.remove(report)            # else a stale verdict passes for a fresh one
                try:
                    task = orca("orchestration", "task-create", "--task-title", f"jury {name} {model}",
                                "--spec", SPEC.format(artifact=artifact, intent=intent, report=report,
                                                      standard=args.standard))["task"]["id"]
                    d = orca("orchestration", "worker-start", "--task", task,
                             "--worktree", worktree,
                             "--terminal", handle)["dispatchId"]
                except Exception as exc:
                    dead[model] = f"dispatch failed: {exc}"
                    progress("dispatch_failed", f"NO REPORT from "
                             f"{model.split('/')[-1]} — dispatch failed", model=model)
                    continue
                dispatches[d] = {"model": model, "report": report, "task": task,
                                 "handle": handle}
                # registered here, not after collect returns: a crash inside collect() left
                # these unknown to settle_all, and the finally closed their terminals
                # anyway — manufacturing the `terminal_missing` this change exists to
                # remove, on the one path most likely to hit it
                records[d] = {"result": "unsettled"}
                # written before the wait, so a crash here still leaves a later run enough
                # to settle these records
                # `records` holds every dispatch from the moment it is created, retries
                # included, so concatenating `dispatches` only listed each one twice
                record_handles(state, terminals.values(), run, records)
            if dispatches:
                progress("dispatched", f"{len(dispatches)} "
                         f"juror{'s' * (len(dispatches) != 1)} dispatched")

            settled = collect(dispatches, args.timeout_ms, run)
            records.update(settled)

            jurors = [{"model": m, "returned": False, "parse_ok": False, "error": err}
                      for m, err in dead.items()]
            for d, meta in dispatches.items():
                row = juror_row(meta["model"], d, settled.get(d) or {"result": "unsettled"},
                                read_report(meta["report"]))
                rows[d] = row              # settle_all runs later and fills in its release
                jurors.append(row)
            # a juror Orca proved dead cannot serve the next artifact
            returned = {j["model"] for j in jurors if j.get("returned")}
            for d, meta in dispatches.items():
                rec = settled.get(d) or {}
                if rec.get("result") in ("failed", "abandoned") and meta["model"] not in returned:
                    ready.pop(meta["model"], None)
                    boot_failed.setdefault(meta["model"], absence_reason(rec))

            reported = [j for j in jurors if j.get("parse_ok")]
            confirmed = [j for j in jurors if j.get("returned")]
            for j in jurors:
                if not j.get("parse_ok") and j["model"] not in dead:
                    progress("absent", f"NO REPORT from {j['model'].split('/')[-1]} — "
                             f"{j.get('error')}", model=j["model"])
            results.append({"artifact": artifact, "seconds": round(time.monotonic() - started, 1),
                            "reported": len(reported), "confirmed": len(confirmed),
                            "attempted": len(jurors), "jurors": jurors})
            if not reported:
                progress("no_verdict",
                         f"{name}: NO VERDICT — none of {len(jurors)} jurors reported")
    finally:
        # settle before closing: a terminal closed under a live dispatch is what Orca
        # reports back as "no longer live after orchestration recovery"
        settle_all(records)
        for d, rec in records.items():          # the rows are already inside `results`
            for key in ("release", "settled_by"):
                if rec.get(key) is not None and d in rows:
                    rows[d][key] = rec[key]
        for h in terminals.values():
            close_terminal(h)
        if os.path.exists(state):
            os.remove(state)
        # inside finally: the caller treats this file as the settle signal, so a crash that
        # never writes it leaves them waiting for something that will never arrive
        payload = {"run": run, "runId": run_id, "standard": args.standard, "results": results}
        crash = sys.exc_info()[1]
        if crash is not None:
            payload["error"] = f"{type(crash).__name__}: {crash}"
            if not results:                      # nothing was recorded; rescue what landed
                rows = salvage(args.out, run_id, args.artifact[0], args.models)
                if rows:
                    payload["results"] = [{"artifact": args.artifact[0], "salvaged": True,
                                           "reported": len([r for r in rows if r["parse_ok"]]),
                                           "attempted": len(rows), "jurors": rows}]
        try:
            os.makedirs(os.path.dirname(results_path) or ".", exist_ok=True)
            with open(results_path, "w") as fh:
                json.dump(payload, fh, indent=2)
            progress("settled", f"Panel completed — findings in {results_path}")
        except OSError as exc:
            # nowhere to write it: say so rather than masking whatever sent us here
            progress("settled", f"Panel completed — COULD NOT WRITE "
                     f"{results_path}: {exc}")


if __name__ == "__main__":
    main()
