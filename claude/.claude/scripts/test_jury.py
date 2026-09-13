#!/usr/bin/env python3
"""Behaviour tests for jury.py.  Run: python3 claude/.claude/scripts/test_jury.py

By path, from the worktree root: `~/.claude/scripts/` resolves to the main checkout, so the
habitual path runs the copy you are not editing and goes green over a broken change.

No test framework, deliberately: this must run anywhere the jury does with nothing
installed.  Every test here exists because a real run broke, and each names the
iteration it came from — so when one fails, it says which decision is being reversed
rather than just going red.

Iteration 20 retired 35 of them, because LAB-66 deleted the code beneath them rather than
changing it: jurors are bounded processes, so there is no supervisor left to test.  Named so
the gap reads as a decision — orca failure receipts and call formation; keepalive filtering;
worktree resolution; boot failure; heartbeat liveness; settle message types and message
replay; dispatch retry; classify and dispatch-state reading; outcome_unknown resolution;
completion grace; orphan reclamation and the recovery sweep; release accounting; terminal
ordering; state-file accounting; juror-row reconciliation and absence_reason.  Eight more
pinned behaviour that outlived the path they were written against and were re-expressed
against run_headless/main instead.
"""
import importlib.util, json, os, re, subprocess, sys, tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jury.py")


