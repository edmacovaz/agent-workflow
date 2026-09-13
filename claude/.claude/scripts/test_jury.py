#!/usr/bin/env python3
"""Behaviour tests for jury.py.  Run: python3 claude/.claude/scripts/test_jury.py

By path, from the worktree root: `~/.claude/scripts/` resolves to the main checkout, so the
habitual path runs the copy you are not editing and goes green over a broken change.

No test framework, deliberately: this must run anywhere the jury does with nothing
installed.  Every test here exists because a real run broke, and each names the
iteration it came from — so when one fails, it says which decision is being reversed
rather than just going red.
"""
import importlib.util, json, os, re, subprocess, sys, tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jury.py")


def load():
    """A fresh module per test: these stub module-level functions heavily."""
    spec = importlib.util.spec_from_file_location("jury", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.event = lambda msg: None
    m.close_terminal = lambda h: None
    return m


class Clock:
    """Advances only when a fake responds, so loops actually reach their later passes.
    Iteration 8: a clock that ticked on every read let the deadline arrive before the
    second poll, hiding a bug that lived only on polls carrying an ack."""
    def __init__(self): self.t = 1000.0
    def monotonic(self): return self.t
    def strftime(self, fmt): return "X"


def repo():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    open(os.path.join(d, "a.md"), "w").write("artifact")
    open(os.path.join(d, "i.md"), "w").write("intent")
    return d


def argv(**kw):
    # every test built through here predates the headless default and pins the Orca path, so
    # it asks for that path by name; a test wanting the other mode passes its own (LAB-65)
    kw.setdefault("mode", "tui")
    a = ["jury", "--artifact", "a.md", "--intent", "i.md", "--standard", "plan"]
    for k, v in kw.items():
        a += [f"--{k.replace('_', '-')}", *(v if isinstance(v, list) else [v])]
    return a


def stub_orca(dispatch_id="d1", on_start=None, worktree_path=None):
    def orca(*a, **k):
        op = " ".join(a[:2])
        if op == "orchestration worker-start":
            if on_start:
                on_start()
            return {"dispatchId": dispatch_id}
        if op == "worktree current":
            return {"worktree": {"id": "wt", "path": worktree_path or os.getcwd()}}
        return {"orchestration run-create": {"run": {"id": "R"}},
                "terminal create": {"terminal": {"handle": "h"}},
                "terminal wait": {},
                "orchestration task-create": {"task": {"id": "t"}}}.get(op, {})
    return orca


# ---------------------------------------------------------------- iteration 4, 9
def test_reclaim_only_dead_runs():
    j, closed = load(), []
    j.close_terminal = closed.append
    d = tempfile.mkdtemp(); sd = os.path.join(d, ".terminals")
    mine = os.path.join(sd, "mine.json")
    j.record_handles(mine, ["h-mine"])
    j.record_handles(os.path.join(sd, "other-live.json"), ["h-other"])   # our pid: alive
    dead = os.path.join(sd, "dead.json")
    j.record_handles(dead, ["h-dead"])
    s = json.load(open(dead)); s["pid"] = 999999; json.dump(s, open(dead, "w"))

    j.reclaim_orphans(sd, mine)
    assert closed == ["h-dead"], closed
    assert os.path.exists(mine) and os.path.exists(os.path.join(sd, "other-live.json"))
    assert not os.path.exists(dead)
    j.reclaim_orphans(os.path.join(d, "absent"), mine)          # missing dir is a no-op


def test_reclaim_survives_a_losing_race():
    j = load()
    d = tempfile.mkdtemp(); sd = os.path.join(d, ".terminals")
    dead = os.path.join(sd, "dead.json")
    j.record_handles(dead, ["h"])
    s = json.load(open(dead)); s["pid"] = 999999; json.dump(s, open(dead, "w"))
    real_remove = os.remove
    os.remove = lambda p: (real_remove(p), real_remove(p))       # another run got there first
    try:
        j.reclaim_orphans(sd, os.path.join(sd, "mine.json"))
    finally:
        os.remove = real_remove


# ------------------------------------------------------------------- iteration 5, 9
def test_settle_file_written_when_the_run_dies():
    """The caller waits on this file.  Anything that raises without producing it leaves
    them waiting forever — the hang iteration 5 closed and iteration 9 closed again."""
    for label, break_it in (("orca down", lambda j: setattr(j, "orca", _boom("orca is down"))),
                            ("pre-try",   lambda j: setattr(j, "reclaim_orphans", _boom("reclaim exploded")))):
        j = load(); prev = os.getcwd(); os.chdir(repo())
        try:
            break_it(j)
            sys.argv = argv(run_id="DEAD", out="out", models="opencode-go/gpt-5.6-luna")
            try:
                j.main(); raise AssertionError(f"{label}: expected the failure to propagate")
            except RuntimeError:
                pass
            payload = json.load(open("out/DEAD.jury-result.json"))
            assert payload["error"].startswith("RuntimeError"), (label, payload)
        finally:
            os.chdir(prev)


def _boom(msg):
    def raise_it(*a, **k):
        raise RuntimeError(msg)
    return raise_it


def test_boot_failure_does_not_end_the_panel():
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        events, n = [], {"terminals": 0, "dispatch": 0}
        j.event = events.append
        j.check_models = lambda m: None
        j.collect = lambda expected, timeout, run: {}
        def orca(*a, **k):
            op = " ".join(a[:2])
            if op == "terminal create":
                n["terminals"] += 1
                if n["terminals"] == 2:
                    raise RuntimeError("no such model")
                return {"terminal": {"handle": f"h{n['terminals']}"}}
            if op == "orchestration worker-start":
                n["dispatch"] += 1
                return {"dispatchId": f"d{n['dispatch']}"}
            if op == "worktree current":
                return {"worktree": {"id": "wt", "path": os.getcwd()}}
            return {"orchestration run-create": {"run": {"id": "R"}}, "terminal wait": {},
                    "orchestration task-create": {"task": {"id": "t"}}}.get(op, {})
        j.orca = orca
        sys.argv = argv(run_id="BOOT", out="out",
                        models=["m/alpha", "m/bravo", "m/charlie"])
        j.main()
        r = json.load(open("out/BOOT.jury-result.json"))["results"][0]
        assert r["attempted"] == 3 and r["reported"] == 0, r
        by_model = {x["model"]: x["error"] for x in r["jurors"]}
        assert by_model["m/bravo"].startswith("boot failed"), by_model
        assert "never reported" not in by_model["m/alpha"], by_model   # iteration 13
        assert len([e for e in events if "bravo" in e]) == 1, events   # announced once
    finally:
        os.chdir(prev)


# ---------------------------------------------------------------- iteration 6, 8, 13
def test_the_backstop_bounds_the_wait_but_never_explains_it():
    """Iteration 6 made the deadline the stop rule.  Iteration 13 demotes it to a backstop:
    it still bounds the wait, but what it reports is the state inspection found, never that
    time ran out.  Three of four jurors on LAB-38-20260830-125849 were still `ready` when
    they were written down as silent."""
    j = load(); clock = Clock(); j.time = clock
    events = []; j.event = events.append
    expected = {"d1": {"model": "v/alpha"}, "d2": {"model": "v/bravo"}}
    def orca(*a, **k):
        if " ".join(a[:2]) == "orchestration worker-show":
            return {"dispatch": {"status": "dispatched", "last_heartbeat_at": None},
                    "worker": {"state": "ready", "stage": "running"}}
        if "--timeout-ms" in a:
            clock.t += int(a[a.index("--timeout-ms") + 1]) / 1000
        return {"timedOut": True, "messages": [], "deliveryId": None}
    j.orca = orca

    out = j.collect(expected, 600_000, "RUN")
    assert clock.t - 1000.0 <= 600.0, "ran past its own backstop"
    assert set(out) == {"d1", "d2"}, out            # every dispatch accounted for, not just settled ones
    for rec in out.values():
        assert rec["result"] == "unsettled" and rec["state"] == "ready", rec
    reason = j.absence_reason(out["d1"])
    assert "still ready" in reason and "never reported" not in reason, reason
    assert not any("up to" in e or "left" in e for e in events), events


def test_a_heartbeat_never_settles_a_juror():
    """Iteration 13, LAB-48.  The runner settled on any message carrying a dispatch id, and
    a `heartbeat` carries the same taskId/dispatchId pair as a `worker_done`.  glm-5.3-flash
    was announced as returned, had sent no worker_done, wrote no report, and its task was
    still `ready` when it was found by hand a day later."""
    j = load(); clock = Clock(); j.time = clock
    events = []; j.event = events.append
    calls = []
    def orca(*a, **k):
        if " ".join(a[:2]) == "orchestration worker-show":
            return {"dispatch": {}, "worker": {"state": "ready"}}
        calls.append(list(a))
        if "--timeout-ms" in a:
            clock.t += int(a[a.index("--timeout-ms") + 1]) / 1000
        if len(calls) == 1:
            return {"deliveryId": "D1", "messages": [
                {"type": "heartbeat",
                 "payload": {"dispatchId": "d1", "taskId": "t1", "phase": "reviewing"}}]}
        return {"timedOut": True, "messages": [], "deliveryId": None}
    j.orca = orca

    out = j.collect({"d1": {"model": "v/alpha"}}, 120_000, "RUN")
    assert out["d1"]["result"] == "unsettled", out
    assert out["d1"].get("phase") == "reviewing", out       # surfaced to the caller, not discarded
    assert not any("returned" in e or "reported done" in e for e in events), events


def test_only_worker_done_and_escalation_settle():
    j = load(); clock = Clock(); j.time = clock
    j.event = lambda m: None
    def orca(*a, **k):
        if " ".join(a[:2]) == "orchestration worker-show":
            return {"dispatch": {}, "worker": {"state": "ready"}}
        clock.t += 5
        return {"deliveryId": "D1", "messages": [
            {"type": "worker_done", "payload": {"dispatchId": "d1", "outcome": "succeeded"}},
            {"type": "escalation", "body": "cannot read the artifact",
             "payload": {"dispatchId": "d2"}}]}
    j.orca = orca
    out = j.collect({"d1": {"model": "v/a"}, "d2": {"model": "v/b"}}, 600_000, "RUN")
    assert out["d1"]["result"] == "done" and out["d1"]["outcome"] == "succeeded", out
    assert out["d2"]["result"] == "escalated", out


def test_every_orca_call_is_well_formed():
    """Iteration 8: --run was added to the args list and the --ack splice index was not,
    so every poll after the first was malformed and the panel collected one juror."""
    j = load(); clock = Clock(); j.time = clock
    expected = {"d1": "v/a", "d2": "v/b", "d3": "v/c"}
    calls = []
    def orca(*a, **k):
        calls.append(list(a))
        clock.t += 5
        n = len([c for c in calls if "--wait" in c])
        if f"d{n}" in expected:
            return {"deliveryId": f"D{n}", "messages": [
                {"type": "worker_done", "payload": {"dispatchId": f"d{n}", "outcome": "succeeded"}}]}
        return {"timedOut": True, "messages": [], "deliveryId": None}
    j.orca = orca

    assert len(j.collect(expected, 600_000, "RUN")) == 3
    assert len([c for c in calls if "--wait" in c]) >= 2, "never reached a second poll"
    assert any("--ack" in c for c in calls), "no poll carried an ack; the bug's path was untested"
    for c in calls:
        for i, tok in enumerate(c):
            if tok in ("--run", "--ack", "--types", "--timeout-ms"):
                assert i + 1 < len(c) and not c[i + 1].startswith("--"), (tok, c)
        # inspection calls are addressed by dispatch id and carry no --run
        if "--run" in c:
            assert c[c.index("--run") + 1] == "RUN", c


def test_crash_mid_collect_salvages_what_landed():
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        os.makedirs("out")
        j.check_models = lambda m: None
        report = '{"verdict":"revise","findings":[{"dimension":"fit","severity":"nit",' \
                 '"claim":"real","evidence":"src"}]}'
        j.orca = stub_orca(on_start=lambda: open("out/X.a.alpha.json", "w").write(report))
        real = j.collect
        j.collect = _boom("orca orchestration check failed: ")
        sys.argv = argv(run_id="X", out="out", models=["m/alpha", "m/bravo"])
        try:
            j.main(); raise AssertionError("expected the crash to propagate")
        except RuntimeError:
            pass
        r = json.load(open("out/X.jury-result.json"))["results"][0]
        assert r["salvaged"] and r["reported"] == 1, r
        assert r["jurors"][0]["report"]["verdict"] == "revise", r
    finally:
        os.chdir(prev)


# ---------------------------------------------------------------- iteration 6, 7
def test_stale_report_is_never_served_as_this_runs_verdict():
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        os.makedirs("out")
        open("out/S.a.alpha.json", "w").write('{"verdict":"pass","findings":[]}')
        j.check_models = lambda m: None
        j.collect = lambda e, t, r: {"d1": {"type": "worker_done", "outcome": "succeeded",
                                            "reportPath": None}}
        j.orca = stub_orca()                       # the juror reports but writes nothing
        sys.argv = argv(run_id="S", out="out", models="m/alpha")
        j.main()
        row = json.load(open("out/S.jury-result.json"))["results"][0]["jurors"][0]
        assert row["parse_ok"] is False and "report" not in row, row
    finally:
        os.chdir(prev)


def test_unparseable_report_keeps_its_text():
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        os.makedirs("out")
        j.check_models = lambda m: None
        j.collect = lambda e, t, r: {"d1": {"type": "worker_done", "outcome": "succeeded",
                                            "reportPath": None}}
        j.orca = stub_orca(on_start=lambda: open("out/R.a.alpha.json", "w").write(
            '{"verdict":"pass","findings":[]} TRAILING'))
        sys.argv = argv(run_id="R", out="out", models="m/alpha")
        j.main()
        row = json.load(open("out/R.jury-result.json"))["results"][0]["jurors"][0]
        assert row["parse_ok"] is False and "TRAILING" in row["raw"], row
    finally:
        os.chdir(prev)


def test_is_report_requires_labelled_findings():
    j = load()
    assert j.is_report({"verdict": "pass", "findings": []})
    assert j.is_report({"verdict": "revise", "findings": [
        {"dimension": "fit", "severity": "nit", "claim": "c", "evidence": "e"}]})
    for bad in ({}, {"verdict": "revise"}, {"verdict": "nope", "findings": []},
                {"verdict": "revise", "findings": "not a list"}):
        assert not j.is_report(bad), bad
    for finding in ([{"claim": "c", "evidence": "e"}],
                    [{"dimension": "fit", "severity": "nit", "claim": "c"}],
                    [{"dimension": "other", "severity": "nit", "claim": "c", "evidence": "e"}],
                    [{"dimension": "fit", "severity": "urgent", "claim": "c", "evidence": "e"}],
                    ["not even a dict"]):
        assert not j.is_report({"verdict": "revise", "findings": finding}), finding


# ------------------------------------------------------------------- iteration 10
def test_ensure_ignored_appends_and_never_truncates():
    """Iteration 7 made this write unconditionally, on a finding that write-if-absent
    left reports committable.  Iteration 10 reversed it, on a finding that truncating
    destroys the repository's rules.  Both were right; neither extreme is."""
    j, d = load(), tempfile.mkdtemp()
    def ignored(name, seed=None):
        root = os.path.join(d, name); os.makedirs(root, exist_ok=True)
        if seed is not None:
            open(os.path.join(root, ".gitignore"), "w").write(seed)
        j.ensure_ignored(root)
        return open(os.path.join(root, ".gitignore")).read()

    assert ignored("fresh") == "*\n"
    assert ignored("empty", "") == "*\n"
    assert ignored("rules", "secrets.env\n*.tmp\n") == "secrets.env\n*.tmp\n*\n"
    assert ignored("nonewline", "secrets.env") == "secrets.env\n*\n"
    assert ignored("starglob", "*.log\n") == "*.log\n*\n"      # *.log does not ignore all
    assert ignored("already", "*\n") == "*\n"
    assert ignored("commented", "# scratch\n*\n") == "# scratch\n*\n"
    j.ensure_ignored(os.path.join(d, "rules"))                 # idempotent
    assert open(os.path.join(d, "rules", ".gitignore")).read() == "secrets.env\n*.tmp\n*\n"


# -------------------------------------------------------------------- iteration 7, 10
def test_check_models_rejects_unknown_ids():
    """ox-alpha-free was in the panel for five runs and does not exist; opencode fell
    back to the agent's own model, so the panel was one model twice."""
    j = load()
    j.check_models(j.PANEL)                                    # the live panel must resolve
    for bad in ("opencode-go/ox-alpha-free", "opencode-go/not-a-model"):
        try:
            j.check_models([bad]); raise AssertionError(f"{bad} was accepted")
        except RuntimeError as exc:
            assert bad in str(exc), exc


def test_check_models_reports_a_failed_command_honestly():
    j = load()
    real = subprocess.run
    subprocess.run = lambda *a, **k: type("P", (), {
        "returncode": 1, "stdout": "", "stderr": "opencode: not logged in"})()
    try:
        try:
            j.check_models(["opencode-go/gpt-5.6-luna"]); raise AssertionError("expected a raise")
        except RuntimeError as exc:
            assert "not logged in" in str(exc) and "unknown model" not in str(exc), exc
    finally:
        subprocess.run = real


# ---------------------------------------------------------------------- iteration 9
def test_output_lands_at_the_repo_root_not_the_cwd():
    """The juror's terminal opens at the worktree root, so a run started deeper would
    write where the juror never looks and every juror would read as absent."""
    j = load(); prev = os.getcwd(); root = repo()
    nested = os.path.join(root, "nested", "deeper"); os.makedirs(nested)
    os.chdir(nested)
    try:
        j.check_models = lambda m: None
        j.collect = lambda e, t, r: {}
        j.orca = stub_orca()
        sys.argv = argv(run_id="SUB", out="out", models="m/alpha")
        j.main()
        assert os.path.exists(os.path.join(root, "out", "SUB.jury-result.json"))
        assert not os.path.exists(os.path.join(nested, "out"))
    finally:
        os.chdir(prev)


# --------------------------------------------------------------------- iteration 11
def _failing_run(stdout, stderr):
    return lambda *a, **k: type("P", (), {"returncode": 1, "stdout": stdout, "stderr": stderr})()


def test_orca_failures_carry_their_reason():
    """orca puts its error in JSON on stdout and leaves stderr empty. Reading stderr alone
    stripped the reason off every failure: on LAB-38's first cold run all four jurors
    reported 'worker-start failed: ' with nothing after the colon, while the cause sat
    unread in stdout."""
    j = load(); real = subprocess.run
    subprocess.run = _failing_run('{"ok": false, "error": {"message": "Missing required --task"}}', "")
    try:
        try:
            j.orca("orchestration", "worker-start"); raise AssertionError("expected a raise")
        except RuntimeError as exc:
            assert "Missing required --task" in str(exc), exc
    finally:
        subprocess.run = real


def test_orca_failure_is_never_reasonless():
    """An error with an empty reason reads as a mystery rather than a bug, so the one thing
    this must never do is report a failure with nothing after the colon."""
    j = load(); real = subprocess.run
    subprocess.run = _failing_run("", "")
    try:
        try:
            j.orca("terminal", "create"); raise AssertionError("expected a raise")
        except RuntimeError as exc:
            assert not str(exc).rstrip().endswith(":"), f"reasonless error: {exc!r}"
            assert "no output" in str(exc), exc
    finally:
        subprocess.run = real


# --------------------------------------------------------------------- iteration 12
def test_dispatch_carries_a_resolved_worktree_not_the_word_current():
    """Orca's bare `current` selector resolves the terminal *pane*, not the working
    directory. A session whose pane was created in a sted worktree while the runner worked
    in dotfiles asked Orca to place every juror in the wrong repository — and once that
    worktree was deleted, all four dispatches failed with selector_not_found (LAB-46)."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    calls, base = [], stub_orca()
    try:
        os.makedirs("out")
        j.check_models = lambda m: None
        j.collect = lambda e, t, r: {}
        def orca(*a, **k):
            calls.append(list(a)); return base(*a, **k)
        j.orca = orca
        sys.argv = argv(run_id="W", out="out", models="m/alpha")
        j.main()
        for op in ("terminal create", "orchestration worker-start"):
            c = next(c for c in calls if " ".join(c[:2]) == op)
            assert "--worktree" in c, (op, c)
            assert c[c.index("--worktree") + 1] == "wt", (op, c)
    finally:
        os.chdir(prev)


def test_runner_refuses_a_worktree_that_is_not_the_repo_under_review():
    """The mismatch must stop the run before anything boots: a juror started in another
    repository checks that repository's code against this one's claims, and writes its
    report where the runner never looks."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    calls = []
    try:
        os.makedirs("out")
        j.check_models = lambda m: None
        j.collect = lambda e, t, r: {}   # a regression must fail here, not hang in a poll
        base = stub_orca(worktree_path="/somewhere/else")
        def orca(*a, **k):
            calls.append(" ".join(a[:2])); return base(*a, **k)
        j.orca = orca
        sys.argv = argv(run_id="M", out="out", models="m/alpha")
        try:
            j.main(); raise AssertionError("expected a refusal")
        except RuntimeError as exc:
            assert "wrong repository" in str(exc), exc
        assert "terminal create" not in calls, "booted a terminal before refusing"
    finally:
        os.chdir(prev)


# --------------------------------------------------------------------- iteration 13
def test_a_stderr_full_of_keepalives_never_masks_the_error():
    """LAB-47.  orca puts its error in JSON on stdout and streams `_keepalive` lines to
    stderr every 15 seconds during a --wait, so reading stderr first reported 180 seconds
    of heartbeats as the reason a whole panel died."""
    j = load(); real = subprocess.run
    keepalives = "\n".join('{"_keepalive":true,"_heartbeat":true,"elapsedMs":%d}' % ms
                           for ms in range(15000, 195000, 15000))
    subprocess.run = _failing_run(
        '{"ok": false, "error": {"code": "consumer_fenced", "message": "bound to another run"}}',
        keepalives)
    try:
        try:
            j.orca("orchestration", "check"); raise AssertionError("expected a raise")
        except RuntimeError as exc:
            assert "consumer_fenced" in str(exc), exc
            assert "bound to another run" in str(exc), exc
            assert "_keepalive" not in str(exc), exc
    finally:
        subprocess.run = real


def test_keepalives_alone_still_leave_a_reason():
    """A failure whose only output is the keepalive stream must not report a heartbeat as
    its cause — nor a reasonless error, which iteration 11 already ruled out."""
    j = load(); real = subprocess.run
    subprocess.run = _failing_run("", '{"_keepalive":true,"elapsedMs":15000}')
    try:
        try:
            j.orca("orchestration", "check"); raise AssertionError("expected a raise")
        except RuntimeError as exc:
            assert "_keepalive" not in str(exc), exc
            assert "no output" in str(exc), exc
    finally:
        subprocess.run = real


def test_release_treats_retained_as_success():
    """Jury terminals are external to Orca — the runner creates them and passes
    `--terminal` — so every release comes back `retained` and closes nothing.  Only
    `release_unknown` is a failure; treating `retained` as one reports every juror broken."""
    j = load()
    j.orca = lambda *a, **k: {"terminalState": "retained"}
    assert j.worker_release("d1") == "retained"
    j.orca = _boom("release_unknown")
    assert j.worker_release("d1").startswith("release failed"), j.worker_release("d1")


def test_terminals_close_only_after_their_dispatches_settle():
    """The runner closed terminals in its finally while dispatches were still open, and
    Orca answered `stage: terminal_missing` — "The assigned worker terminal is no longer
    live after orchestration recovery".  That failure was ours, not Orca's."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        order = []
        j.check_models = lambda m: None
        j.event = lambda m: None
        j.close_terminal = lambda h: order.append(f"close {h}")
        def orca(*a, **k):
            op = " ".join(a[:2])
            if op.startswith("orchestration worker-"):
                order.append(op.split()[-1])
            if op == "orchestration worker-show":
                return {"dispatch": {}, "worker": {"state": "ready"}}
            if op == "orchestration worker-start":
                return {"dispatchId": "d1"}
            if op == "worktree current":
                return {"worktree": {"id": "wt", "path": os.getcwd()}}
            return {"orchestration run-create": {"run": {"id": "R"}},
                    "terminal create": {"terminal": {"handle": "h1"}}, "terminal wait": {},
                    "orchestration task-create": {"task": {"id": "t"}}}.get(op, {})
        j.orca = orca
        j.collect = lambda dispatches, timeout, run: {d: {"result": "unsettled"} for d in dispatches}
        sys.argv = argv(run_id="S", out="out", models="m/alpha")
        j.main()
        assert "close h1" in order, order
        assert order.index("worker-stop") < order.index("close h1"), order
        assert order.index("worker-release") < order.index("close h1"), order
        row = json.load(open("out/S.jury-result.json"))["results"][0]["jurors"][0]
        assert row["settled_by"].startswith("stopped"), row      # and it reaches the caller
    finally:
        os.chdir(prev)


def test_the_recovery_sweep_skips_a_live_run_and_settles_a_dead_one():
    """26 task records across 18 runs, the oldest four days stale.  Orca reclaims worker
    terminals on its own; it never settles task or dispatch records, and until now nothing
    else did either."""
    j = load(); calls = []
    j.close_terminal = lambda h: None
    def orca(*a, **k):
        calls.append(" ".join(a[:2]))
        return {"dispatch": {}, "worker": {"state": "ready"}}
    j.orca = orca
    d = tempfile.mkdtemp(); sd = os.path.join(d, ".terminals")
    live = os.path.join(sd, "live.json")
    j.record_handles(live, ["h-live"], "run_live", ["ctx_live"])
    dead = os.path.join(sd, "dead.json")
    j.record_handles(dead, ["h-dead"], "run_dead", ["ctx_dead"])
    s = json.load(open(dead)); s["pid"] = 999999; json.dump(s, open(dead, "w"))

    j.reclaim_orphans(sd, os.path.join(sd, "mine.json"))
    assert "orchestration run-use" in calls, calls            # required before its tasks resolve
    assert "orchestration worker-abandon" in calls, calls     # records only; no process action
    assert "orchestration worker-release" in calls, calls
    assert os.path.exists(live) and not os.path.exists(dead)
    assert "run_live" not in str(calls), calls


def test_a_report_without_a_worker_done_is_kept_and_flagged():
    """LAB-48's other half.  deepseek-v4-flash wrote a report and was never announced,
    because the progress stream was built from messages and the verdict from files.  The
    report is real and must survive; what it must not do is pass as a confirmed return."""
    j = load()
    report = {"verdict": "pass", "findings": []}
    row = j.juror_row("v/alpha", "d1", {"result": "unsettled", "state": "ready"},
                      {"parse_ok": True, "report": report})
    assert row["parse_ok"] and row["report"] == report, row
    assert row["returned"] is False and row["unconfirmed"], row

    done = j.juror_row("v/bravo", "d2", {"result": "done", "outcome": "succeeded"}, None)
    assert done["returned"] is False, done
    assert done["error"] == "reported done but wrote no report", done


def test_outcome_unknown_is_stopped_and_then_reported_as_what_it_became():
    """Orca's recovery for `outcome_unknown` is to stop and inspect again, or abandon and
    accept that resources may still be live.  A stop that does not take is itself the thing
    to report, not a silence to pass on."""
    j = load(); j.event = lambda m: None
    stopped = []
    def orca(*a, **k):
        op = " ".join(a[:2])
        if op == "orchestration worker-stop":
            stopped.append(a)
        if op == "orchestration worker-show":       # the inspection *after* the stop
            return {"dispatch": {}, "worker": {"state": "stopped" if stopped else "outcome_unknown"}}
        return {}
    j.orca = orca
    rec = j.resolve_unknown("d1", "alpha", {"state": "outcome_unknown"})
    assert stopped, "never asked Orca to stop it"
    assert rec["result"] == "failed" and rec["state"] == "stopped", rec

    j2 = load(); j2.event = lambda m: None
    j2.orca = lambda *a, **k: ({"dispatch": {}, "worker": {"state": "outcome_unknown"}}
                               if " ".join(a[:2]) == "orchestration worker-show" else {})
    rec2 = j2.resolve_unknown("d2", "bravo", {"state": "outcome_unknown"})
    assert rec2["result"] == "abandoned" and "may still be live" in rec2["note"], rec2


# --------------------------------------------------------------------- iteration 14
def test_a_crash_in_collect_still_settles_before_closing():
    """The panel's blocker.  `records` was filled only after collect() returned, so a crash
    inside it left that artifact's dispatches unknown to settle_all while the finally closed
    their terminals anyway — manufacturing the `terminal_missing` this change exists to
    remove, on the one path most likely to hit it."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        order = []
        j.check_models = lambda m: None
        j.event = lambda m: None
        j.close_terminal = lambda h: order.append("close")
        def orca(*a, **k):
            op = " ".join(a[:2])
            if op.startswith("orchestration worker-"):
                order.append(op.split()[-1])
            if op == "orchestration worker-show":
                return {"dispatch": {}, "worker": {"state": "ready"}}
            if op == "orchestration worker-start":
                return {"dispatchId": "d1"}
            if op == "worktree current":
                return {"worktree": {"id": "wt", "path": os.getcwd()}}
            return {"orchestration run-create": {"run": {"id": "R"}},
                    "terminal create": {"terminal": {"handle": "h1"}}, "terminal wait": {},
                    "orchestration task-create": {"task": {"id": "t"}}}.get(op, {})
        j.orca = orca
        j.collect = _boom("orca orchestration check failed: consumer_fenced")
        sys.argv = argv(run_id="C", out="out", models="m/alpha")
        try:
            j.main(); raise AssertionError("expected the crash to propagate")
        except RuntimeError:
            pass
        assert "close" in order, order
        assert order.index("worker-stop") < order.index("close"), order
        assert order.index("worker-release") < order.index("close"), order
        assert os.path.exists("out/C.progress.jsonl"), "no progress survived the crash"
    finally:
        os.chdir(prev)


def test_a_failed_dispatch_reading_ready_is_reported_promptly():
    """classify() consulted worker.state alone, so a dispatch Orca had already marked
    `failed` sat `ready` until the 30-minute backstop — longer than the seven minutes it
    replaced, which is the opposite of what this issue is for."""
    j = load(); clock = Clock(); j.time = clock
    events = []; j.event = events.append
    def orca(*a, **k):
        if " ".join(a[:2]) == "orchestration worker-show":
            return {"dispatch": {"status": "failed", "last_failure": "terminal gone"},
                    "worker": {"state": "ready"}}
        clock.t += 5
        return {"timedOut": True, "messages": [], "deliveryId": None}
    j.orca = orca

    out = j.collect({"d1": {"model": "v/alpha"}}, 1_800_000, "RUN")
    assert out["d1"]["result"] == "failed", out
    assert clock.t - 1000.0 < 60.0, "waited on a dispatch Orca had already failed"
    assert any("terminal gone" in e for e in events), events
def test_the_sweep_releases_even_when_it_cannot_inspect():
    """Release is bookkeeping and does not depend on the worker's state, so skipping it when
    the inspection raises drops exactly the case the sweep exists to close."""
    j = load(); calls = []
    def orca(*a, **k):
        op = " ".join(a[:2])
        calls.append(op)
        if op == "orchestration worker-show":
            raise RuntimeError("worker_identity_changed")
        return {}
    j.orca = orca
    j.settle_abandoned_run("run_dead", ["ctx_dead"])
    assert "orchestration worker-release" in calls, calls


def test_release_never_claims_more_than_orca_said():
    """Run LAB-49-20260830-183854 recorded `release=released` for four workers whose
    terminals Orca had retained as external.  The fallback asserted an outcome the receipt
    never contained — the habit this whole issue is about."""
    j = load()
    j.orca = lambda *a, **k: {}
    assert j.worker_release("d1") == "release accepted", j.worker_release("d1")
    j.orca = lambda *a, **k: {"terminalState": "retained"}
    assert j.worker_release("d1") == "retained"


def test_progress_reaches_the_caller_during_the_wait():
    """Monitor renders only its own description, so a wake says "something changed" and no
    more.  Before this the only thing a waiting caller could see was which report files had
    appeared — never that a juror was alive and working."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "p.jsonl"
        j.progress("state", "alpha is still reviewing", model="m/alpha",
                   state="ready", heartbeat_age=40, phase=None)
        j.progress("returned", "alpha returned", model="m/alpha")
        rows = [json.loads(l) for l in open("p.jsonl")]
        assert [r["kind"] for r in rows] == ["state", "returned"], rows
        assert rows[0]["message"] == "alpha is still reviewing", rows
        assert rows[0]["state"] == "ready" and rows[0]["heartbeat_age"] == 40, rows
        assert "phase" not in rows[0], "None fields are noise, not state"
    finally:
        os.chdir(prev)


def test_a_heartbeat_phase_reaches_the_caller_without_settling():
    """`phase: reviewing` was the answer to "is this stalled" and was discarded.  It must
    reach the caller *and* leave the juror unsettled — both halves, not either."""
    j = load(); clock = Clock(); j.time = clock
    j.event = lambda m: None; prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "hb.jsonl"
        calls = []
        def orca(*a, **k):
            if " ".join(a[:2]) == "orchestration worker-show":
                return {"dispatch": {}, "worker": {"state": "ready"}}
            calls.append(1)
            clock.t += int(a[a.index("--timeout-ms") + 1]) / 1000 if "--timeout-ms" in a else 0
            if len(calls) == 1:
                return {"deliveryId": "D1", "messages": [
                    {"type": "heartbeat",
                     "payload": {"dispatchId": "d1", "phase": "reviewing"}}]}
            return {"timedOut": True, "messages": [], "deliveryId": None}
        j.orca = orca
        out = j.collect({"d1": {"model": "v/alpha"}}, 120_000, "RUN")
        assert out["d1"]["result"] == "unsettled", out
        rows = [json.loads(l) for l in open("hb.jsonl")]
        assert any(r["kind"] == "heartbeat" and r["phase"] == "reviewing" for r in rows), rows
    finally:
        os.chdir(prev)


# --------------------------------------------------------------------- iteration 15
def test_a_stop_that_reveals_a_success_is_not_reported_as_a_failure():
    """glm-5.3-flash alone found this, and it was the sharpest of the four.  classify()
    returns "succeeded" for a worker revealed finished after a stop, and resolve_unknown
    called it failed anyway — which under --retry starts a replacement whose first act is to
    delete the report that juror had already written."""
    j = load(); j.event = lambda m: None
    def orca(*a, **k):
        if " ".join(a[:2]) == "orchestration worker-show":
            return {"dispatch": {"status": "completed"}, "worker": {"state": "succeeded"}}
        return {}
    j.orca = orca
    rec = j.resolve_unknown("d1", "alpha", {"state": "outcome_unknown"})
    assert rec["result"] == "done" and rec["outcome"] == "succeeded", rec
    assert "not observed" in rec["note"], rec
    assert rec["reconstructed"] is True, "a record built from Orca's state yields to the "\
        "worker_done that arrives after it (LAB-58)"


def test_a_stop_that_reveals_a_dead_worker_still_reports_it_failed():
    """The other half of the same branch: relabelling a success must not relabel a failure."""
    j = load(); j.event = lambda m: None
    j.orca = lambda *a, **k: ({"dispatch": {}, "worker": {"state": "stopped"}}
                              if " ".join(a[:2]) == "orchestration worker-show" else {})
    rec = j.resolve_unknown("d1", "alpha", {"state": "outcome_unknown"})
    assert rec["result"] == "failed" and rec["state"] == "stopped", rec


def test_release_unknown_is_the_one_release_failure():
    """The docstring promised that only `release_unknown` fails while the code returned
    whatever state arrived.  Orca exits 1 on it today, so the promise held by accident."""
    j = load()
    j.orca = lambda *a, **k: {"releaseState": "release_unknown"}
    assert j.worker_release("d1").startswith("release failed"), j.worker_release("d1")
    j.orca = lambda *a, **k: {"terminalState": "release_pending"}
    assert j.worker_release("d1") == "release_pending"


def test_the_state_file_lists_each_dispatch_once():
    """Iteration 14 put every dispatch in `records` at creation while it was already in
    `dispatches`, and the two were concatenated — so run LAB-49-20260830-195307 recorded all
    four of its dispatches twice, and the recovery sweep would have abandoned and released
    each of them twice."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        j.check_models = lambda m: None
        j.event = lambda m: None
        n = {"d": 0}
        def orca(*a, **k):
            op = " ".join(a[:2])
            if op == "orchestration worker-start":
                n["d"] += 1
                return {"dispatchId": "d%d" % n["d"]}
            if op == "worktree current":
                return {"worktree": {"id": "wt", "path": os.getcwd()}}
            if op == "orchestration worker-show":
                return {"dispatch": {}, "worker": {"state": "ready"}}
            return {"orchestration run-create": {"run": {"id": "R"}},
                    "terminal create": {"terminal": {"handle": "h%d" % n["d"]}},
                    "terminal wait": {},
                    "orchestration task-create": {"task": {"id": "t"}}}.get(op, {})
        j.orca = orca
        j.collect = lambda d, t, r: {k: {"result": "unsettled"} for k in d}
        written, real = [], j.record_handles

        def spy(path, handles, run=None, dispatches=()):
            written.append(list(dispatches))
            return real(path, handles, run, dispatches)
        j.record_handles = spy

        sys.argv = argv(run_id="ONCE", out="out", models=["m/a", "m/b"])
        j.main()
        last = written[-1]
        assert last and len(last) == len(set(last)), last
    finally:
        os.chdir(prev)


# --------------------------------------------------------------------- iteration 16
def test_a_stop_that_does_not_take_reaches_the_caller():
    """The Outcome requires that a stop which does not take is itself a reported outcome.
    resolve_unknown recorded stop_error and nothing read it: juror_row copied by allow-list,
    so any field nobody remembered to enumerate was dropped — `retry`/`retry_of` first, then
    this."""
    j = load()
    row = j.juror_row("v/alpha", "d1",
                      {"result": "abandoned", "stop_error": "worker_identity_changed",
                       "note": "abandoned after outcome_unknown", "stale_reported": True},
                      None)
    assert row["stop_error"] == "worker_identity_changed", row
    assert "stale_reported" not in row, row          # loop bookkeeping stays internal


def test_a_completed_dispatch_is_never_stopped():
    """classify() tested outcome_unknown before dispatchStatus, so a dispatch Orca had
    already completed routed into resolve_unknown and was stopped — and the post-stop
    inspection then read `stopped`, which is dead, so a juror whose verdict was on disk was
    recorded as a failure."""
    j = load()
    assert j.classify({"state": "outcome_unknown", "dispatchStatus": "completed"}) == "succeeded"
    assert j.classify({"state": "outcome_unknown", "dispatchStatus": "dispatched"}) == "unknown"
    assert j.classify({"state": "failed", "dispatchStatus": "completed"}) == "dead"
    assert j.classify({"state": "stopped", "dispatchStatus": "completed"}) == "dead"


def test_a_replayed_message_is_processed_once():
    """A Delivery replays until it is acknowledged, and `d in settled` guards only the types
    that settle — so a replayed heartbeat emitted a duplicate line and a replayed question
    was answered twice."""
    j = load(); events = []; j.event = events.append
    replies, seen, settled, watch = [], set(), {}, {}
    j.orca = lambda *a, **k: replies.append(a) or {}
    dispatches = {"d1": {"model": "v/alpha"}}
    heartbeat = {"id": "m1", "type": "heartbeat",
                 "payload": {"dispatchId": "d1", "phase": "reviewing"}}
    question = {"id": "m2", "type": "question", "body": "which base?",
                "payload": {"dispatchId": "d1"}}
    for m in (heartbeat, heartbeat, question, question):
        j.handle_message(m, dispatches, settled, watch, seen)
    assert len([e for e in events if "reviewing" in e]) == 1, events
    assert len([a for a in replies if a[:2] == ("orchestration", "reply")]) == 1, replies


def test_retry_is_gone():
    """89 dispatches, none ever `failed`: every non-success traced to the coordinator's own
    terminal-closing defect or an explicit stop. Retry recovered from a condition that had
    never occurred, and would have fired on all nineteen."""
    j = load()
    assert not hasattr(j, "retry_failures"), "retry_failures survived"
    assert "--retry" not in open(SCRIPT).read(), "the --retry flag survived"


# --------------------------------------------------------------------- iteration 17
def completing_run(shows, windows):
    """A collect() harness: `shows` answers worker-show per dispatch, `windows` is the list
    of check results to hand back in order, and the clock advances by each wait."""
    j = load(); clock = Clock(); j.time = clock; j.event = lambda m: None
    served = []
    def orca(*a, **k):
        op = " ".join(a[:2])
        if op == "orchestration worker-show":
            d = a[a.index("--dispatch") + 1]
            return shows(d)
        if "--timeout-ms" in a:
            clock.t += int(a[a.index("--timeout-ms") + 1]) / 1000
        i = len(served)
        served.append(1)
        return windows[i] if i < len(windows) else {"messages": [], "deliveryId": None}
    j.orca = orca
    return j


def done_message(d, path="r.json"):
    return {"id": f"m-{d}", "type": "worker_done", "body": "reviewed",
            "payload": {"dispatchId": d, "outcome": "succeeded", "reportPath": path}}


def test_a_worker_done_arriving_after_its_dispatch_completed_still_counts():
    """The whole of LAB-58.  Orca completes a dispatch the moment a valid worker_done
    arrives, so the state flips while the message is still in the queue.  Settling on the
    state left the message to be dropped by `d in settled` and the run reported no count at
    all: three jurors, three `succeeded` lines, no `returned` (LAB-53-20260906-103254)."""
    j = completing_run(lambda d: {"dispatch": {"status": "completed"},
                                  "worker": {"state": "succeeded"}},
                       [{"messages": [], "deliveryId": None},
                        {"messages": [done_message("d1")], "deliveryId": "D1"}])
    prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "p.jsonl"
        out = j.collect({"d1": {"model": "v/alpha"}}, 600_000, "RUN")
        rows = [json.loads(l) for l in open("p.jsonl")]
    finally:
        os.chdir(prev)
    assert out["d1"]["type"] == "worker_done", out
    assert out["d1"]["reportPath"] == "r.json", out
    assert [r["kind"] for r in rows] == ["returned"], rows
    assert "1 of 1" in rows[0]["message"], rows
    assert "late" not in rows[0], "it was waited for, not given up on"


def test_a_completed_dispatch_is_not_announced_while_its_message_is_in_flight():
    """Inspection saying `succeeded` is notification that a worker_done exists, not evidence
    in its own right — so inside the grace it settles nothing and says nothing.  Announcing
    is what made "worker_done not observed here" fire on the healthy path, where it was pure
    noise; it has to mean something when it appears."""
    j = completing_run(lambda d: {"dispatch": {"status": "completed"},
                                  "worker": {"state": "succeeded"}}, [])
    prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "p.jsonl"
        settled, watch = {}, {}
        j.inspect_round({"d1": {"model": "v/alpha"}}, settled, watch,
                        j.time.monotonic() + 10_000)
        said_anything = os.path.exists("p.jsonl")   # written on the first line, not before
    finally:
        os.chdir(prev)
    assert settled == {}, settled
    assert not said_anything, "silence between changes, and this is not a change yet"
    row = j.juror_row("v/alpha", "d1", dict(watch["d1"], result="unsettled"), None)
    assert "completed_seen_at" not in row, \
        "the grace clock is loop bookkeeping, not a field for the caller"
    assert "had not arrived" in row["error"], row


def test_a_message_that_never_arrives_is_settled_and_said_so():
    """The grace is bounded: a completion whose message never comes is still reconciled
    rather than carried to the backstop and called silence (LAB-48).  What changed is that
    the line now names an anomaly instead of firing on every healthy juror."""
    j = completing_run(lambda d: {"dispatch": {"status": "completed"},
                                  "worker": {"state": "succeeded"}}, [])
    prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "p.jsonl"
        out = j.collect({"d1": {"model": "v/alpha"}}, 600_000, "RUN")
        rows = [json.loads(l) for l in open("p.jsonl")]
    finally:
        os.chdir(prev)
    assert out["d1"]["result"] == "done" and out["d1"]["reconstructed"] is True, out
    assert [r["kind"] for r in rows] == ["succeeded"], rows
    assert f"{j.COMPLETION_GRACE_S}s" in rows[0]["message"], rows


def test_a_completion_still_in_its_grace_at_the_backstop_is_settled_not_abandoned():
    """The grace must never outlive the backstop.  Unclamped, a juror Orca had proved
    finished — verdict on disk — came back `unsettled` and `returned: False`, and settle_all
    then issued worker-stop against a dispatch that had already completed, which is what
    test_a_completed_dispatch_is_never_stopped exists to prevent."""
    j = completing_run(lambda d: {"dispatch": {"status": "completed"},
                                  "worker": {"state": "succeeded"}}, [])
    prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "p.jsonl"
        out = j.collect({"d1": {"model": "v/alpha"}}, 60_000, "RUN")
    finally:
        os.chdir(prev)
    assert out["d1"]["result"] == "done", out
    row = j.juror_row("v/alpha", "d1", out["d1"], {"parse_ok": True, "report": {}})
    assert row["returned"] is True, row


def test_a_worker_done_after_the_grace_corrects_the_record():
    """A record the runner reconstructed is not evidence against the message that arrives
    later.  Reachable while other jurors are still outstanding — which is the panel case,
    since a run whose last dispatch settles ends the wait."""
    late = {"messages": [done_message("d1", "late.json")], "deliveryId": "D1"}
    j = completing_run(lambda d: ({"dispatch": {"status": "completed"},
                                   "worker": {"state": "succeeded"}} if d == "d1"
                                  else {"dispatch": {}, "worker": {"state": "ready"}}),
                       [{"messages": [], "deliveryId": None},
                        {"messages": [], "deliveryId": None},
                        {"messages": [], "deliveryId": None},
                        late,
                        {"messages": [done_message("d2")], "deliveryId": "D2"}])
    prev = os.getcwd(); os.chdir(repo())
    try:
        j.PROGRESS["path"] = "p.jsonl"
        out = j.collect({"d1": {"model": "v/alpha"}, "d2": {"model": "v/beta"}},
                        600_000, "RUN")
        rows = [json.loads(l) for l in open("p.jsonl")]
    finally:
        os.chdir(prev)
    assert out["d1"]["reportPath"] == "late.json", out
    assert "reconstructed" not in out["d1"], "the message replaces the reconstruction"
    kinds = [r["kind"] for r in rows]
    assert kinds == ["succeeded", "returned", "returned"], rows
    assert rows[1]["late"] is True and "1 of 2" in rows[1]["message"], rows
    assert "2 of 2" in rows[2]["message"], "a corrected record is not counted twice"


# --------------------------------------------------------------------- iteration 18
def _report(impediments=None, verdict="pass"):
    r = {"verdict": verdict, "findings": []}
    if impediments is not None:
        r["impediments"] = impediments
    return r


WALL = {"tool": "bash", "target": "git status", "kind": "refused",
        "refusal": "denied by the bash allowlist", "purpose": "see what changed"}


def test_a_malformed_impediment_never_costs_the_verdict():
    """The loop asks its workers to report defects in the loop, which only holds while
    reporting one is free.  A bad entry costs its own slot and nothing else — `is_report`
    stays the only thing that can sink a verdict (LAB-57)."""
    j = load()
    report = _report([WALL, "not a dict", {"tool": "telepathy", "target": "x", "kind": "refused"}])
    assert j.is_report(report), report

    row = j.juror_row("v/alpha", "d1", {"result": "done", "outcome": "succeeded"},
                      {"parse_ok": True, "report": report})
    assert row["returned"] is True and row["report"]["verdict"] == "pass", row
    assert row["impediments_reported"] is True, row

    entries, reported = j.read_impediments(report)
    assert reported and len(entries) == 3, entries
    assert entries[0]["target"] == "git status", entries
    assert "malformed" in entries[1] and "malformed" in entries[2], entries


def test_a_juror_that_answered_nothing_is_not_one_that_hit_nothing():
    """A panel where the room worked must not read like one where nobody moved, so an
    absent field and an empty list are different answers (LAB-57)."""
    j = load()
    assert j.read_impediments(_report()) == ([], False)
    assert j.read_impediments(_report([])) == ([], True)

    jurors = [{"model": "v/quiet", "parse_ok": True, "report": _report()},
              {"model": "v/clean", "parse_ok": True, "report": _report([])},
              {"model": "v/absent", "parse_ok": False, "error": "escalated"}]
    rollup = j.impediment_rollup(jurors)
    assert rollup["silent"] == ["v/quiet"], rollup
    assert rollup["reported_by"] == ["v/clean"], rollup
    assert rollup["walls"] == [], rollup


def test_a_recurring_wall_counts_jurors_not_calls():
    """A wall the whole panel hit is the pattern worth seeing; one juror retrying a refused
    command is still one wall, not three (LAB-57)."""
    j = load()
    retried = _report([WALL, dict(WALL), {"tool": "skill", "target": "orca-cli",
                                          "kind": "refused", "refusal": "no such skill"}])
    jurors = [{"model": "v/alpha", "parse_ok": True, "report": retried},
              {"model": "v/bravo", "parse_ok": True, "report": _report([WALL])}]
    walls = j.impediment_rollup(jurors)["walls"]
    assert [(w["target"], w["count"]) for w in walls] == [("git status", 2), ("orca-cli", 1)], walls
    assert walls[0]["jurors"] == ["v/alpha", "v/bravo"], walls


def test_a_retry_loop_shows_in_attempts_not_in_the_wall_count():
    """glm-5.3-flash retried a denied `git status` for fifteen minutes on
    LAB-57-20260912-132045 and burned a dollar producing nothing.  Counting jurors keeps
    that one wall; counting attempts is what tells it apart from hitting it once."""
    j = load()
    looped = _report([dict(WALL, attempts=412)])
    steady = _report([dict(WALL, attempts=1)])
    walls = j.impediment_rollup([
        {"model": "v/looper", "parse_ok": True, "report": looped},
        {"model": "v/steady", "parse_ok": True, "report": steady}])["walls"]
    assert len(walls) == 1 and walls[0]["count"] == 2, walls
    assert walls[0]["attempts"] == 413, walls

    # a miscounted attempt never costs the wall it witnessed
    for bad in (None, 0, "many", True, -3):
        entries, _ = j.read_impediments(_report([dict(WALL, attempts=bad)]))
        assert entries[0]["attempts"] == 1, (bad, entries)
    assert j.read_impediments(_report([WALL]))[0][0]["attempts"] == 1


def test_a_wall_with_no_stated_reason_is_counted_as_such():
    """Recording what was attempted is half the outcome; a wall nobody said the reason for
    cannot be acted on, so it is counted rather than passed off as complete (LAB-57 review)."""
    j = load()
    bare = {"tool": "read", "target": "~/.agents/skills/orca-cli", "kind": "refused"}
    entries, _ = j.read_impediments(_report([bare, dict(WALL, refusal="   ")]))
    assert [e["refusal"] for e in entries] == [None, None], entries

    rollup = j.impediment_rollup([{"model": "v/alpha", "parse_ok": True,
                                   "report": _report([bare, WALL])}])
    assert rollup["unexplained"] == 1, rollup
    assert len(rollup["walls"]) == 2, rollup
    assert "unexplained" not in j.impediment_rollup(
        [{"model": "v/alpha", "parse_ok": True, "report": _report([WALL])}])


def test_a_failed_call_is_its_own_kind_of_wall():
    """`refused` is the room saying no and `failed` is a permitted call breaking.  They key
    apart so a juror's own bad command is never filed as a permission bug (LAB-57)."""
    j = load()
    broke = dict(WALL, kind="failed", refusal="fatal: not a git repository")
    walls = j.impediment_rollup([{"model": "v/alpha", "parse_ok": True,
                                  "report": _report([WALL, broke])}])["walls"]
    assert sorted(w["kind"] for w in walls) == ["failed", "refused"], walls
    assert all(w["count"] == 1 for w in walls), walls


def test_an_impediments_field_that_is_not_a_list_is_kept_and_counted():
    """The field is telemetry, so a juror that puts prose where the list belongs still gets
    its verdict — and the maintainer still learns the schema was missed (LAB-57 review)."""
    j = load()
    report = _report("the room refused me twice")
    assert j.is_report(report), report
    entries, reported = j.read_impediments(report)
    assert reported and len(entries) == 1 and "refused me twice" in entries[0]["malformed"]

    rollup = j.impediment_rollup([{"model": "v/alpha", "parse_ok": True, "report": report}])
    assert rollup["malformed"] == 1 and rollup["walls"] == [], rollup
    assert rollup["reported_by"] == ["v/alpha"] and rollup["silent"] == [], rollup


def test_the_settle_file_carries_the_panels_walls():
    """The whole point is a record someone can compare across runs, so the roll-up has to
    reach the file the caller reads rather than living in the progress stream (LAB-57)."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        os.makedirs("out")
        j.check_models = lambda m: None
        j.collect = lambda e, t, r: {"d1": {"result": "done", "type": "worker_done",
                                            "outcome": "succeeded", "reportPath": None}}
        j.orca = stub_orca(on_start=lambda: open("out/W.a.alpha.json", "w").write(
            json.dumps(_report([WALL]))))
        sys.argv = argv(run_id="W", out="out", models="m/alpha")
        j.main()
        result = json.load(open("out/W.jury-result.json"))["results"][0]
        assert result["impediments"]["walls"][0]["target"] == "git status", result
        assert result["impediments"]["reported_by"] == ["m/alpha"], result
        assert result["jurors"][0]["impediments_reported"] is True, result
        assert result["reported"] == 1 and result["confirmed"] == 1, result
    finally:
        os.chdir(prev)


# --------------------------------------------------------------------- iteration 19
# Headless jurors (LAB-65). Absence is three process facts here, so these pin what the
# operating system said rather than what a worker claimed about itself.

class FakeProc:
    """A juror process. `codes` is what poll() returns in order; None means still running."""
    def __init__(self, codes):
        self.codes, self.killed = list(codes), False

    def poll(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]

    def kill(self):
        self.killed = True
        self.codes = [-9]

    def wait(self):
        return -9


def headless(m, d, codes, report=None, events="", stderr="", timeout_ms=60000):
    """One juror through run_headless, with the process and its streams faked."""
    out = os.path.join(d, "out")
    os.makedirs(out, exist_ok=True)
    made = {}

    def launch(exe, model, spec, rep, root, o, run_id, name):
        # written here rather than up front: run_headless deletes a pre-existing report, so a
        # test that seeded one would be testing the stale-verdict guard instead
        if report is not None:
            open(rep, "w").write(report)
        open(f"{o}/R.alpha.events.json", "w").write(events)
        open(f"{o}/R.alpha.stderr.txt", "w").write(stderr)
        made["proc"] = FakeProc(codes)
        return {"model": model, "proc": made["proc"], "report": rep,
                "events": f"{o}/R.alpha.events.json", "stderr": f"{o}/R.alpha.stderr.txt",
                "handles": (), "started": m.time.monotonic()}

    m.opencode_exe = lambda: "opencode"
    m.launch_juror = launch
    m.POLL_S = 0
    lines = []
    m.progress = lambda kind, msg, **kw: lines.append((kind, msg))
    results = []
    m.run_headless(["m/alpha"], "a.md", "i.md", "plan", out, "R", d, timeout_ms, results)
    res = results[0]
    return res, res["jurors"][0], lines, made.get("proc")


def test_a_clean_exit_with_a_verdict_is_reported_and_confirmed():
    m = load()
    with tempfile.TemporaryDirectory() as d:
        good = json.dumps({"verdict": "pass", "findings": [], "impediments": []})
        res, row, _, _ = headless(m, d, [0], report=good)
        assert row["returned"] and row["parse_ok"], row
        assert res["reported"] == 1 and res["confirmed"] == 1, res


def test_a_clean_exit_without_a_report_is_not_a_verdict():
    """Exit 0 settles the process, not the review — `confirmed` without `reported` is exactly
    the juror this distinguishes, and counting it as a pass is counting silence as approval."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        res, row, _, _ = headless(m, d, [0])
        assert row["returned"] and not row["parse_ok"], row
        assert "wrote no report" in row["error"], row
        assert res["confirmed"] == 1 and res["reported"] == 0, res


def test_a_non_zero_exit_carries_its_code_and_its_reason():
    m = load()
    with tempfile.TemporaryDirectory() as d:
        _, row, _, _ = headless(m, d, [3], stderr="provider refused the request")
        assert row["exit"] == 3 and not row["returned"], row
        assert "exited 3" in row["error"] and "provider refused" in row["error"], row


def test_a_juror_killed_at_the_deadline_says_so():
    """A timeout is a clean loss with a name, never a juror that 'did not respond'."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        # a real clock: the deadline has to be short or the suite waits it out (LAB-65)
        _, row, lines, proc = headless(m, d, [None], timeout_ms=1)
        assert proc.killed, "the deadline must actually kill it"
        assert not row["returned"] and "timeout" in row["error"], row
        assert any(k == "timeout" for k, _ in lines), lines


def test_a_wall_survives_the_headless_path_intact():
    """The report contract is what LAB-55/57/32 read, so it must cross unchanged (LAB-65)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        walled = json.dumps({"verdict": "pass", "findings": [], "impediments": [
            {"tool": "bash", "target": "git status", "kind": "refused",
             "attempts": 4, "refusal": "denied", "purpose": "check the tree"}]})
        res, row, _, _ = headless(m, d, [0], report=walled)
        assert row["parse_ok"] and row["returned"], row
        wall = res["impediments"]["walls"][0]
        assert (wall["tool"], wall["target"], wall["attempts"]) == ("bash", "git status", 4), wall


def test_a_repeated_call_is_reported_as_repeated():
    """Repetition is the strong signal the event stream buys; silence is not evidence, so only
    this one is counted. It must never stop a juror — see the next test."""
    m = load()
    ev = "\n".join(json.dumps({"part": {"type": "tool", "tool": "bash",
                                        "state": {"input": {"command": "git status"}}}})
                   for _ in range(3))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.json")
        open(path, "w").write(ev)
        seen = m.observed(path)
        assert seen["tool"] == "bash" and seen["repeats"] == 3, seen
        line = m.working_line("m/alpha", {"started": 0, "events": path}, 30)
        assert "×3" in line and "git status" in line, line


def test_a_loop_is_reported_and_never_stopped():
    """The old seven-minute cutoff reported working jurors as silent. The deadline stays the
    only stop rule: a juror repeating itself is described, not killed."""
    m = load()
    ev = "\n".join(json.dumps({"part": {"type": "tool", "tool": "bash",
                                        "state": {"input": {"command": "ls"}}}})
                   for _ in range(9))
    with tempfile.TemporaryDirectory() as d:
        m.REPORT_EVERY_S = 0
        _, row, lines, proc = headless(m, d, [None, None, 0],
                                       report=json.dumps({"verdict": "pass", "findings": []}),
                                       events=ev)
        assert not proc.killed, "a repeating juror must not be killed"
        assert row["returned"] and row["parse_ok"], row
        assert any(k == "working" and "×9" in msg for k, msg in lines), lines


def test_a_quiet_juror_is_quiet_and_not_stuck():
    """Three minutes without an event is also what one long model call looks like from out
    here, so silence is reported as silence and never diagnosed."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.json")
        open(path, "w").write("")
        assert m.observed(path) is None
        line = m.working_line("m/alpha", {"started": 0, "events": path}, 200)
        assert "nothing called yet" in line and "200s" in line, line
        assert "stuck" not in line, line


def test_a_half_written_event_line_never_costs_the_reading():
    """The stream is read while the juror is still writing it, so a torn last line is normal."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.json")
        open(path, "w").write(
            json.dumps({"part": {"type": "tool", "tool": "read",
                                 "state": {"input": {"filePath": "a.md"}}}}) + "\n{\"par")
        seen = m.observed(path)
        assert seen and seen["tool"] == "read", seen


