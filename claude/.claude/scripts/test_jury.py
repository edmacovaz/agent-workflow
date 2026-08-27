#!/usr/bin/env python3
"""Behaviour tests for jury.py.  Run: python3 ~/.claude/scripts/test_jury.py

No test framework, deliberately: this must run anywhere the jury does with nothing
installed.  Every test here exists because a real run broke, and each names the
iteration it came from — so when one fails, it says which decision is being reversed
rather than just going red.
"""
import importlib.util, json, os, subprocess, sys, tempfile

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
    a = ["jury", "--artifact", "a.md", "--intent", "i.md", "--standard", "plan"]
    for k, v in kw.items():
        a += [f"--{k.replace('_', '-')}", *(v if isinstance(v, list) else [v])]
    return a


def stub_orca(dispatch_id="d1", on_start=None):
    def orca(*a, **k):
        op = " ".join(a[:2])
        if op == "orchestration worker-start":
            if on_start:
                on_start()
            return {"dispatchId": dispatch_id}
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
        assert by_model["m/alpha"] == "never reported", by_model
        assert len([e for e in events if "bravo" in e]) == 1, events   # announced once
    finally:
        os.chdir(prev)


# ------------------------------------------------------------------- iteration 6, 8
def test_collect_honours_a_run_level_deadline():
    j = load(); clock = Clock(); j.time = clock
    events = []; j.event = events.append
    expected = {"d1": "v/alpha", "d2": "v/bravo", "d3": "v/charlie", "d4": "v/delta"}
    calls = []
    def orca(*a, **k):
        calls.append(list(a))
        if "--timeout-ms" not in a:
            return {}                            # the closing ack carries no wait
        wait = int(a[a.index("--timeout-ms") + 1]) / 1000
        if len(calls) == 1:
            clock.t += 1
            return {"deliveryId": "D1", "messages": [
                {"type": "worker_done", "payload": {"dispatchId": d, "outcome": "succeeded"}}
                for d in ("d1", "d2")]}
        clock.t += wait
        return {"timedOut": True, "messages": [], "deliveryId": None}
    j.orca = orca

    done = j.collect(expected, 600_000, "RUN")
    assert len(done) == 2, done
    assert clock.t - 1000.0 <= 600.0, "ran past its own deadline"
    waits = [e for e in events if "still waiting" in e]
    assert len(waits) == 1, waits                       # one heartbeat, at the halfway mark
    assert "charlie" in waits[0] and "delta" in waits[0] and "bravo" not in waits[0]
    assert all("up to" in e for e in events if "returned" in e), events


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


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
