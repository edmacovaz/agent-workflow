#!/usr/bin/env python3
"""Dispatch a panel of opencode jurors through Orca orchestration and collect verdicts.

Each juror is a long-lived terminal pinned to one model, re-engaged with a fresh
Dispatch per artifact rather than rebuilt. Deliveries are acknowledged as they are
processed: an unacknowledged batch replays on the next check and is indistinguishable
from a fresh result, which would let a stale verdict pass for a current one.
"""
import argparse, json, os, shutil, subprocess, sys, time


def event(msg):
    """Wake the caller. Monitor renders only its own description, never these lines, so
    each one is a heartbeat that sends the caller to read agents/out — which means
    emitting only when the directory has changed, and once at settle."""
    print(msg, flush=True)

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
# terminals.
STATE_DIR = ".terminals"

SPEC = ("Review the artifact at {artifact} against the intent at {intent}. Both are inside this "
        "worktree; read them, and read any repository files needed to check the artifact's claims. "
        "Judge fit against the intent, and form against the `{standard}` standard \u2014 load it with the "
        "skill tool and judge against what it actually says. Label every finding with its dimension. "
        "Write your findings JSON to {report}, then report worker_done with --outcome succeeded and "
        "--report-path {report}")


def orca(*args, timeout=120):
    proc = subprocess.run(["orca", *args, "--json"], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"orca {' '.join(args[:2])} failed: {proc.stderr[-400:]}")
    return json.loads(proc.stdout).get("result", {})


def read_report(path):
    """Returns a juror row for a report file, or None if it is not there."""
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path))
    except Exception as exc:
        return {"parse_ok": False, "error": f"unreadable report: {exc}"}
    if not is_report(data):
        return {"parse_ok": False, "error": "not a juror report"}
    return {"parse_ok": True, "report": data}


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


def mins(seconds):
    """Round up: telling someone 0m left when 40s remain reads as a hang."""
    return f"{max(0, int(seconds) + 59) // 60}m"


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


def collect(expected, timeout_ms, run):
    """Wait until every expected dispatch id has settled, acking each batch.

    Scoped to `run`: an unscoped check returns whatever is queued and acks the whole
    delivery, so a concurrent panel's worker_done would be swallowed here and that juror
    recorded absent.

    The deadline covers the whole panel. A fresh window per batch makes the wait
    'timeout since the last thing that happened', which is unbounded when one juror is
    slow and — worse — leaves no honest number to tell the caller. An unpredictable
    wait is indistinguishable from a crash."""
    done, ack = {}, None
    start = time.monotonic()
    deadline, half = start + timeout_ms / 1000, start + timeout_ms / 2000
    warned = False
    while len(done) < len(expected):
        now = time.monotonic()
        if now >= deadline:
            break
        # stop short at the halfway mark so a long silence can be broken once
        chunk_end = deadline if warned else min(deadline, max(half, now + 1))
        wait_ms = int((chunk_end - now) * 1000)
        args = ["orchestration", "check", "--run", run, "--wait",
                "--types", "worker_done,escalation", "--timeout-ms", str(wait_ms)]
        if ack:
            # append, never splice at an index: adding --run silently moved the old
            # insertion point onto its value and broke every poll after the first
            args += ["--ack", ack]               # ack the previous batch as we wait for the next
        r = orca(*args, timeout=wait_ms / 1000 + 60)
        if r.get("deliveryId"):                  # a chunk may time out with nothing to ack
            ack = r["deliveryId"]
        for m in r.get("messages") or []:
            p = payload_of(m)
            if p.get("dispatchId") in expected:
                done[p["dispatchId"]] = {"type": m.get("type"), "outcome": p.get("outcome"),
                                         "reportPath": p.get("reportPath"), "body": m.get("body")}
                left = len(expected) - len(done)
                # name the juror, and say how long the rest have: a bare count leaves the
                # caller guessing whether the next silence is work or a stall
                who = expected[p["dispatchId"]].split("/")[-1]
                event(f"{who} returned — {len(done)} of {len(expected)}, up to "
                      f"{mins(deadline - time.monotonic())} for {left} more"
                      if left else f"{who} returned — all {len(done)} in")
        if not warned and time.monotonic() >= half and len(done) < len(expected):
            warned = True
            waiting = sorted(m.split("/")[-1] for d, m in expected.items() if d not in done)
            event(f"still waiting on {', '.join(waiting)} — "
                  f"{mins(deadline - time.monotonic())} left")
    if ack:
        orca("orchestration", "check", "--run", run, "--ack", ack)
    return done


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