def test_headless_asks_orca_for_nothing():
    """Orca has no role in the juror path: a call would mean state nobody settles (LAB-65)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        def forbidden(*a, **k):
            raise AssertionError(f"headless called orca: {a}")
        m.orca = forbidden
        _, row, _, _ = headless(m, d, [0],
                                report=json.dumps({"verdict": "pass", "findings": []}))
        assert row["returned"], row


def test_the_juror_is_launched_as_a_bounded_call():
    m = load()
    seen = {}
    m.subprocess = type("S", (), {
        "Popen": staticmethod(lambda cmd, **k: seen.update(cmd=cmd, kw=k) or FakeProc([0])),
        "DEVNULL": -3})()
    with tempfile.TemporaryDirectory() as d:
        m.launch_juror("oc", "m/alpha", "spec", f"{d}/r.json", d, d, "R", "a")
    cmd = seen["cmd"]
    assert cmd[:3] == ["oc", "run", "--agent"] and cmd[3] == "juror", cmd
    assert "--auto" in cmd and "--format" in cmd and "--dir" in cmd, cmd
    # stdout to a file, never a pipe: a piped run killed at its deadline came back empty
    assert seen["kw"]["stdout"] is not m.subprocess.DEVNULL, seen["kw"]


def test_a_killed_juror_that_wrote_a_verdict_is_not_called_absent():
    """The stream and the settle file must not disagree: this row was counted in `reported`
    while being announced as NO REPORT (LAB-65 review)."""
    m = load()
    row = {"model": "m/alpha", "seconds": 30.0, "parse_ok": True, "returned": False,
           "error": "killed at the 30s timeout"}
    kind, line = m.headless_line(row)
    assert kind == "returned" and "NO REPORT" not in line, line
    assert "wrote a verdict" in line and "killed" in line, line


def test_a_juror_is_never_left_running_when_the_wait_breaks():
    """A juror outlives the runner otherwise, and can drop a report after the settle file was
    written, where salvage() would serve it as this run's verdict (LAB-65 review)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out")
        os.makedirs(out)
        procs = []

        def launch(exe, model, spec, rep, root, o, run_id, name):
            open(f"{o}/x.events.json", "w").write("")
            p = FakeProc([None])
            procs.append(p)
            return {"model": model, "proc": p, "report": rep, "events": f"{o}/x.events.json",
                    "stderr": f"{o}/x.events.json", "handles": (), "started": 0}

        m.opencode_exe = lambda: "opencode"
        m.launch_juror = launch
        m.POLL_S = 0
        m.progress = lambda *a, **k: None
        m.headless_row = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            m.run_headless(["m/alpha"], "a.md", "i.md", "plan", out, "R", d, 0, [])
        except RuntimeError:
            pass
        assert procs and procs[0].killed, "the juror must be killed when the wait breaks"


