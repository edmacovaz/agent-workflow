#!/usr/bin/env python3
"""Run a panel of opencode jurors over an artifact and collect their verdicts.

Each juror is a bounded `opencode run` pinned to one model: it starts, reviews, writes its
report and exits, so completion is the exit and absence is a process fact. Its own event
stream says what it is doing while it works. The deadline is the only thing that stops one —
a second stop rule racing it is how working jurors came to be reported as silent (LAB-65).
"""
import argparse, json, os, shutil, signal, subprocess, sys, time


def event(msg):
    """Say one thing to the caller. Run the panel as the Monitor command and this line is what
    the caller sees, verbatim — measured 12 Sep 2026, against a long-standing belief that only
    Monitor's own description ever reached them (LAB-65).

    The rule is one line per change and nothing between changes: a line the caller cannot
    account for is the noise, and no line at all is the silence this replaced."""
    print(msg, flush=True)


# Set once per run. The progress file lives beside the reports so the directory the caller
# already watches is the one that changes; no second watch is needed.
PROGRESS = {"path": None}


def progress(kind, message, **fields):
    """One caller-facing line: printed to wake Monitor, and appended to the run's progress
    file so that *what* changed can actually reach the caller.

    Before this, the only thing a waiting caller could see was which report files had appeared —
    never that a juror was alive and working, which is the one thing they are waiting to know.
    Iteration 1 removed the false "time remains" signal without adding the true one. The file is
    the record; stdout is the channel, and a run that only writes the file goes silent.

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


SPEC = ("Review the artifact at {artifact} against the intent at {intent}. Both are inside this "
        "worktree; read them, and read any repository files needed to check the artifact's claims. "
        "Judge fit against the intent, and form against the `{standard}` standard — load it with the "
        "skill tool and judge against what it actually says. Label every finding with its dimension. "
        "Write your findings JSON to {report}")


# A backstop, not a stop rule. Thirty minutes because 15-60 is ordinary for real review
# work, and the old 7 was a competing stop rule that reported working jurors as silent.
DEFAULT_TIMEOUT_MS = 1800000

# Bounds how stale a progress line can be, and nothing else. Named apart from the backstop
# because a second thing that decides when a juror is done is how the old seven-minute cutoff
# came to report working jurors as silent — see DEFAULT_TIMEOUT_MS.
POLL_S = 5

# How often a juror still running is reported on. Long enough that the whole panel's chatter
# does not bury the reports it sits among, short enough that a caller is never left wondering.
REPORT_EVERY_S = 60


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


def excerpt(value, limit=200):
    """Whatever a juror put where a field belonged, kept readable and bounded."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text[:limit]


# Every tool a juror can be refused on, because read_impediments drops an entry naming
# anything else: `websearch`, denied since LAB-56, was reported honestly and then vanished
# before the rollup. A wall named outside these is counted malformed, never dropped (LAB-57).
IMPEDIMENT_TOOLS = ("bash", "read", "write", "glob", "grep", "list", "skill",
                    "webfetch", "websearch", "other")
IMPEDIMENT_KINDS = ("refused", "failed")


