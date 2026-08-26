#!/usr/bin/env python3
"""Dispatch a panel of opencode jurors through Orca orchestration and collect verdicts.

Each juror is a long-lived terminal pinned to one model, re-engaged with a fresh
Dispatch per artifact rather than rebuilt. Deliveries are acknowledged as they are
processed: an unacknowledged batch replays on the next check and is indistinguishable
from a fresh result, which would let a stale verdict pass for a current one.
"""
import argparse, json, os, subprocess, sys, time

PANEL = ["opencode-go/gpt-5.6-luna", "opencode-go/deepseek-v4-flash",
         "opencode-go/qwen3.7-plus", "opencode-go/ox-alpha-free"]

SPEC = ("Review the artifact at {artifact} against the intent at {intent}. Both are inside this "
        "worktree; read them, and read any repository files needed to check the artifact's claims. "
        "Write your findings JSON to {report}, then report worker_done with --outcome succeeded and "
        "--report-path {report}")


def orca(*args, timeout=120):
    proc = subprocess.run(["orca", *args, "--json"], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"orca {' '.join(args[:2])} failed: {proc.stderr[-400:]}")
    return json.loads(proc.stdout).get("result", {})


def payload_of(msg):
    p = msg.get("payload") or {}
    return json.loads(p) if isinstance(p, str) else p


def collect(expected, timeout_ms):
    """Wait until every expected dispatch id has settled, acking each batch."""
    done, ack = {}, None
    while len(done) < len(expected):
        args = ["orchestration", "check", "--wait", "--types", "worker_done,escalation",
                "--timeout-ms", str(timeout_ms)]
        if ack:
            args[3:3] = ["--ack", ack]           # ack the previous batch as we wait for the next
        r = orca(*args, timeout=timeout_ms / 1000 + 60)
        if r.get("timedOut") and not r.get("messages"):
            break
        ack = r.get("deliveryId")
        for m in r.get("messages") or []:
            p = payload_of(m)
            if p.get("dispatchId") in expected:
                done[p["dispatchId"]] = {"type": m.get("type"), "outcome": p.get("outcome"),
                                         "reportPath": p.get("reportPath"), "body": m.get("body")}
    if ack:
        orca("orchestration", "check", "--ack", ack)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", action="append", required=True,
                    help="repo-relative artifact path; repeatable")
    ap.add_argument("--intent", action="append", required=True,
                    help="repo-relative intent path, paired with --artifact by position")
    ap.add_argument("--models", nargs="*", default=PANEL)
    ap.add_argument("--out", default="agents/out")
    ap.add_argument("--timeout-ms", type=int, default=420000)
    args = ap.parse_args()
    if len(args.artifact) != len(args.intent):
        sys.exit("--artifact and --intent must be given the same number of times")

    run = orca("orchestration", "run-create", "--objective", "LAB-31 jury corpus")["run"]["id"]
    print(f"run: {run}", file=sys.stderr)

    terminals = {}
    for model in args.models:
        h = orca("terminal", "create", "--worktree", "current", "--title", f"juror {model.split('/')[-1]}",
                 "--command", f"opencode --agent juror -m {model}")["terminal"]["handle"]
        orca("terminal", "wait", "--terminal", h, "--for", "tui-idle", "--timeout-ms", "120000", timeout=180)
        terminals[model] = h
        print(f"  juror ready: {model}", file=sys.stderr)

    results = []
    try:
        for artifact, intent in zip(args.artifact, args.intent):
            name = os.path.basename(artifact).replace(".md", "")
            started, dispatches = time.monotonic(), {}
            for model, handle in terminals.items():
                report = f"{args.out}/{name}.{model.split('/')[-1]}.json"
                task = orca("orchestration", "task-create", "--task-title", f"jury {name} {model}",
                            "--spec", SPEC.format(artifact=artifact, intent=intent, report=report))["task"]["id"]
                d = orca("orchestration", "worker-start", "--task", task, "--terminal", handle)["dispatchId"]
                dispatches[d] = {"model": model, "report": report}
            print(f"{name}: {len(dispatches)} dispatched", file=sys.stderr)

            settled = collect(set(dispatches), args.timeout_ms)
            jurors = []
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
                        row["report"] = json.load(open(s.get("reportPath") or meta["report"]))
                        row["parse_ok"] = True
                    except Exception as exc:
                        row.update(parse_ok=False, error=f"unreadable report: {exc}")
                jurors.append(row)
            results.append({"artifact": artifact, "seconds": round(time.monotonic() - started, 1),
                            "jurors": jurors})
            print(f"{name}: settled in {results[-1]['seconds']}s", file=sys.stderr)
    finally:
        for h in terminals.values():
            subprocess.run(["orca", "terminal", "close", "--terminal", h, "--json"],
                           capture_output=True, text=True)

    json.dump({"run": run, "results": results}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