def test_two_artifacts_keep_their_own_event_streams():
    """One run id covers every artifact, so a stream named only for the model meant the second
    artifact truncated the first's (LAB-65 review)."""
    m = load()
    seen = []
    m.subprocess = type("S", (), {
        "Popen": staticmethod(lambda cmd, **k: seen.append(k) or FakeProc([0])),
        "DEVNULL": -3})()
    with tempfile.TemporaryDirectory() as d:
        a = m.launch_juror("oc", "m/alpha", "s", f"{d}/r.json", d, d, "R", "first")
        b = m.launch_juror("oc", "m/alpha", "s", f"{d}/r.json", d, d, "R", "second")
    assert a["events"] != b["events"] and a["stderr"] != b["stderr"], (a, b)
    assert "first" in a["events"] and "second" in b["events"], (a, b)


def test_the_reports_glob_never_matches_an_event_stream():
    """`dispatch-mechanics.md` has the caller glob `<run>.<artifact>.<model>.json` for verdicts.
    A `.events.json` sibling answers that glob and is served as a report (LAB-65 review)."""
    m = load()
    import glob as g
    seen = []
    m.subprocess = type("S", (), {
        "Popen": staticmethod(lambda cmd, **k: seen.append(k) or FakeProc([0])),
        "DEVNULL": -3})()
    with tempfile.TemporaryDirectory() as d:
        j = m.launch_juror("oc", "m/alpha", "s", f"{d}/R.a.alpha.json", d, d, "R", "a")
        open(f"{d}/R.a.alpha.json", "w").write("{}")
        matched = [os.path.basename(x) for x in g.glob(f"{d}/R.a.*.json")]
    assert j["events"].endswith(".jsonl"), j["events"]
    assert matched == ["R.a.alpha.json"], matched