def text_of(value):
    """A field the juror may have left blank, normalised so absent and "" are one thing."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def attempts_of(entry):
    """How many times the juror reached for it. Defaults to 1 rather than malforming the
    entry: a juror that named the wall but miscounted still witnessed the wall."""
    n = entry.get("attempts")
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 1 else 1


def read_impediments(report):
    """The walls a juror hit, normalised for counting, and whether it answered at all.

    Never raises and never rejects a report: `is_report` stays the only thing that can sink
    a verdict, because a juror penalised for reporting a wall stops reporting them."""
    if not isinstance(report, dict) or "impediments" not in report:
        return [], False             # absent is a juror that did not answer, not an empty list
    raw = report.get("impediments")
    if not isinstance(raw, list):
        return [{"malformed": excerpt(raw)}], True
    entries = []
    for e in raw:
        if (isinstance(e, dict) and e.get("tool") in IMPEDIMENT_TOOLS
                and e.get("kind") in IMPEDIMENT_KINDS
                and isinstance(e.get("target"), str) and e["target"].strip()):
            entries.append({"tool": e["tool"], "target": e["target"].strip(),
                            "kind": e["kind"], "attempts": attempts_of(e),
                            "refusal": text_of(e.get("refusal")),
                            "purpose": text_of(e.get("purpose"))})
        else:
            entries.append({"malformed": excerpt(e)})
    return entries, True


def impediment_rollup(jurors):
    """Walls this panel hit, grouped so one that recurs is countable rather than
    reconstructed from transcripts.

    Counts jurors, not calls — a juror retrying a refused command hit one wall. Only jurors
    that left a verdict are read: an absent one said nothing about the room, and counting it
    silent would blur "the room worked" into "nobody moved" (LAB-57)."""
    walls, reported_by, silent, malformed, unexplained = {}, [], [], 0, 0
    for j in jurors:
        if not j.get("parse_ok"):
            continue
        entries, reported = read_impediments(j.get("report"))
        (reported_by if reported else silent).append(j["model"])
        for e in entries:
            if "malformed" in e:
                malformed += 1
                continue
            key = (e["tool"], e["target"], e["kind"])
            wall = walls.setdefault(key, {"tool": e["tool"], "target": e["target"],
                                          "kind": e["kind"], "count": 0, "attempts": 0,
                                          "jurors": []})
            if not e["refusal"]:
                # counted, not dropped: a wall with no stated reason is still a wall, but it
                # cannot be acted on from this file alone (LAB-57 review)
                unexplained += 1
            # `count` is jurors and `attempts` is calls: glm-5.3-flash retried a denied
            # `git status` for 15 minutes on LAB-57-20260912-132045, which a juror count
            # alone renders identical to hitting it once
            wall["attempts"] += e["attempts"]
            if j["model"] not in wall["jurors"]:
                wall["jurors"].append(j["model"])
                wall["count"] += 1
    rollup = {"walls": sorted(walls.values(),
                              key=lambda w: (-w["count"], w["tool"], w["target"], w["kind"])),
              "reported_by": reported_by, "silent": silent}
    if malformed:
        rollup["malformed"] = malformed
    if unexplained:
        rollup["unexplained"] = unexplained
    return rollup


def salvage(out, run_id, artifact, models):
    """Recover verdicts a crashed run already collected. The settle file is the caller's
    only record, and a crash mid-panel would otherwise hand them an empty one
    sitting next to perfectly good report files."""
    name = os.path.basename(artifact).replace(".md", "")
    rows = []
    for model in models:
        row = read_report(report_path(out, run_id, name, model))
        if row:
            rows.append(dict(model=model, salvaged=True, **row))
    return rows


def opencode_exe():
    """homebrew's bin is missing from PATH in some Claude Code sessions, so `which` alone would
    abort every run rather than the bad ones."""
    exe = shutil.which("opencode") or next(
        (c for c in ("/opt/homebrew/bin/opencode", "/usr/local/bin/opencode",
                     os.path.expanduser("~/.opencode/bin/opencode")) if os.path.exists(c)), None)
    if not exe:
        raise RuntimeError("cannot find the opencode binary")
    return exe


def check_models(models):
    """An unresolvable model id does not fail the dispatch — opencode falls back to the
    agent's declared model and the panel quietly becomes that model twice. Five runs went
    by before a juror's own session gave it away, so the ids are checked before spending."""
    proc = subprocess.run([opencode_exe(), "models"], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        # else an empty stdout blames every model for the command having failed
        raise RuntimeError(f"`opencode models` failed: {proc.stderr[-300:]}")
    known = set(proc.stdout.split())
    unknown = [m for m in models if m not in known]
    if unknown:
        raise RuntimeError(f"unknown model(s): {', '.join(unknown)} — see `opencode models`")


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


def observed(events_path):
    """What a juror has actually done, read from its live event stream: its last tool call and
    how many times that same call has already been made.

    Observation, not inference. The supervision this replaced could only guess liveness from
    heartbeats and dispatch state, because a TUI offered nothing else (LAB-65); a juror's own
    event stream says what it did.

    **This function may not raise.** An escape reaches the wait loop, whose finally kills every
    juror — a status line destroying the panel it was reporting on. Returns None instead, both
    for an unreadable stream and for a juror that has yet to call anything."""
    last, counts = None, {}
    try:
        # errors="replace" and ValueError below: EOF lands mid-character while the juror is
        # still writing, and UnicodeDecodeError is a ValueError — see this function's contract
        # above for why an escape from here is fatal (LAB-65)
        with open(events_path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    part = ev.get("part") or {}
                    if part.get("type") != "tool":
                        continue
                    got = part.get("state") or {}
                    arg = got.get("input") if isinstance(got.get("input"), dict) else {}
                    # the whole target, never the rendered one, and every key a tool uses to
                    # name it: truncating collapsed six files into one, and a missing key made
                    # two different calls look like one repeated (LAB-65 review)
                    key = (part.get("tool") or "?",
                           str(arg.get("command") or arg.get("filePath") or arg.get("pattern")
                               or arg.get("path") or arg.get("name") or arg.get("patchText")
                               or ""))
                except Exception:
                    # every shape in this stream is a third party's, and the last line is
                    # routinely torn; this function may not raise on any of them
                    continue
                counts[key] = counts.get(key, 0) + 1
                last = key
    except (OSError, ValueError):
        return None
    if last is None:
        return None
    return {"tool": last[0], "target": last[1], "repeats": counts[last]}


def shorten(target, limit=60):
    """A target the caller can actually identify. Absolute paths in a worktree share a ~48-char
    prefix, so truncating the raw string reported the directory and never the file (LAB-65
    review). Relative first, then trim — which also keeps a command's name, at its front."""
    here = os.getcwd() + os.sep
    if target.startswith(here):
        target = target[len(here):]
    target = " ".join(target.split())
    return target if len(target) <= limit else target[:limit - 1] + "…"


def working_line(model, juror, now):
    """One line about a juror that has not finished. Reports what it is doing and whether it is
    doing it again — repetition is strong evidence of a loop, where silence is not evidence of
    anything: three minutes without an event is also what one long model call looks like from
    out here. Treating silence as a signal is the mistake that reported working jurors as dead
    (LAB-50), so a quiet juror is reported as quiet and never as stuck."""
    short, secs = model.split("/")[-1], int(now - juror["started"])
    seen = observed(juror["events"])
    if seen is None:
        return f"{short} — running {secs}s, nothing called yet"
    line = f"{short} — running {secs}s, last {seen['tool']} {shorten(seen['target'])}".rstrip()
    # no target means no way to tell two calls apart, so ×N would assert a repetition nobody
    # saw — true for any tool whose target key we have not met, not just the known ones
    return line + (f" (×{seen['repeats']})" if seen["repeats"] > 1 and seen["target"] else "")


def stream_dir(run_id):
    """Where a juror's event and stderr streams go — outside the worktree, deliberately.

    A juror may read anything inside the worktree, so streams kept beside the reports let one
    juror read another's whole reasoning as it forms, and a juror reached for exactly that
    during the LAB-65 panel. The agent's own `external_directory: deny` is the only thing that
    can stop it, and it only binds outside the worktree. Kept rather than temped: they are the
    forensics that replaced session exports."""
    path = os.path.join(os.path.expanduser("~/.cache/jury"), run_id)
    os.makedirs(path, exist_ok=True)
    return path


def launch_juror(exe, model, spec, report, root, streams, run_id, name):
    """Start one juror as a bounded process.

    stdout goes to a file rather than a pipe on purpose: a piped run killed at its deadline came
    back with nothing at all, and the file is also what lets progress be read while the juror is
    still working, which is what replaced the heartbeats (LAB-65)."""
    short = model.split("/")[-1]
    # `name` is in here for the same reason report_path carries it: a run with two artifacts
    # reuses the run id, and without it the second artifact truncates the first's streams
    stem = f"{streams}/{run_id}.{name}.{short}"
    events, errs = f"{stem}.events.jsonl", f"{stem}.stderr.txt"
    handles = []
    try:
        handles.append(open(events, "w"))   # one at a time: a tuple left the first of them
        handles.append(open(errs, "w"))     # open and unreferenced when the second raised
        proc = subprocess.Popen(
            [exe, "run", "--agent", "juror", "-m", model, "--auto", "--format", "json",
             "--print-logs", "--dir", root, spec],
            cwd=root, stdout=handles[0], stderr=handles[1], stdin=subprocess.DEVNULL)
    except Exception:
        for fh in handles:
            fh.close()
        raise
    handles = tuple(handles)
    return {"model": model, "proc": proc, "report": report, "events": events,
            "stderr": errs, "handles": handles, "started": time.monotonic()}


def stderr_tail(path, limit=300):
    """Why a juror exited non-zero, in its own words. Bounded: a crash can print a great deal."""
    try:
        with open(path, errors="replace") as fh:
            return "\n".join(l for l in fh.read().splitlines() if l.strip())[-limit:]
    except (OSError, ValueError):
        return ""


def join_reasons(*parts):
    """Every reason a row has, in order, none of them lost."""
    return "; ".join(p for p in parts if p)


def headless_row(juror, rc, killed=False, why=None):
    """One juror, settled from process facts alone.

    `returned` is the process exiting cleanly and `parse_ok` is a verdict being on disk — two
    halves kept apart, so `confirmed` and `reported` keep meaning what the skill already says
    they mean. Nothing here is inferred: each branch is something the operating system told
    us."""
    for fh in juror["handles"]:
        try:
            fh.close()
        except OSError:
            pass
    row = {"model": juror["model"], "returned": False, "parse_ok": False,
           "seconds": round(time.monotonic() - juror["started"], 1)}
    report = read_report(juror["report"])
    if report:
        row.update(report)
    # appended, never replaced: read_report may already have said the verdict is unreadable,
    # and that a malformed one exists is a different fact from how the process ended
    said = row.get("error")
    if killed:
        row["error"] = join_reasons(
            said, why or f"killed at the {int(row['seconds'])}s timeout")
        return row
    row["exit"] = rc
    if rc != 0:
        tail = stderr_tail(juror["stderr"])
        row["error"] = join_reasons(said, f"exited {rc}" + (f": {tail}" if tail else ""))
        return row
    row["returned"] = True
    if not row["parse_ok"] and "error" not in row:
        row["error"] = "exited cleanly but wrote no report"
    return row


def headless_line(row, done=None, total=None):
    """What to tell the caller about a settled juror.

    Derived from the row rather than from the branch that produced it, so the stream and the
    settle file can never say opposite things: a juror killed after writing a good verdict was
    announced as NO REPORT while being counted in `reported` (LAB-65 review)."""
    short, secs = row["model"].split("/")[-1], int(row["seconds"])
    tally = f" — {done} of {total}" if done and total else ""
    if row["parse_ok"] and row["returned"]:
        return "returned", f"{short} returned in {secs}s{tally}"
    if row["parse_ok"]:
        return "returned", f"{short} wrote a verdict but {row['error']}{tally}"
    return "absent", f"NO REPORT from {short} — {row.get('error')}"


def run_headless(models, artifact, intent, standard, out, run_id, root, timeout_ms, results):
    """Fan four bounded calls out and wait on them. The spec is argv, placement is
    --dir, and the exit is the completion, so there is nothing to place, observe or settle.

    The deadline is the only stop rule. Everything read from the event streams is reported and
    never acted on — a second stop rule racing this one is how the old seven-minute cutoff came
    to report working jurors as silent (see DEFAULT_TIMEOUT_MS)."""
    exe = opencode_exe()
    streams = stream_dir(run_id)
    name = os.path.basename(artifact).replace(".md", "")
    started = time.monotonic()
    deadline = started + timeout_ms / 1000.0

    jurors, pending = [], []      # passed into the wait rather than returned from it, so a
                                  # raise there still leaves every settled row in the caller's
                                  # hands
    for model in models:
        report = report_path(out, run_id, name, model)
        if os.path.exists(report):
            os.remove(report)               # else a stale verdict passes for a fresh one
        try:
            spec = SPEC.format(artifact=artifact, intent=intent, standard=standard,
                               report=report)
            pending.append(launch_juror(exe, model, spec, report, root, streams, run_id,
                                        name))
        except Exception as exc:
            jurors.append({"model": model, "returned": False, "parse_ok": False,
                           "error": f"launch failed: {exc}"})
            progress("launch_failed",
                     f"NO REPORT from {model.split('/')[-1]} — launch failed", model=model)
    if pending:
        progress("dispatched", f"{len(pending)} juror{'s' * (len(pending) != 1)} dispatched")

    spoke = time.monotonic()
    try:
        wait_out(jurors, pending, deadline, spoke, len(models))
    finally:
        # every juror dispatched gets a row and every child gets killed, however the wait
        # ended: a result that omits them reads as a smaller panel that did better than it did.
        # Reached on SIGTERM only because main installs a handler; a SIGKILL still leaks
        for juror in pending:
            if juror["proc"].poll() is None:
                juror["proc"].kill()
                juror["proc"].wait()    # reaped before anything is recorded, so a dying juror
                                        # cannot still be writing the report we then read
            row = headless_row(juror, None, killed=True,
                               why="the run stopped before it finished")
            jurors.append(row)
            progress(*headless_line(row), model=juror["model"])
        reported = [j for j in jurors if j.get("parse_ok")]
        impeded = impediment_rollup(jurors)
        results.append({"artifact": artifact,
                        "seconds": round(time.monotonic() - started, 1),
                        "reported": len(reported),
                        "confirmed": len([j for j in jurors if j["returned"]]),
                        "attempted": len(jurors), "impediments": impeded, "jurors": jurors})
        announce_walls(name, impeded, len(jurors), reported)


def wait_out(jurors, pending, deadline, spoke, total=None):
    """Wait on the jurors, appending each into `jurors` as its process ends. The deadline is the
    only stop rule; everything read from an event stream is reported and never acted on.

    Appends rather than returns so that a raise — a SIGTERM turned into an exit, say — leaves
    the caller holding every row settled so far."""
    while pending:
        time.sleep(POLL_S)
        now, still = time.monotonic(), []
        for juror in list(pending):
            rc = juror["proc"].poll()
            if rc is None and now < deadline:
                still.append(juror)
                continue
            if rc is None:
                juror["proc"].kill()
                juror["proc"].wait()
                row = headless_row(juror, None, killed=True)
            else:
                row = headless_row(juror, rc)
            kind, line = headless_line(
                row, len([j for j in jurors if j.get("parse_ok")]) + bool(row["parse_ok"]),
                total)
            progress("timeout" if rc is None and not row["parse_ok"] else kind, line,
                     model=juror["model"])
            jurors.append(row)
        pending[:] = still
        if pending and now - spoke >= REPORT_EVERY_S:
            for juror in pending:
                progress("working", working_line(juror["model"], juror, now),
                         model=juror["model"])
            spoke = now


def announce_walls(name, impeded, attempted, reported):
    """A wall is only knowable once a report lands, so this is the one point in the stream it
    can reach the caller."""
    if impeded["reported_by"] or impeded["silent"]:
        named = ", ".join(
            f"{w['tool']} {w['target']}"
            + (f" ×{w['attempts']}" if w["attempts"] > w["count"] else "")
            for w in impeded["walls"][:3])
        progress("impeded",
                 f"{name}: {len(impeded['walls'])} wall"
                 f"{'s' * (len(impeded['walls']) != 1)} hit"
                 + (f" — {named}" if named else "")
                 + (f"; {len(impeded['silent'])} juror"
                    f"{'s' * (len(impeded['silent']) != 1)} did not answer"
                    if impeded["silent"] else ""),
                 walls=len(impeded["walls"]))
    if not reported:
        progress("no_verdict", f"{name}: NO VERDICT — none of {attempted} jurors reported")


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
    ap.add_argument("--run-id", help="prefixes this run's reports; defaults to a timestamp")
    ap.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS,
                    help="backstop, not a budget: a juror exiting ends its wait, this bounds it")
    ap.add_argument("--results", help="defaults to <out>/<run-id>.jury-result.json")
    args = ap.parse_args()
    # SIGTERM kills a process outright, running no finally, so the jurors would outlive a
    # runner stopped by its watcher. Turning it into an exit is what lets every finally in this
    # run — the juror cleanup and the settle file — happen at all (LAB-65)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit("terminated"))
    if len(args.artifact) != len(args.intent):
        sys.exit("--artifact and --intent must be given the same number of times")

    # The juror runs at the worktree root and its edit permission is the relative glob
    # `agents/out/*`, so relative has to mean the same thing on both sides. Absolute paths
    # would settle it too, but whether they satisfy that glob is unverified.
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip()
    if root:
        os.chdir(root)

    # The run id prefixes filenames rather than adding a directory: the juror's edit
    # permission is `agents/out/*`, and whether that glob crosses a slash is unverified.
    # Concurrent runs stay isolated exactly as far as their run ids differ, and no further.
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    results_path = args.results or os.path.join(args.out, f"{run_id}.jury-result.json")
    PROGRESS["path"] = os.path.join(args.out, f"{run_id}.progress.jsonl")

    results = []
    try:
        # everything that can raise belongs inside: the caller waits on the settle file the
        # finally writes, so anything failing before it leaves them waiting forever
        ensure_ignored(args.out)     # jurors write here, and the caller watches it
        check_models(args.models)    # an unresolvable id degrades the panel silently
        for artifact, intent in zip(args.artifact, args.intent):
            run_headless(args.models, artifact, intent, args.standard,
                         args.out, run_id, root, args.timeout_ms, results)
    finally:
        # inside finally: the caller treats this file as the settle signal, so a crash that
        # never writes it leaves them waiting for something that will never arrive
        payload = {"runId": run_id, "standard": args.standard, "results": results,
                   "streams": stream_dir(run_id)}   # outside the worktree, so say where
        crash = sys.exc_info()[1]
        if crash is not None:
            payload["error"] = f"{type(crash).__name__}: {crash}"
            if not results:                      # nothing was recorded; rescue what landed
                rows = salvage(args.out, run_id, args.artifact[0], args.models)
                if rows:
                    payload["results"] = [{"artifact": args.artifact[0], "salvaged": True,
                                           "reported": len([r for r in rows if r["parse_ok"]]),
                                           "attempted": len(rows),
                                           "impediments": impediment_rollup(rows),
                                           "jurors": rows}]
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