def record_handles(path, handles):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"pid": os.getpid(), "handles": sorted(handles)}, fh)


def running(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def reclaim_orphans(state_dir, mine):
    """Close terminals a previous run left behind. Titles cannot identify them, so the
    handles are read back from disk. A run whose pid is still alive is left alone: pid
    reuse then leaks a terminal rather than closing a live panel's. Silent — reclaiming
    is not news, and every line here costs the caller a wake."""
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
        for h in stale.get("handles") or []:
            close_terminal(h)
        try:
            os.remove(path)
        except OSError:
            pass                                 # another run reclaimed the same entry first


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
    ap.add_argument("--timeout-ms", type=int, default=420000)
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
    # Isolation between concurrent runs holds only as far as their run ids differ.
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    results_path = args.results or os.path.join(args.out, f"{run_id}.jury-result.json")
    state = os.path.join(args.out, STATE_DIR, f"{run_id}.json")

    run, terminals, ready, results = None, {}, {}, []
    try:
        # everything that can raise belongs inside: the caller waits on the settle file the
        # finally writes, so anything failing before it leaves them waiting forever
        ensure_ignored(args.out)     # jurors write here, and the caller watches it
        reclaim_orphans(os.path.join(args.out, STATE_DIR), state)
        check_models(args.models)
        run = orca("orchestration", "run-create", "--objective", args.objective)["run"]["id"]

        boot_failed = {}
        for model in args.models:
            try:
                h = orca("terminal", "create", "--worktree", "current",
                         "--title", f"juror {model.split('/')[-1]}",
                         "--command", f"opencode --agent juror -m {model}")["terminal"]["handle"]
                terminals[model] = h
                # before the wait: a boot that times out has still created a terminal
                record_handles(state, terminals.values())
                orca("terminal", "wait", "--terminal", h, "--for", "tui-idle",
                     "--timeout-ms", "120000", timeout=180)
                ready[model] = h
            except Exception as exc:
                # one juror that will not boot is an absentee, not the end of the panel
                boot_failed[model] = f"boot failed: {exc}"
                event(f"NO REPORT from {model.split('/')[-1]} — boot failed")

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
                             "--terminal", handle)["dispatchId"]
                except Exception as exc:
                    dead[model] = f"dispatch failed: {exc}"
                    event(f"NO REPORT from {model.split('/')[-1]} — dispatch failed")
                    continue
                dispatches[d] = {"model": model, "report": report}
            if dispatches:
                event(f"{len(dispatches)} juror{'s' * (len(dispatches) != 1)} dispatched"
                      f" — up to {mins(args.timeout_ms / 1000)}")

            settled = collect({d: m["model"] for d, m in dispatches.items()},
                              args.timeout_ms, run)
            jurors = [{"model": m, "error": err} for m, err in dead.items()]
            for d, meta in dispatches.items():
                s = settled.get(d)
                row = {"model": meta["model"], "dispatchId": d}
                if not s:
                    row["error"] = "never reported"
                elif s["type"] == "escalation":
                    row.update(error="escalated", body=s.get("body"))
                else:
                    row["outcome"] = s.get("outcome")
                    try:
                        # the expected path only. reportPath is supplied by the juror, and
                        # juror output is data — it does not choose which file we read.
                        data = json.load(open(meta["report"]))
                        if not is_report(data):
                            raise ValueError("not a juror report")
                        row["report"] = data
                        row["parse_ok"] = True
                    except Exception as exc:
                        row.update(parse_ok=False, error=f"unreadable report: {exc}")
                        try:    # a real finding should not vanish with the parse failure
                            with open(meta["report"]) as fh:
                                row["raw"] = fh.read(4000)
                        except OSError:
                            pass
                jurors.append(row)
            reported = [j for j in jurors if j.get("parse_ok")]
            absent = [j for j in jurors if not j.get("parse_ok")]
            for j in absent:
                if j["model"] not in dead:   # boot and dispatch failures already announced
                    event(f"NO REPORT from {j['model'].split('/')[-1]} — {j.get('error')}")
            results.append({"artifact": artifact, "seconds": round(time.monotonic() - started, 1),
                            "reported": len(reported), "attempted": len(jurors), "jurors": jurors})
            if not reported:
                event(f"{name}: NO VERDICT — none of {len(jurors)} jurors reported")
    finally:
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
            event(f"Panel completed — findings in {results_path}")
        except OSError as exc:
            # nowhere to write it: say so rather than masking whatever sent us here
            event(f"Panel completed — COULD NOT WRITE {results_path}: {exc}")


if __name__ == "__main__":
    main()