# The progress reader's contract. Three review rounds each found a different instance of the
# same two violations — a shape that made it raise, and a target it could not name — so these
# are written as invariants over shapes rather than as one test per tool (LAB-65 review).
#
#   P1  observed() never raises, whatever the stream holds.
#   P2  it never claims a repetition it cannot see. `repeats` counts how often that exact
#       (tool, target) appeared anywhere in the stream — a count, never a loop verdict.
#   P3  nothing it does can stop a juror — which follows from P1.

HOSTILE_STREAMS = [
    ("a JSON string line", b'"hello"'),
    ("a JSON array line", b"[1,2,3]"),
    ("a bare number", b"42"),
    ("a null line", b"null"),
    ("part is a list", b'{"part": [1,2]}'),
    ("state is not a mapping", b'{"part":{"type":"tool","state":5}}'),
    ("input is not a mapping", b'{"part":{"type":"tool","state":{"input":7}}}'),
    ("unparseable text", b"not json at all"),
    ("empty", b""),
    ("a torn multi-byte character", b'{"part":{"type":"tool"}}\n{"x": "\xe2'),
    ("raw bytes", b"\xff\xfe\x00garbage"),
]


def test_observed_never_raises_whatever_the_stream_holds():
    """P1. The stream is a third party's output, read while it is still being written. An
    escape from here lands in the wait loop, whose finally kills every juror — a status line
    destroying the panel it was reporting on (LAB-65 properties pass)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.jsonl")
        for label, body in HOSTILE_STREAMS:
            open(path, "wb").write(body)
            m.observed(path)                       # must not raise
            m.working_line("m/a", {"started": 0, "events": path}, 10)
        assert m.observed(os.path.join(d, "absent.jsonl")) is None


def test_every_tool_names_its_target():
    """P2, first half. Each tool puts its target under a different key; one we do not read
    keys as "" and makes two different calls look like one repeated. Rounds found `skill`'s
    `name` and `apply_patch`'s `patchText` separately — this is the table."""
    m = load()
    cases = [("bash", "command", "git status"), ("read", "filePath", "/tmp/a.md"),
             ("grep", "pattern", "juror"), ("glob", "path", "agents/out"),
             ("skill", "name", "review-changes"), ("apply_patch", "patchText", "@@ -1 +1 @@")]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.jsonl")
        for tool, key, val in cases:
            open(path, "w").write(json.dumps(
                {"part": {"type": "tool", "tool": tool, "state": {"input": {key: val}}}}))
            seen = m.observed(path)
            assert seen["tool"] == tool and seen["target"] == val, (tool, seen)