def load():
    """A fresh module per test: these stub module-level functions heavily."""
    spec = importlib.util.spec_from_file_location("jury", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.event = lambda msg: None
    return m


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


def test_settle_file_written_when_the_run_dies():
    """The caller waits on this file, so a run that dies without writing one leaves them
    waiting for something that will never arrive."""
    m = load()
    d = repo()
    cwd = os.getcwd()
    try:
        os.chdir(d)
        m.check_models = lambda models: None
        m.run_headless = _boom("the panel exploded")
        sys.argv = argv(run_id="D", out="out")
        try:
            m.main()
        except RuntimeError:
            pass
        settled = json.load(open(os.path.join(d, "out", "D.jury-result.json")))
    finally:
        os.chdir(cwd)
    assert "the panel exploded" in settled["error"], settled


def _boom(msg):
    def raise_it(*a, **k):
        raise RuntimeError(msg)
    return raise_it


def test_crash_mid_panel_salvages_what_landed():
    """A crash must not hand the caller an empty settle file sitting next to perfectly good
    report files."""
    m = load()
    d = repo()
    cwd = os.getcwd()
    try:
        os.chdir(d)
        os.makedirs("out")
        open("out/S.a.alpha.json", "w").write(json.dumps(_verdict()))
        m.check_models = lambda models: None
        m.run_headless = _boom("died mid-panel")
        sys.argv = argv(run_id="S", out="out", models="m/alpha")
        try:
            m.main()
        except RuntimeError:
            pass
        settled = json.load(open(os.path.join(d, "out", "S.jury-result.json")))
    finally:
        os.chdir(cwd)
    r = settled["results"][0]
    assert r["salvaged"] is True and r["reported"] == 1, r
    assert r["jurors"][0]["report"]["verdict"] == "pass", r


def test_stale_report_is_never_served_as_this_runs_verdict():
    """A previous run's report sitting at this run's path would be counted as a verdict
    nobody reached this time."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out")
        os.makedirs(out)
        stale = os.path.join(out, "R.a.alpha.json")
        open(stale, "w").write(json.dumps(_verdict("block")))
        # the juror writes nothing at all, so anything read back came from the stale file
        _, row, _, _ = headless(m, d, [0], report=None)
        assert row["parse_ok"] is False, row
        assert "wrote no report" in row["error"], row


def test_unparseable_report_keeps_its_text():
    """A real finding must not vanish with the parse failure that stopped it being counted."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        _, row, _, _ = headless(m, d, [0], report="{not json at all")
        assert row["parse_ok"] is False, row
        assert "unreadable report" in row["error"], row
        assert row["raw"].startswith("{not json"), row


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


def test_output_lands_at_the_repo_root_not_the_cwd():
    """The juror's edit permission is the relative glob `agents/out/*`, so relative has to
    mean the same thing on both sides — the repo root, not wherever the runner was invoked."""
    m = load()
    d = repo()
    sub = os.path.join(d, "deep", "inside")
    os.makedirs(sub)
    cwd = os.getcwd()
    try:
        os.chdir(sub)
        m.check_models = lambda models: None
        m.run_headless = lambda *a, **k: None
        sys.argv = argv(run_id="ROOT", out="out")
        m.main()
    finally:
        os.chdir(cwd)
    assert os.path.exists(os.path.join(d, "out", "ROOT.jury-result.json")), "not at the root"
    assert not os.path.exists(os.path.join(sub, "out")), "written at the cwd instead"


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


def test_retry_is_gone():
    """89 dispatches, none ever `failed`: every non-success traced to the coordinator's own
    terminal-closing defect or an explicit stop. Retry recovered from a condition that had
    never occurred, and would have fired on all nineteen."""
    j = load()
    assert not hasattr(j, "retry_failures"), "retry_failures survived"
    assert "--retry" not in open(SCRIPT).read(), "the --retry flag survived"


def _report(impediments=None, verdict="pass"):
    r = {"verdict": verdict, "findings": []}
    if impediments is not None:
        r["impediments"] = impediments
    return r


WALL = {"tool": "bash", "target": "git status", "kind": "refused",
        "refusal": "denied by the bash allowlist", "purpose": "see what changed"}


def _verdict(verdict="pass"):
    return {"verdict": verdict, "findings": []}


def _launch_writing(report):
    """A launch_juror that writes one report and exits 0, for tests entering through main()."""
    def launch(exe, model, spec, rep, root, o, run_id, name):
        open(rep, "w").write(report)
        open(f"{o}/e.json", "w").write("")
        return {"model": model, "proc": FakeProc([0]), "report": rep,
                "events": f"{o}/e.json", "stderr": f"{o}/e.json", "handles": (), "started": 0}
    return launch


def test_a_malformed_impediment_never_costs_the_verdict():
    """The loop asks its workers to report defects in the loop, which only holds while
    reporting one is free.  A bad entry costs its own slot and nothing else — `is_report`
    stays the only thing that can sink a verdict (LAB-57)."""
    j = load()
    report = _report([WALL, "not a dict", {"tool": "telepathy", "target": "x", "kind": "refused"}])
    assert j.is_report(report), report

    with tempfile.TemporaryDirectory() as d:
        _, row, _, _ = headless(j, d, [0], report=json.dumps(report))
        assert row["returned"] is True and row["report"]["verdict"] == "pass", row

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
    m = load()
    d = repo()
    cwd = os.getcwd()
    try:
        os.chdir(d)
        m.check_models = lambda models: None
        m.opencode_exe = lambda: "opencode"
        m.POLL_S = 0
        m.launch_juror = _launch_writing(json.dumps(_report([WALL])))
        sys.argv = argv(run_id="W", out="out", models="m/alpha")
        m.main()
        result = json.load(open(os.path.join(d, "out", "W.jury-result.json")))["results"][0]
    finally:
        os.chdir(cwd)
    assert result["impediments"]["walls"][0]["target"] == "git status", result
    assert result["impediments"]["reported_by"] == ["m/alpha"], result
    assert result["reported"] == 1 and result["confirmed"] == 1, result


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
    """Orca has no role in the juror path: a call would mean state nobody settles (LAB-65).
    Asserted structurally rather than by stubbing a call that no longer exists — a stub on a
    deleted name passes whatever the runner does (LAB-66)."""
    m = load()
    assert not hasattr(m, "orca"), "the orca helper survived"
    body = open(SCRIPT).read()
    for gone in ("orca ", "worker-start", "worker_done", "dispatchId", "--terminal"):
        assert gone not in body, f"{gone!r} survived in the runner"


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
        sys.argv = ["jury", "--artifact", "a.md", "--intent", "i.md", "--standard", "plan",
                    "--run-id", "E2E", "--out", "out", "--models", "m/alpha"]
        m.main()
        settled = json.load(open(os.path.join(d, "out", "E2E.jury-result.json")))
    finally:
        os.chdir(cwd)
    assert settled["runId"] == "E2E" and settled["streams"], settled
    # the Orca Run id went with the supervisor; a null field would have outlived its meaning
    assert "run" not in settled, settled
    r = settled["results"][0]
    assert (r["reported"], r["confirmed"], r["attempted"]) == (1, 1, 1), r
    assert r["jurors"][0]["report"]["verdict"] == "revise", r["jurors"][0]


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
                    "~/.claude/scripts/inspect.sh nonesuch",
                    # nothing observes a juror, so nothing it runs needs to report to Orca.
                    # These two read `allow` until LAB-66 removed the entry serving them.
                    "orca orchestration",
                    "orca orchestration worker-done --outcome succeeded"):
        assert resolve(bash, command) == "deny", f"{command!r} is permitted"
    for command in ("~/.claude/scripts/inspect.sh status",
                    "~/.claude/scripts/inspect.sh show HEAD",
                    "~/.claude/scripts/inspect.sh ignored agents/out/x.md",
                    os.path.expanduser("~/.claude/scripts/inspect.sh log")):
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