def test_no_repeat_marker_without_a_target():
    """P2, second half — and the durable form of it. A tool whose target key we have never met
    keys as "", which cannot tell two calls apart, so ×N would assert a loop nobody saw."""
    m = load()
    ev = "\n".join(json.dumps({"part": {"type": "tool", "tool": "future_tool",
                                        "state": {"input": {"unknownKey": n}}}})
                   for n in ("a", "b", "c"))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.jsonl")
        open(path, "w").write(ev)
        assert m.observed(path)["repeats"] == 3          # it did count them
        line = m.working_line("m/a", {"started": 0, "events": path}, 10)
        assert "×" not in line, line                     # and it must not claim they matched


def test_a_repeat_count_never_collapses_two_different_targets():
    """P2 again, by the route that started it: keying on a *rendered* target collapsed nine
    reads of six files into one call repeated nine times (LAB-65 review)."""
    m = load()
    base = "/Users/x/very/long/worktree/prefix/that/eats/the/budget/claude/scripts/"
    ev = "\n".join(json.dumps({"part": {"type": "tool", "tool": "read",
                                        "state": {"input": {"filePath": base + f}}}})
                   for f in ("jury.py", "test_jury.py", "jury.py"))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.jsonl")
        open(path, "w").write(ev)
        # deliberately non-adjacent: the two jury.py reads are separated by another call, and
        # the count is "how often this call was made", not "how long the trailing run was"
        assert m.observed(path)["repeats"] == 2, m.observed(path)


def test_the_working_line_names_the_file_not_just_its_directory():
    """Absolute paths in a worktree share a long prefix, so trimming the raw string told the
    caller which directory and never which file (LAB-65 review)."""
    m = load()
    root = os.getcwd()
    ev = json.dumps({"part": {"type": "tool", "tool": "read", "state": {"input": {
        "filePath": os.path.join(root, "claude/.claude/scripts/test_jury.py")}}}})
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e.jsonl")
        open(path, "w").write(ev)
        line = m.working_line("m/alpha", {"started": 0, "events": path}, 30)
    assert "test_jury.py" in line and root not in line, line


def test_undecodable_stderr_never_kills_the_survivors():
    """Same contract as P1, reached through headless_row while settling one juror."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "err.txt")
        open(path, "wb").write(b"provider said \xff\xfe no")
        assert "provider said" in m.stderr_tail(path)
        assert m.stderr_tail(os.path.join(d, "absent.txt")) == ""


def test_an_interrupted_wait_keeps_the_jurors_it_already_settled():
    """A TaskStop becomes SystemExit out of the sleep, and rows built in a local were discarded
    with it — main only salvages when *no* artifact produced results, so a two-artifact panel
    lost the second artifact's verdicts entirely (LAB-65 review)."""
    m = load()
    settled, pending = [], []
    with tempfile.TemporaryDirectory() as d:
        done = os.path.join(d, "done.json")
        open(done, "w").write(json.dumps({"verdict": "pass", "findings": []}))
        open(os.path.join(d, "e.jsonl"), "w").write("")
        for name, codes in (("m/done", [0]), ("m/slow", [None])):
            pending.append({"model": name, "proc": FakeProc(codes), "report": done,
                            "events": os.path.join(d, "e.jsonl"),
                            "stderr": os.path.join(d, "e.jsonl"), "handles": (), "started": 0})
        m.POLL_S = 0
        m.progress = lambda *a, **k: None
        rounds = {"n": 0}

        def interrupt(_):
            rounds["n"] += 1
            if rounds["n"] > 1:
                raise SystemExit("terminated")

        m.time = type("T", (), {"sleep": staticmethod(interrupt),
                                "monotonic": staticmethod(lambda: 0.0)})()
        try:
            m.wait_out(settled, pending, 10_000, 0, 2)
            raise AssertionError("expected the interrupt to propagate")
        except SystemExit:
            pass
    assert [r["model"] for r in settled] == ["m/done"], settled
    assert settled[0]["parse_ok"], settled


def test_an_interrupted_run_still_records_every_juror():
    """salvage() rebuilds a result from whichever reports exist, so a run that lost its rows
    reported `attempted: 2` for a four-juror panel — a record that reads better than the run
    (LAB-65 jury). run_headless writes the partial result itself instead."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out")
        os.makedirs(out)
        made = []

        def launch(exe, model, spec, rep, root, o, run_id, name):
            if model == "m/good":
                open(rep, "w").write(json.dumps({"verdict": "pass", "findings": []}))
            open(f"{o}/{model[-1]}.jsonl", "w").write("")
            proc = FakeProc([0] if model == "m/good" else [None])
            made.append(proc)
            return {"model": model, "proc": proc, "report": rep,
                    "events": f"{o}/{model[-1]}.jsonl", "stderr": f"{o}/{model[-1]}.jsonl",
                    "handles": (), "started": 0}

        m.opencode_exe = lambda: "opencode"
        m.launch_juror = launch
        m.POLL_S = 0
        said = []
        m.progress = lambda kind, message, **k: said.append((kind, message))
        rounds = {"n": 0}

        def interrupt(_):
            rounds["n"] += 1
            if rounds["n"] > 1:
                raise SystemExit("terminated")

        m.time = type("T", (), {"sleep": staticmethod(interrupt),
                                "monotonic": staticmethod(lambda: 0.0)})()
        results = []
        try:
            m.run_headless(["m/good", "m/slow"], "a.md", "i.md", "plan", out, "R", d, 9999,
                           results)
            raise AssertionError("expected the interrupt to propagate")
        except SystemExit:
            pass
    assert results, "an interrupted run must still record its result"
    r = results[0]
    assert (r["attempted"], r["reported"]) == (2, 1), r
    slow = [j for j in r["jurors"] if j["model"] == "m/slow"][0]
    assert "stopped before it finished" in slow["error"], slow
    assert made[1].killed, "the unfinished juror must be killed"
    # the caller is told, in words: stubbing progress to a no-op hid a swapped argument that
    # printed the line's kind as its message ("absent") on a real run
    told = [m_ for k, m_ in said if k == "absent"]
    assert told and "NO REPORT from slow" in told[0], said


def test_a_brace_in_a_path_never_aborts_the_panel():
    """The spec was formatted twice, so the second pass ran over the caller's own paths and a
    brace in one raised before a single juror launched (LAB-65 review). Restored after a range
    edit dropped it."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out")
        os.makedirs(out)
        specs = []

        def launch(exe, model, spec, rep, root, o, run_id, name):
            specs.append(spec)
            open(f"{o}/x.jsonl", "w").write("")
            return {"model": model, "proc": FakeProc([0]), "report": rep,
                    "events": f"{o}/x.jsonl", "stderr": f"{o}/x.jsonl",
                    "handles": (), "started": 0}

        m.opencode_exe = lambda: "opencode"
        m.launch_juror = launch
        m.POLL_S = 0
        m.progress = lambda *a, **k: None
        m.run_headless(["m/alpha"], "a{weird}.md", "i.md", "plan", out, "R", d, 60000, [])
    assert specs and "a{weird}.md" in specs[0], specs


def test_a_failed_launch_leaks_no_handle():
    """Both files are opened before the process starts, so a failure between them left the
    first open and unreferenced (LAB-65 properties pass)."""
    m = load()
    real, opened = open, []

    def flaky(path, *a, **k):
        if str(path).endswith(".stderr.txt"):
            raise OSError("no space")
        fh = real(path, *a, **k)
        opened.append(fh)
        return fh

    import builtins
    builtins.open = flaky
    try:
        with tempfile.TemporaryDirectory() as d:
            try:
                m.launch_juror("oc", "m/a", "s", f"{d}/r.json", d, d, "R", "a")
                raise AssertionError("expected the launch to fail")
            except OSError:
                pass
    finally:
        builtins.open = real
    assert opened and opened[0].closed, "the first handle must be closed"


def test_a_settled_juror_is_counted_against_the_panel():
    """`dispatch-mechanics.md` advertises `— 1 of 4`; nothing emitted it (LAB-65 review)."""
    m = load()
    row = {"model": "m/alpha", "seconds": 12.0, "parse_ok": True, "returned": True}
    assert m.headless_line(row, 1, 4)[1].endswith("— 1 of 4"), m.headless_line(row, 1, 4)


def test_main_runs_the_headless_path_end_to_end():
    """The mode that ships had no test through main(): the new tests all entered at
    run_headless, so argument wiring and the settle file's shape went uncovered (LAB-65 review)."""
    m = load()
    d = repo()
    cwd = os.getcwd()
    try:
        os.chdir(d)
        m.check_models = lambda models: None
        m.opencode_exe = lambda: "opencode"

        def launch(exe, model, spec, rep, root, o, run_id, name):
            open(rep, "w").write(json.dumps({"verdict": "revise", "findings": [
                {"dimension": "fit", "severity": "nit", "claim": "c", "evidence": "e"}],
                "impediments": []}))
            open(f"{o}/e.json", "w").write("")
            return {"model": model, "proc": FakeProc([0]), "report": rep,
                    "events": f"{o}/e.json", "stderr": f"{o}/e.json", "handles": (),
                    "started": 0}

        m.launch_juror = launch
        m.POLL_S = 0
        m.orca = lambda *a, **k: (_ for _ in ()).throw(AssertionError("headless called orca"))
        sys.argv = ["jury", "--artifact", "a.md", "--intent", "i.md", "--standard", "plan",
                    "--run-id", "E2E", "--out", "out", "--models", "m/alpha"]
        m.main()
        settled = json.load(open(os.path.join(d, "out", "E2E.jury-result.json")))
    finally:
        os.chdir(cwd)
    assert settled["run"] is None and settled["runId"] == "E2E", settled
    r = settled["results"][0]
    assert (r["reported"], r["confirmed"], r["attempted"]) == (1, 1, 1), r
    assert r["jurors"][0]["report"]["verdict"] == "revise", r["jurors"][0]


# --------------------------------------------------------------------- LAB-56 iteration 1
#
# The juror's own permission block, asserted rather than read.  An allowlist of `git status*`
# patterns was a write primitive: opencode matches a pattern against the whole command text,
# redirect included, and never path-checks the redirect target, so `git log > /tmp/x` ran and
# created it, `edit` and `external_directory` both denying.  These encode the invariant instead of
# that one vector.  They prove the file conforms to semantics measured against opencode
# 1.18.30 — not that opencode still behaves that way, which only a live probe can show.

JUROR_MD = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "..", "..", "..", "opencode", ".config", "opencode", "agents", "juror.md")

# opencode 1.18.30's permission surface.  A key absent from the block is not thereby denied:
# resolution starts from a built-in `"*": "allow"`, which is how `websearch` stayed open.
PERMISSION_KEYS = ("read", "edit", "glob", "grep", "list", "bash", "task", "external_directory",
                   "todowrite", "question", "webfetch", "websearch", "lsp", "skill", "doom_loop")


def juror_permissions():
    """The `permission:` block, hand-parsed: there is no yaml in the standard library and this
    suite must run with nothing installed."""
    front = open(JUROR_MD, encoding="utf-8").read().split("---\n")[1]
    keys, bash, in_bash = [], [], False
    for raw in front.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2:
            name, _, action = line.strip().partition(":")
            name = name.strip().strip('"')
            in_bash = name == "bash"
            keys.append((name, action.strip()))
        elif indent == 4 and in_bash:
            pattern, action = line.strip().rsplit(":", 1)
            bash.append((pattern.strip().strip('"'), action.strip()))
    assert bash, "no bash rules parsed — the block's shape changed and these tests went blind"
    return keys, bash


def permits(pattern, command):
    """opencode compiles `*` to `.*` and `?` to `.`, matches the whole string, and expands `~`
    in the pattern but never in the command a juror writes."""
    pattern = os.path.expanduser(pattern) if pattern.startswith("~") else pattern
    tail = ""
    if pattern.endswith(" *"):        # opencode rewrites this to `( .*)?`, so `orca x *`
        pattern, tail = pattern[:-2], "( .*)?"   # also permits a bare `orca x`
    rx = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern) + tail
    return re.fullmatch(rx, command, re.S) is not None


def resolve(rules, command):
    """Every command node must be permitted, the last matching rule wins, and a redirected
    statement is matched with its redirect still attached."""
    for part in re.split(r"&&|\|\||;|\|", command):
        part = part.strip()
        if not part:
            continue
        action = "deny"
        for pattern, act in rules:
            if permits(pattern, part):
                action = act
        if action != "allow":
            return action
    return "allow"


def test_no_permitted_command_can_carry_a_redirect():
    """Generated from the file's own allow entries, so an entry added later is covered the day
    it is added rather than when someone remembers to extend a list of vectors."""
    _, bash = juror_permissions()
    for pattern, action in bash:
        if action != "allow":
            continue
        sample = os.path.expanduser(pattern) if pattern.startswith("~") else pattern
        sample = sample.replace("*", "HEAD").replace("?", "~")
        assert resolve(bash, sample) == "allow", f"{pattern} does not permit its own {sample}"
        for redirect in (" > /tmp/pwned", " >> /tmp/pwned", " 2> /tmp/pwned"):
            assert resolve(bash, sample + redirect) == "deny", f"{pattern} permits a redirect"


def test_the_juror_shell_reaches_only_the_inspect_verbs():
    """The blindness this fixes was real, so the allows matter as much as the denies: a panel
    where every juror is refused its first move is half the panel producing nothing."""
    _, bash = juror_permissions()
    for command in ("git status", "git log --oneline", "ls agents/out",
                    "python3 claude/.claude/scripts/test_jury.py",
                    "~/.claude/scripts/inspect.sh status && rm -rf /",
                    "~/.claude/scripts/inspect.sh log | head -5",
                    "~/.claude/scripts/inspect.sh nonesuch"):
        assert resolve(bash, command) == "deny", f"{command!r} is permitted"
    for command in ("orca orchestration",  # bare: opencode's ` *` rewrite permits it
                    "~/.claude/scripts/inspect.sh status",
                    "~/.claude/scripts/inspect.sh show HEAD",
                    "~/.claude/scripts/inspect.sh ignored agents/out/x.md",
                    os.path.expanduser("~/.claude/scripts/inspect.sh log"),
                    "orca orchestration worker-done --outcome succeeded"):
        assert resolve(bash, command) == "allow", f"{command!r} is refused"


def test_every_permission_key_is_named_and_omissions_are_closed():
    """`websearch` reached the open internet from a whole panel because no one wrote it down.
    The leading `"*": deny` is what makes the enumeration a closure rather than a snapshot."""
    keys, _ = juror_permissions()
    assert keys[0] == ("*", "deny"), f"the block must open with a top-level deny, not {keys[0]}"
    named = dict(keys)
    missing = [k for k in PERMISSION_KEYS if k not in named]
    assert not missing, f"unnamed permission keys: {', '.join(missing)}"
    # Names alone would pass with any of these flipped to allow — which is the regression this
    # test is named for, so it asserts the action too (LAB-56 review)
    for key in ("webfetch", "websearch", "task", "question"):
        assert named[key] == "deny", f"{key} is {named[key]!r}, not deny"


def main():
    defined = re.findall(r"^def (test_\w+)", open(__file__).read(), re.M)
    dupes = sorted({n for n in defined if defined.count(n) > 1})
    if dupes:
        # globals() keeps one definition per name, so a duplicate is a test that never runs
        # while the tally still counts it — a green suite hiding a hole (LAB-65 review)
        print(f"  FAIL duplicate test names, so one of each never runs: {', '.join(dupes)}")
        return 1
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    assert len(tests) == len(defined), f"{len(defined)} defined, {len(tests)} collected"
    failed = []
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:
            failed.append((t.__name__, exc))
            print(f"  FAIL {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
