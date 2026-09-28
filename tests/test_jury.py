#!/usr/bin/env python3
"""Behaviour tests for jury.py, statusline.py and session-rules.sh.  Run: python3 tests/test_jury.py

By path, from the worktree root.  An installed plugin is a copy under `~/.claude/plugins/cache/`
at a path that changes on every update, so testing the installed runner exercises the copy you
are not editing and goes green over a broken change (LAB-80).

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

# This suite spans the split LAB-80 made: `jury.py` ships inside the plugin, while
# `statusline.py` stays in the stow package because `settings.json` must name it by a
# literal path and no plugin component owns the status-line slot.
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "plugins", "loop", "scripts", "jury.py")
STATUSLINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "claude", ".claude", "scripts", "statusline.py")


def load():
    """A fresh module per test: these stub module-level functions heavily."""
    spec = importlib.util.spec_from_file_location("jury", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.event = lambda msg: None
    return m


def load_statusline():
    """The status-line renderer (LAB-86). It reads the file jury.py writes, so it is tested
    beside it: the JSONL schema is the only thing they share, and a change to one that breaks
    the other should fail here rather than in a live panel."""
    spec = importlib.util.spec_from_file_location("statusline", STATUSLINE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def progress_file(*rows, name="LAB-1-20260921-120000-1234"):
    """A run's progress file, written the way jury.py's record() writes one."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, f"{name}.progress.jsonl")
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def working(model, message, artifact=None):
    row = {"t": "2026-09-21T12:00:00", "kind": "working", "message": message, "model": model}
    return {**row, "artifact": artifact} if artifact else row


def rendered(text):
    """What the caller actually sees. Claude Code puts a status line through
    `stdout.trim().split("\\n").flatMap(d => d.trim() || []).join("\\n")` before rendering it,
    so anything this drops was never on screen — an indent written here included (LAB-86)."""
    return [l for l in (x.strip() for x in text.strip().split("\n")) if l]


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


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
        m.check_models = lambda models: None

        def wrote_then_died(*a, **k):
            # written from inside the run, which is what "mid-panel" means: the juror had
            # landed its verdict before the crash. A report seeded before main() starts is a
            # previous run's by definition now, and is the next test's subject (LAB-83 review)
            open("out/S.a.alpha.json", "w").write(json.dumps(_verdict()))
            raise RuntimeError("died mid-panel")

        m.run_headless = wrote_then_died
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


def test_salvage_never_serves_a_previous_runs_verdict():
    """run_headless deletes a stale report before launching, but salvage is reached on the
    path where run_headless never ran — so a hand-passed run id could have a previous run's
    verdict counted in `reported`, which is the error that deletion exists to prevent."""
    m = load()
    d = repo()
    cwd = os.getcwd()
    try:
        os.chdir(d)
        os.makedirs("out")
        open("out/S.a.alpha.json", "w").write(json.dumps(_verdict("block")))
        os.utime("out/S.a.alpha.json", (1_000_000, 1_000_000))     # a run long finished
        m.check_models = _boom("died before any juror started")
        sys.argv = argv(run_id="S", out="out", models="m/alpha")
        try:
            m.main()
        except RuntimeError:
            pass
        settled = json.load(open(os.path.join(d, "out", "S.jury-result.json")))
    finally:
        os.chdir(cwd)
    assert settled["results"] == [], settled
    assert "died before any juror started" in settled["error"], settled


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
        _, row, _, _, _ = headless(m, d, [0], report=None)
        assert row["parse_ok"] is False, row
        assert "wrote no report" in row["error"], row


def test_unparseable_report_keeps_its_text():
    """A real finding must not vanish with the parse failure that stopped it being counted."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        _, row, _, _, _ = headless(m, d, [0], report="{not json at all")
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
    appeared — never that a juror was alive and working.

    Both halves are asserted since LAB-75 split them: a state change is printed *and* recorded.
    A split that quietly stopped printing landings too would restore the silence this replaced,
    and only the stdout assertion below can tell the two apart."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        said = []
        j.event = lambda msg: said.append(msg)
        j.PROGRESS["path"] = "p.jsonl"
        j.progress("state", "alpha is still reviewing", model="m/alpha",
                   state="ready", heartbeat_age=40, phase=None)
        j.progress("returned", "alpha returned", model="m/alpha")
        rows = [json.loads(l) for l in open("p.jsonl")]
        assert [r["kind"] for r in rows] == ["state", "returned"], rows
        assert rows[0]["message"] == "alpha is still reviewing", rows
        assert rows[0]["state"] == "ready" and rows[0]["heartbeat_age"] == 40, rows
        assert "phase" not in rows[0], "None fields are noise, not state"
        assert said == ["alpha is still reviewing", "alpha returned"], said
    finally:
        os.chdir(prev)


def test_a_recorded_line_reaches_the_file_and_never_the_caller():
    """A printed line is a conversation turn, and no silence is available once one exists — so
    a panel printing a heartbeat per juror per minute drew multi-paragraph analyses of a rising
    counter (LAB-75). The line is still worth keeping, for a stream that was missed or a run
    that has to be reconstructed, so it goes to the file and stops there."""
    j = load(); prev = os.getcwd(); os.chdir(repo())
    try:
        said = []
        j.event = lambda msg: said.append(msg)
        j.PROGRESS["path"] = "p.jsonl"
        j.record("working", "alpha — running 120s, last read a.md (×3)",
                 model="m/alpha", phase=None)
        rows = [json.loads(l) for l in open("p.jsonl")]
        assert [r["kind"] for r in rows] == ["working"], rows
        assert "×3" in rows[0]["message"] and rows[0]["model"] == "m/alpha", rows
        assert "phase" not in rows[0], "None fields are noise, not state"
        assert said == [], said
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
        _, row, _, _, _ = headless(j, d, [0], report=json.dumps(report))
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
    # two channels, captured apart: `said` reached the caller and cost a turn, `wrote` only
    # reached the progress file. Collapsing them is what hid the heartbeats (LAB-75)
    said, wrote = [], []
    m.progress = lambda kind, msg, **kw: said.append((kind, msg))
    m.record = lambda kind, msg, **kw: wrote.append((kind, msg))
    results = []
    m.run_headless(["m/alpha"], "a.md", "i.md", "plan", out, "R", d, timeout_ms, results)
    res = results[0]
    return res, res["jurors"][0], said, wrote, made.get("proc")


def test_a_clean_exit_with_a_verdict_is_reported_and_confirmed():
    m = load()
    with tempfile.TemporaryDirectory() as d:
        good = json.dumps({"verdict": "pass", "findings": [], "impediments": []})
        res, row, _, _, _ = headless(m, d, [0], report=good)
        assert row["returned"] and row["parse_ok"], row
        assert res["reported"] == 1 and res["confirmed"] == 1, res


def test_a_clean_exit_without_a_report_is_not_a_verdict():
    """Exit 0 settles the process, not the review — `confirmed` without `reported` is exactly
    the juror this distinguishes, and counting it as a pass is counting silence as approval."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        res, row, _, _, _ = headless(m, d, [0])
        assert row["returned"] and not row["parse_ok"], row
        assert "wrote no report" in row["error"], row
        assert res["confirmed"] == 1 and res["reported"] == 0, res


def test_a_non_zero_exit_carries_its_code_and_its_reason():
    m = load()
    with tempfile.TemporaryDirectory() as d:
        _, row, _, _, _ = headless(m, d, [3], stderr="provider refused the request")
        assert row["exit"] == 3 and not row["returned"], row
        assert "exited 3" in row["error"] and "provider refused" in row["error"], row


def test_a_juror_killed_at_the_deadline_says_so():
    """A timeout is a clean loss with a name, never a juror that 'did not respond'."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        # a real clock: the deadline has to be short or the suite waits it out (LAB-65)
        _, row, said, _, proc = headless(m, d, [None], timeout_ms=1)
        assert proc.killed, "the deadline must actually kill it"
        assert not row["returned"] and "timeout" in row["error"], row
        assert any(k == "timeout" for k, _ in said), said


def test_a_wall_survives_the_headless_path_intact():
    """The report contract is what LAB-55/57/32 read, so it must cross unchanged (LAB-65)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        walled = json.dumps({"verdict": "pass", "findings": [], "impediments": [
            {"tool": "bash", "target": "git status", "kind": "refused",
             "attempts": 4, "refusal": "denied", "purpose": "check the tree"}]})
        res, row, _, _, _ = headless(m, d, [0], report=walled)
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
    only stop rule: a juror repeating itself is described, not killed — and since LAB-75 it is
    described to the file rather than to the caller, so the description costs no turn."""
    m = load()
    ev = "\n".join(json.dumps({"part": {"type": "tool", "tool": "bash",
                                        "state": {"input": {"command": "ls"}}}})
                   for _ in range(9))
    with tempfile.TemporaryDirectory() as d:
        m.REPORT_EVERY_S = 0
        _, row, said, wrote, proc = headless(
            m, d, [None, None, 0],
            report=json.dumps({"verdict": "pass", "findings": []}), events=ev)
        assert not proc.killed, "a repeating juror must not be killed"
        assert row["returned"] and row["parse_ok"], row
        assert any(k == "working" and "×9" in msg for k, msg in wrote), wrote
        assert not any(k == "working" for k, _ in said), said


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
        "filePath": os.path.join(root, "tests/test_jury.py")}}}})
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


def test_the_spec_opens_on_the_report_file():
    """qwen gave well-formed verdicts as its final message instead of a file, while the path came
    last and unemphasised (LAB-92)."""
    m = load()
    spec = m.SPEC.format(artifact="a.md", intent="i.md", standard="plan",
                         report="agents/out/R.a.m.json")
    first = spec.split(". ")[0]
    assert "agents/out/R.a.m.json" in first and "write tool" in first, spec


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


# What a panel cost (LAB-83).  opencode wrote `cost` and `tokens` on every step all along and
# nothing read them, which is the measurement that reopened LAB-31's gap.  Totals and token
# counts here are run STE-266-20260917-224009's own; where a juror's 42 steps are collapsed
# into two, the first is that run's real first step and the second is the remainder, chosen so
# the sum lands on the total it actually reached.


def _step(cost=None, **tokens):
    """One step-finish, shaped as opencode writes it."""
    part = {"type": "step-finish"}
    if cost is not None:
        part["cost"] = cost
    if tokens:
        cache = {"read": tokens.pop("cache_read", 0), "write": tokens.pop("cache_write", 0)}
        part["tokens"] = dict(tokens, cache=cache)
    return json.dumps({"type": "step_finish", "part": part})


def _call(tool="read", **arg):
    return json.dumps({"type": "tool_use",
                       "part": {"type": "tool", "tool": tool, "state": {"input": arg}}})


def _stream(d, *lines, name="e.jsonl"):
    path = os.path.join(d, name)
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def test_a_panel_reports_what_each_juror_cost():
    """LAB-31 closed with spend unrecorded, and LAB-37 carried it forward as a gap needing a
    platform.  Both readings were wrong.  These are the deepseek juror's own steps."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        spent = m.tally(_stream(d, _step(0.0042564, input=27660, output=179),
                                _step(0.0769436, input=215465, output=46230)))
        assert spent["cost"] == 0.0812, spent
        assert (spent["steps"], spent["calls"]) == (2, 0), spent
        assert spent["tokens"]["input"] == 243125, spent


def test_a_stream_with_no_cost_says_unknown_and_never_zero():
    """A free model and a stream that lost its costs must not read alike: summing an absent
    figure to 0 reports a panel that cost nothing, which is a claim nobody measured."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        blank = m.tally(_stream(d, _step(), _step(), name="blank.jsonl"))
        assert blank["cost"] is None and blank["steps"] == 2, blank
        free = m.tally(_stream(d, _step(0.0), name="free.jsonl"))
        assert free["cost"] == 0 and free["cost"] is not None, free
        partial = m.tally(_stream(d, _step(0.01), _step(), name="partial.jsonl"))
        assert partial["cost"] == 0.01 and partial["steps_without_cost"] == 1, partial


def test_cache_reads_count_as_the_work_they_were():
    """gpt-5.6-luna billed 30 input tokens against 530K read from cache, so input and output
    alone understate what a juror did by orders of magnitude."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        spent = m.tally(_stream(d, _step(0.0463, input=30, output=1460, reasoning=1991,
                                         cache_read=530890, cache_write=126148)))
        tok = spent["tokens"]
        assert (tok["cache_read"], tok["cache_write"]) == (530890, 126148), tok
        assert (tok["input"], tok["reasoning"]) == (30, 1991), tok


def test_a_torn_cost_stream_never_costs_the_panel():
    """tally() is read from the wait loop, whose finally kills every juror — so an escape here
    destroys the panel it was measuring.  Same contract as observed(), same reason (LAB-65)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        torn = _stream(d, _step(0.01, input=5), '{"type":"step_fin')
        assert m.tally(torn)["cost"] == 0.01, "a torn last line is ordinary, not fatal"
        # mid-stream, not trailing: JSONDecodeError is a ValueError, so the reader's outer
        # handler catches a torn line either way — but it ends the whole stream, where the
        # per-line skip loses only that line.  A trailing bad line cannot tell them apart
        mid = _stream(d, _step(0.01), '{"type":"step_fin', _step(0.02), name="mid.jsonl")
        assert m.tally(mid)["cost"] == 0.03, "a line after a torn one must still count"
        for junk in ('{"part": 3}', '{"part": []}', '{"part": {"type": "step-finish"}}',
                     '{"part": {"type": "step-finish", "cost": "free"}}',
                     '{"part": {"type": "step-finish", "cost": true}}',
                     '{"part": {"type": "step-finish", "tokens": []}}',
                     '{"part": {"type": "tool", "state": []}}',
                     '[]', 'null', '3', 'not json at all', ''):
            m.tally(_stream(d, junk, name="junk.jsonl"))          # must not raise
        assert m.tally(os.path.join(d, "never-written.jsonl")) is None
        # bool is not a figure: True would otherwise sum as one dollar and one token
        lying = m.tally(_stream(d, '{"part": {"type": "step-finish", "cost": true}}',
                                name="lying.jsonl"))
        assert lying["cost"] is None, lying


def test_a_juror_killed_at_the_deadline_still_reports_its_spend():
    """The kill is where the figure matters most: the run is over and the money is gone
    either way.  It falls out of headless_row rather than needing a path of its own."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        ev = "\n".join([_step(0.0231, input=900), _call("read", filePath="a.md")])
        _, row, said, _, proc = headless(m, d, [None], events=ev, timeout_ms=1)
        assert proc.killed, "the deadline must actually kill it"
        assert (row["cost"], row["steps"], row["calls"]) == (0.0231, 1, 1), row
        # `said`, not `wrote`: a juror settling is a change of state, so its line is one the
        # caller is woken for — the distinction LAB-75 drew
        assert any("$0.0231" in msg for _, msg in said), said


def test_a_repeated_call_is_counted_and_never_priced():
    """Cost sits on the step and never on the call, so what a juror burned repeating itself is
    a count here.  LAB-71 bounds the 786-call case and deliberately leaves the 16-call one;
    this is what makes the second a number rather than an impression."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        lines = ([_step(0.05)] + [_call("bash", command="git status")] * 16
                 + [_call("read", filePath="a.md")])
        spent = m.tally(_stream(d, *lines))
        top = spent["repeats"][0]
        assert (top["tool"], top["calls"]) == ("bash", 16), spent["repeats"]
        assert "cost" not in top, "no per-call price exists to report"
        assert spent["calls"] == 17, spent
        assert [r for r in spent["repeats"] if r["tool"] == "read"] == [], spent["repeats"]


def test_a_targetless_call_is_never_reported_as_repeated():
    """Two calls with no target cannot be told apart, so counting them as one repeated call
    asserts a repetition nobody saw — the rule working_line already follows."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        spent = m.tally(_stream(d, *[_call("todowrite")] * 7))
        assert spent["calls"] == 7 and spent["repeats"] == [], spent


def test_the_repeats_rollup_is_capped():
    """glm-5.3-flash made 786 near-identical calls on one panel.  Uncapped, that list would be
    the largest thing in the settle file."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        lines = []
        for i in range(12):
            lines += [_call("read", filePath=f"f{i}.md")] * (i + 2)
        spent = m.tally(_stream(d, *lines))
        assert len(spent["repeats"]) == m.REPEATS_TOP, spent["repeats"]
        assert spent["repeats"][0]["calls"] == 13, spent["repeats"][0]


def test_the_settle_file_carries_what_the_panel_spent():
    """The result is the caller's record, so the figure has to survive into it rather than
    living only on a progress line that scrolled past."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        good = json.dumps({"verdict": "pass", "findings": [], "impediments": []})
        res, row, said, _, _ = headless(m, d, [0], report=good,
                                        events=_step(0.0463, input=30, cache_read=530890))
        assert res["spend"]["cost"] == 0.0463, res["spend"]
        assert res["spend"]["steps"] == 1 and "jurors_without_cost" not in res["spend"], res
        assert row["tokens"]["cache_read"] == 530890, row
        assert any(k == "spend" and "$0.0463" in msg for k, msg in said), said


def test_a_juror_with_no_cost_is_named_rather_than_counted_free():
    """A total that quietly stands for less than the whole panel is the same error as counting
    silence as approval, which this runner exists to avoid."""
    m = load()
    mixed = m.spend_rollup([{"model": "m/a", "cost": 0.02, "steps": 3, "calls": 4},
                            {"model": "m/b"}])
    assert mixed["cost"] == 0.02 and mixed["jurors_without_cost"] == ["m/b"], mixed
    assert (mixed["steps"], mixed["calls"]) == (3, 4), mixed
    assert m.spend_rollup([{"model": "m/b"}])["cost"] is None


def test_a_cents_scale_panel_keeps_the_differences_it_is_chosen_on():
    """LAB-32 picks a panel on these figures, and two decimals halve how many of them there
    are to pick between."""
    m = load()
    measured = [0.0812, 0.0535, 0.0463, 0.0793]
    assert len({m.money(c) for c in measured}) == 4
    assert len({f"${c:.2f}" for c in measured}) == 2


def test_a_crashed_run_salvages_what_it_spent_not_only_what_it_collected():
    """salvage() is the caller's last chance at a crashed panel, and the money is as gone as
    the verdicts are written."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        streams, out = os.path.join(d, "streams"), os.path.join(d, "out")
        os.makedirs(streams), os.makedirs(out)
        m.stream_dir = lambda run_id: streams
        open(m.report_path(out, "R", "a", "m/alpha"), "w").write(
            json.dumps({"verdict": "pass", "findings": []}))
        open(m.stream_stem(streams, "R", "a", "m/alpha") + ".events.jsonl", "w").write(
            _step(0.031) + "\n")
        rows = m.salvage(out, "R", "a.md", ["m/alpha"], 0)
        assert rows[0]["salvaged"] and rows[0]["cost"] == 0.031, rows
        assert rows[0]["parse_ok"], rows


# The jury's own findings on this change, and /code-review's (LAB-83 review).  Each names the
# reader that caught it, because four of the eight were things the author's own tests missed.


def test_every_settled_juror_carries_its_cost():
    """The middle branch — a verdict written, then killed at the backstop — dropped the figure
    while a juror that wrote nothing kept it.  That is the expensive juror, and the comment on
    the branch below it already said a juror that died still spent what it spent."""
    m = load()
    base = {"model": "m/alpha", "seconds": 42.0, "cost": 0.0812}
    lines = [m.headless_line(dict(base, parse_ok=True, returned=True), 1, 4)[1],
             m.headless_line(dict(base, parse_ok=True, returned=False,
                                  error="killed at the 42s timeout"), 1, 4)[1],
             m.headless_line(dict(base, parse_ok=False, returned=False,
                                  error="killed at the 42s timeout"))[1]]
    for line in lines:
        assert "$0.0812" in line, line


def test_a_non_finite_figure_never_reaches_the_settle_file():
    """`json.loads` accepts a bare NaN, one contaminates every sum it reaches, and `json.dump`
    writes it back out as bare NaN — which is not valid JSON, so one malformed step would make
    the caller's only record unreadable to a strict parser (jury: gpt-5.6-luna)."""
    m = load()
    assert m.number(float("nan")) is None
    assert m.number(float("inf")) is None and m.number(float("-inf")) is None
    # an int json.loads built from 400 digits: isfinite cannot convert it, and the guard
    # against a malformed stream must not itself be how a malformed stream kills a panel
    assert m.number(int("9" * 400)) is None
    with tempfile.TemporaryDirectory() as d:
        spent = m.tally(_stream(d, '{"part": {"type": "step-finish", "cost": 0.05}}',
                                '{"part": {"type": "step-finish", "cost": NaN}}',
                                '{"part": {"type": "step-finish", "tokens": {"input": %s}}}' % ("9" * 400),
                                '{"part": {"type": "step-finish", "tokens": {"input": Infinity}}}'))
        assert spent["cost"] == 0.05, spent
        assert spent["steps_without_cost"] == 3, spent
        assert spent["tokens"]["input"] == 0, spent
        # the whole point: the record has to survive a strict reader
        def strict(c):
            raise AssertionError(f"bare {c} reached the settle file")
        json.loads(json.dumps({"spend": m.spend_rollup([dict(model="m/a", **spent)])}),
                   parse_constant=strict)


def test_salvage_never_prices_a_juror_this_run_did_not_launch():
    """Streams are kept on purpose and salvage runs where nothing truncated them, so a reused
    run id let a previous run's stream be reported as this one's spend — $4.20 for a juror that
    never started (/code-review)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        streams, out = os.path.join(d, "streams"), os.path.join(d, "out")
        os.makedirs(streams), os.makedirs(out)
        m.stream_dir = lambda run_id: streams
        open(m.report_path(out, "R", "a", "m/alpha"), "w").write(
            json.dumps({"verdict": "pass", "findings": []}))
        stale = m.stream_stem(streams, "R", "a", "m/alpha") + ".events.jsonl"
        open(stale, "w").write(_step(4.2) + "\n")
        os.utime(stale, (1_000_000, 1_000_000))            # a previous run, long finished
        rows = m.salvage(out, "R", "a.md", ["m/alpha"], since=2_000_000)
        assert rows[0]["parse_ok"], "the verdict is still salvaged"
        assert "cost" not in rows[0], rows[0]
        assert m.spend_rollup(rows)["cost"] is None, m.spend_rollup(rows)
        # and a stream this run did write is still read
        os.utime(stale, (3_000_000, 3_000_000))
        assert m.salvage(out, "R", "a.md", ["m/alpha"], since=2_000_000)[0]["cost"] == 4.2


def test_a_panel_stopped_mid_pass_settles_each_juror_once():
    """TaskStop is the way SKILL.md says to stop a panel, and main turns that SIGTERM into a
    SystemExit that lands wherever the loop happens to be. Settled jurors left in `pending`
    are swept a second time by run_headless's finally — which always miscounted `attempted`
    and, since spend is summed, doubles the money too (/code-review).

    Driven through run_headless rather than by reimplementing its finally here: a test that
    inlines the logic it is checking passes whatever the runner does (LAB-83 review)."""
    m = load()
    m.POLL_S = 0
    m.progress = lambda *a, **k: None
    m.opencode_exe = lambda: "opencode"
    d = tempfile.mkdtemp()
    out = os.path.join(d, "out")
    os.makedirs(out, exist_ok=True)
    costs = {"m/a": 0.1, "m/b": 0.2, "m/c": 0.4}

    class Exited:
        def poll(self): return 0
        def kill(self): pass
        def wait(self): return 0

    def launch(exe, model, spec, rep, root, streams, run_id, name):
        path = os.path.join(d, f"{model.replace('/', '_')}.jsonl")
        open(path, "w").write(_step(costs[model]) + "\n")
        return {"model": model, "proc": Exited(), "report": rep, "events": path,
                "stderr": path, "handles": (), "started": m.time.monotonic()}

    m.launch_juror = launch
    real, seen = m.headless_row, {"n": 0}

    def exiting(j, rc, **kw):
        seen["n"] += 1
        if seen["n"] == 2:                  # the stop lands after the first juror settled
            raise SystemExit("terminated")
        return real(j, rc, **kw)

    m.headless_row = exiting
    results = []
    try:
        m.run_headless(list(costs), "a.md", "i.md", "plan", out, "R", d, 60000, results)
    except SystemExit:
        pass
    m.headless_row = real

    assert results, "the finally must still hand back a result"
    rows = results[0]["jurors"]
    models = [r["model"] for r in rows]
    assert sorted(models) == ["m/a", "m/b", "m/c"], models
    assert len(models) == len(set(models)), f"a juror was settled twice: {models}"
    assert results[0]["attempted"] == 3, results[0]["attempted"]
    assert results[0]["spend"]["cost"] == 0.7, results[0]["spend"]


def test_a_panel_that_made_calls_but_finished_no_step_still_reports():
    """A juror killed inside its first model call has calls and no step-finish, so cost is None
    and steps is 0 — and the spend line was suppressed entirely, while the settle file carried
    the counts (jury: glm-5.3-flash, /code-review). A panel that read nothing at all still says
    nothing, which is the one case the doc now names."""
    m = load()
    said = []
    m.progress = lambda kind, msg, **kw: said.append((kind, msg))
    m.announce_spend("LAB-83", {"cost": None, "steps": 0, "calls": 9,
                                "jurors_without_cost": ["m/a"]})
    assert said and said[0][0] == "spend", said
    assert "cost unknown" in said[0][1] and "9 calls" in said[0][1], said
    # and a panel that truly read nothing still says nothing: "$0.0000" would be a claim
    said.clear()
    m.announce_spend("LAB-83", {"cost": None, "steps": 0, "calls": 0})
    assert said == [], said


def test_never_raises_stops_bugs_but_never_the_panel():
    """The contract four functions declared and fourteen hand-written except clauses were meant
    to enforce. Three rounds each found one whose clause did not match reality, so it is a
    construct now (LAB-83 review).

    The BaseException half is the part that matters most: main turns SIGTERM into SystemExit
    on purpose, and swallowing it would leave a panel nothing could stop — the opposite of the
    failure this guards."""
    m = load()

    @m.never_raises(default="fallback")
    def boom(exc):
        raise exc

    for exc in (ValueError("closed file"), OverflowError("too large"), OSError("gone"),
                TypeError("shape"), KeyError("missing"), RuntimeError("?")):
        assert boom(exc) == "fallback", exc

    for exc in (SystemExit("terminated"), KeyboardInterrupt()):
        try:
            boom(exc)
        except BaseException as got:
            assert type(got) is type(exc), got
        else:
            raise AssertionError(f"{type(exc).__name__} must pass through, not be swallowed")

    # and the guarded readers really are guarded, whatever the argument
    assert m.tally(None) is None and m.observed(None) is None
    assert m.stderr_tail(None) == ""
    m.PROGRESS["path"] = None
    m.event = lambda msg: (_ for _ in ()).throw(ValueError("closed"))
    m.progress("returned", "alpha returned")          # must not raise


def test_a_closed_stdout_never_orphans_a_juror():
    """`except OSError` does not catch ValueError, and a closed stdout raises one. Escaping
    progress() lands in run_headless's finally, which then kills no remaining juror and
    records no result — orphaned `opencode run` children spending tokens beside a settle file
    saying the panel was empty, which is worse than the double-settle this replaced
    (/code-review)."""
    m = load()
    m.opencode_exe = lambda: "opencode"
    m.POLL_S = 0
    d = tempfile.mkdtemp()
    out = os.path.join(d, "out")
    os.makedirs(out, exist_ok=True)
    killed = []

    class NeverExits:
        def __init__(self, model): self.model = model
        def poll(self): return None
        def kill(self): killed.append(self.model)
        def wait(self): return -9

    def launch(exe, model, spec, rep, root, streams, run_id, name):
        path = os.path.join(d, "e.jsonl")
        open(path, "w").write("")
        return {"model": model, "proc": NeverExits(model), "report": rep, "events": path,
                "stderr": path, "handles": (), "started": m.time.monotonic()}

    m.launch_juror = launch
    m.event = lambda msg: (_ for _ in ()).throw(ValueError("I/O operation on closed file"))
    results = []
    m.run_headless(["m/a", "m/b", "m/c"], "a.md", "i.md", "plan", out, "R", d, 1, results)
    assert sorted(killed) == ["m/a", "m/b", "m/c"], killed
    assert results and results[0]["attempted"] == 3, results


def test_a_duplicated_model_never_leaves_a_child_running():
    """The finally skips jurors wait_out already settled. Keyed by model rather than by
    identity, a second juror carrying the same model id was skipped while still alive: never
    killed, never recorded (/code-review)."""
    m = load()
    m.opencode_exe = lambda: "opencode"
    m.POLL_S = 0
    m.progress = lambda *a, **k: None
    d = tempfile.mkdtemp()
    out = os.path.join(d, "out")
    os.makedirs(out, exist_ok=True)
    killed, made = [], []

    class Proc:
        def __init__(self, exits): self.exits = exits
        def poll(self): return 0 if self.exits else None
        def kill(self): killed.append(id(self))
        def wait(self): return -9

    def launch(exe, model, spec, rep, root, streams, run_id, name):
        path = os.path.join(d, "e.jsonl")
        open(path, "w").write("")
        proc = Proc(not made)                    # the first settles, the second keeps running
        made.append(proc)
        return {"model": model, "proc": proc, "report": rep, "events": path,
                "stderr": path, "handles": (), "started": m.time.monotonic()}

    m.launch_juror = launch
    real, seen = m.headless_row, {"n": 0}

    def exiting(j, rc, **kw):
        seen["n"] += 1
        if seen["n"] == 2:
            raise SystemExit("terminated")
        return real(j, rc, **kw)

    m.headless_row = exiting
    results = []
    try:
        m.run_headless(["m/a", "m/a"], "a.md", "i.md", "plan", out, "R", d, 1, results)
    except SystemExit:
        pass
    m.headless_row = real
    # keyed by model, the second juror is skipped entirely: no kill, no row, and a panel of
    # two reported as one. kill() may land more than once on an already-dead child, which is
    # a no-op, so the count is not what is asserted here
    assert id(made[1]) in killed, "the live duplicate must still be killed"
    assert results and results[0]["attempted"] == 2, results
    assert [j["model"] for j in results[0]["jurors"]] == ["m/a", "m/a"], results[0]["jurors"]


def test_a_verdict_written_just_before_the_clock_is_still_salvaged():
    """from_this_run compares a filesystem mtime against this process's clock. Whole-second
    granularity or a lagging mount can date a fresh verdict before the run began, and judging
    it stale loses it silently — the failure salvage exists to prevent (/code-review)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        report = os.path.join(d, "r.json")
        open(report, "w").write("{}")
        os.utime(report, (10_000, 10_000))
        assert m.from_this_run(report, 10_000 + m.STALE_SLACK_S - 1), "within slack: keep"
        assert not m.from_this_run(report, 10_000 + m.STALE_SLACK_S + 60), "a previous run: drop"


def test_a_closed_monitor_pipe_never_settles_a_juror_twice():
    """print() sat outside progress()'s guard, so a BrokenPipeError escaped mid-pass through
    wait_out — which rebuilds `pending` only after its whole loop, leaving settled jurors in it
    for the finally to settle again.  Cosmetic for `attempted`; money once spend is summed."""
    m = load()
    m.PROGRESS["path"] = None

    def broken(msg):
        raise BrokenPipeError(32, "Broken pipe")

    m.event = broken
    m.progress("returned", "alpha returned in 42s")       # must not raise

    # and the record must outlive the channel: a closed pipe is the case the progress file
    # exists for, so one shared guard would drop the line exactly when the stream was lost
    with tempfile.TemporaryDirectory() as d:
        m.PROGRESS["path"] = os.path.join(d, "p.jsonl")
        m.progress("returned", "alpha returned in 42s, $0.0812")
        written = open(m.PROGRESS["path"]).read().splitlines()
        assert len(written) == 1, written
        assert json.loads(written[0])["message"].endswith("$0.0812"), written


def test_tokens_say_unknown_on_the_same_terms_as_cost():
    """tally reported cost as None when unmeasured but tokens as 0, applying its own rule — a
    free model and a stream that lost its figures must not read alike — to one and not the
    other (jury: deepseek-v4-flash)."""
    m = load()
    with tempfile.TemporaryDirectory() as d:
        none = m.tally(_stream(d, _step(0.01), _step(0.02)))
        assert none["tokens"] is None and none["cost"] == 0.03, none
        some = m.tally(_stream(d, _step(0.01, input=5), _step(0.02), name="some.jsonl"))
        assert some["tokens"]["input"] == 5, some
        assert some["steps_without_tokens"] == 1, some


def test_the_spend_line_names_jurors_not_calls():
    """"no cost read for 2 of them" attached to `calls`, and meant jurors."""
    m = load()
    said = []
    m.progress = lambda kind, msg, **kw: said.append(msg)
    m.announce_spend("LAB-83", {"cost": 0.017, "steps": 4, "calls": 9,
                                "jurors_without_cost": ["m/b", "m/c"]})
    assert "2 jurors" in said[0], said
    m.announce_spend("LAB-83", {"cost": 0.017, "steps": 1, "calls": 1,
                                "jurors_without_cost": ["m/b"]})
    assert "1 juror;" in said[1] or said[1].endswith("1 juror"), said


#
# The juror's own permission block, asserted rather than read.  An allowlist of `git status*`
# patterns was a write primitive: opencode matches a pattern against the whole command text,
# redirect included, and never path-checks the redirect target, so `git log > /tmp/x` ran and
# created it, `edit` and `external_directory` both denying.  These encode the invariant instead of
# that one vector.  They prove the file conforms to semantics measured against opencode
# 1.18.30 — not that opencode still behaves that way, which only a live probe can show.

JUROR_MD = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "..", "opencode", ".config", "opencode", "agents", "juror.md")

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
                    "python3 tests/test_jury.py",
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


def test_glob_is_denied_because_it_answers_wrongly_instead_of_refusing():
    """Every other denial here closes a reach.  This one withholds a tool: opencode never passes
    `--hidden` to ripgrep, so every pattern misses the 41 of 47 files a stow tree keeps under a
    dotted path, and success with zero rows is the one failure `impediments` cannot record (LAB-72)."""
    keys, _ = juror_permissions()
    assert dict(keys)["glob"] == "deny", "glob is granted; it under-reports silently"


def test_a_settled_panel_shows_nothing():
    """The outcome says the display shows nothing when no panel is running, and a settled panel
    is not a running one — from there the agent's own report carries it (LAB-86)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched"},
        working("opencode-go/qwen3.7-plus", "qwen3.7-plus — running 60s, last read a.py"),
        {"kind": "settled", "message": "Panel completed — findings in agents/out/x.json"})
    assert m.render(path) == "", m.render(path)


def test_no_panel_at_all_shows_nothing():
    """Every session on the machine runs this several times a minute, and almost none of them
    have a panel. A missing or empty file is the ordinary case, not an error (LAB-86)."""
    m = load_statusline()
    assert m.render("/nonexistent/x.progress.jsonl") == ""
    assert m.render(progress_file()) == ""


def test_every_working_juror_gets_its_own_line():
    """One line per juror, because the status line renders newlines as a column while a single
    line is truncated at the terminal edge and never wrapped — so a four-juror panel on one
    line loses whatever does not fit, which is the targets (LAB-86)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched"},
        {"kind": "returned", "message": "luna returned in 55s — 1 of 4",
         "model": "opencode-go/gpt-5.6-luna"},
        working("opencode-go/deepseek-v4-flash", "deepseek-v4-flash — running 60s, last read a.py (×3)"),
        working("opencode-go/qwen3.7-plus", "qwen3.7-plus — running 60s, last read b.swift"),
        working("opencode-go/glm-5.3-flash", "glm-5.3-flash — running 60s, last grep neon"))
    lines = m.render(path).split("\n")
    assert lines[0] == "⚖ LAB-1 — 1 of 4 reported", lines[0]
    assert len(lines) == 4, lines
    # the runner's own line, verbatim: reformatting it here would be a second copy of
    # working_line()'s format, free to drift from the one jury.py actually writes
    assert lines[1] == "deepseek-v4-flash — running 60s, last read a.py (×3)", lines[1]
    assert not any("gpt-5.6-luna" in l for l in lines[1:]), "a juror that reported is not working"


def test_a_torn_final_line_does_not_cost_the_display():
    """The runner appends while this reads, both several times a minute, so catching a
    half-written line is routine. Losing the whole display to it would make the display
    flicker exactly when the panel is busiest (LAB-86)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched"},
        working("opencode-go/qwen3.7-plus", "qwen3.7-plus — running 60s, last read a.py"))
    with open(path, "a") as fh:
        fh.write('{"t": "2026-09-21T12:01:0')
    assert m.render(path).split("\n")[1] == "qwen3.7-plus — running 60s, last read a.py"


def test_a_runner_that_stopped_writing_says_so():
    """A juror line is written every 60s, so a file that has gone quiet for minutes is a runner
    that died rather than a panel between heartbeats. Vanishing would read as a panel that
    finished, which is the one thing it did not do (LAB-86)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched"},
        working("opencode-go/qwen3.7-plus", "qwen3.7-plus — running 60s, last read a.py"))
    head = m.render(path, now=os.path.getmtime(path) + 8 * 60).split("\n")[0]
    assert head == "⚖ LAB-1 — 0 of 4 reported · last change 8m ago", head


def test_a_kind_this_does_not_know_is_ignored():
    """LAB-83 adds `spend` rows to the same file. A renderer that had to be told about every
    kind would break on the next one; unknown kinds are data it does not act on (LAB-86)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched"},
        {"kind": "spend", "message": "LAB-1.artifact: $0.1719 over 39 steps", "cost": 0.1719},
        working("opencode-go/qwen3.7-plus", "qwen3.7-plus — running 60s, last read a.py"))
    lines = m.render(path).split("\n")
    assert len(lines) == 2, lines
    assert "$0.17" not in m.render(path)


def test_a_juror_that_never_reported_is_not_counted_as_reporting():
    """`absent` and `timeout` settle a juror without a verdict. Counting them as reported made
    a panel where all four died read `4 of 4 reported` — four verdicts claimed where none
    landed, and the last thing the caller saw before the line vanished (LAB-86 review)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched", "pid": os.getpid()},
        {"kind": "returned", "message": "luna returned in 55s", "model": "a"},
        {"kind": "absent", "message": "NO REPORT from b", "model": "b"},
        {"kind": "timeout", "message": "NO REPORT from c — killed at the 1801s timeout",
         "model": "c"},
        working("d", "d — running 60s, last read x.py"))
    head = m.render(path).split("\n")[0]
    assert head == "⚖ LAB-1 — 1 of 4 reported, 2 absent", head


def test_a_second_artifacts_jurors_still_render():
    """One progress file covers every artifact of a run, and the same four models review each.
    Read as one panel, artifact 1's settled jurors counted against artifact 2 — every live
    juror filtered out and the header frozen at `4 of 4`, which is what a finished panel looks
    like, for up to the backstop (LAB-86 review)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "2 jurors dispatched", "artifact": "one",
         "pid": os.getpid()},
        {"kind": "returned", "message": "a returned in 30s", "model": "a", "artifact": "one"},
        {"kind": "returned", "message": "b returned in 40s", "model": "b", "artifact": "one"},
        {"kind": "dispatched", "message": "2 jurors dispatched", "artifact": "two",
         "pid": os.getpid()},
        working("a", "a — running 60s, last read x.py", artifact="two"),
        working("b", "b — running 60s, last grep y", artifact="two"))
    lines = m.render(path).split("\n")
    assert lines[0] == "⚖ LAB-1 — 0 of 2 reported", lines[0]
    assert len(lines) == 3, lines


def test_a_run_whose_process_is_gone_shows_nothing():
    """A SIGKILLed runner writes no `settled` — that is in a `finally`, which SIGKILL skips —
    and nothing prunes `agents/out`, so its file stays newest in the directory. Asking the OS
    about the pid settles it; mtime only guessed, and guessed for half an hour (LAB-86)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched", "pid": dead_pid()},
        working("a", "a — running 60s, last read x.py"))
    assert m.render(path) == "", m.render(path)


def test_the_juror_line_survives_the_status_lines_own_trim():
    """The status line trims every line before rendering it, so an indent written here is
    dropped before anyone sees it. Asserting the emitted string hid that; this asserts what
    reaches the screen (LAB-86 review)."""
    m = load_statusline()
    path = progress_file(
        {"kind": "dispatched", "message": "4 jurors dispatched", "pid": os.getpid()},
        working("a", "a — running 60s, last read x.py"))
    shown = rendered(m.render(path))
    assert shown == ["⚖ LAB-1 — 0 of 4 reported", "a — running 60s, last read x.py"], shown


def test_the_runner_writes_what_the_display_reads():
    """The writer and the reader meeting on a real file, not on hand-built rows.

    Every other display test calls render() with rows the test wrote, so a regression in what
    jury.py records — or a wrong assumption about it — would render nothing while the whole
    suite stayed green. That is the same shape of gap that let the artifact and pid defects
    ship in the first place (LAB-86 review)."""
    m, sl = load(), load_statusline()
    d = repo()
    cwd = os.getcwd()
    try:
        os.chdir(d)
        m.check_models = lambda models: None
        m.check_display = lambda *a, **k: None
        m.opencode_exe = lambda: "opencode"

        def launch(exe, model, spec, rep, root, o, run_id, name):
            open(rep, "w").write(json.dumps({"verdict": "pass", "findings": [],
                                             "impediments": []}))
            open(f"{o}/e.json", "w").write("")
            return {"model": model, "proc": FakeProc([0]), "report": rep,
                    "events": f"{o}/e.json", "stderr": f"{o}/e.json", "handles": (),
                    "started": 0}

        m.launch_juror = launch
        m.POLL_S = 0
        sys.argv = ["jury", "--artifact", "a.md", "--intent", "i.md", "--standard", "plan",
                    "--run-id", "W-20260921-120000-1", "--out", "out", "--models", "m/alpha"]
        m.main()
        path = os.path.join(d, "out", "W-20260921-120000-1.progress.jsonl")
        rows = [json.loads(l) for l in open(path) if l.strip()]
    finally:
        os.chdir(cwd)

    dispatched = [r for r in rows if r["kind"] == "dispatched"]
    assert dispatched and dispatched[0].get("pid") == os.getpid(), dispatched
    assert dispatched[0].get("artifact") == "a", dispatched
    # the display opens on this one, a minute before the wait would write any
    assert [r for r in rows if r["kind"] == "working" and r.get("artifact") == "a"], rows
    # every row the panel phase writes is attributable, the spend row included
    unnamed = [r["kind"] for r in rows if r["kind"] not in ("settled",) and not r.get("artifact")]
    assert not unnamed, unnamed

    # and the reader makes sense of it. Kept: what the file held before the juror returned —
    # a settled panel renders nothing, and a juror that reported is not one still working
    live = [r for r in rows if r["kind"] in ("dispatched", "working")]
    with open(path, "w") as fh:
        for r in live:
            fh.write(json.dumps(r) + "\n")
    shown = rendered(sl.render(path))
    assert shown[0] == "⚖ W — 0 of 1 reported", shown
    assert len(shown) == 2 and "alpha" in shown[1], shown


def test_the_display_finds_the_run_from_the_payload():
    """newest_progress reads Claude Code's own status-line payload, so its shape is an
    assumption this repo cannot check anywhere else. Wrong keys render nothing, silently, on
    every machine at once (LAB-86 review)."""
    m = load_statusline()
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "agents", "out"))
    old = os.path.join(d, "agents/out", "OLD-20260921-100000-1.progress.jsonl")
    new = os.path.join(d, "agents/out", "NEW-20260921-110000-2.progress.jsonl")
    for p in (old, new):
        open(p, "w").write(json.dumps({"kind": "dispatched", "message": "4 jurors"}) + "\n")
    os.utime(old, (1, 1))
    assert m.newest_progress({"workspace": {"current_dir": d}}) == new
    assert m.newest_progress({"workspace": {"project_dir": d}}) == new
    assert m.newest_progress({"workspace": {"current_dir": "/nonexistent"}}) is None
    assert m.newest_progress({}) is None          # a payload without a workspace is not a crash


def test_the_runner_says_when_the_display_is_not_installed():
    """Named and present fail separately, and only the second was checked at first — so a run
    that rendered nowhere passed the guard quietly, which is the failure it exists to catch
    (LAB-86 review)."""
    m = load()
    said = []
    m.progress = lambda kind, msg, **kw: said.append((kind, msg))
    d = tempfile.mkdtemp()
    script = os.path.join(d, "statusline.py")
    named = os.path.join(d, "named.json")
    open(named, "w").write(json.dumps({"statusLine": {"command": f"python3 {script}"}}))
    orca = os.path.join(d, "orca.json")
    open(orca, "w").write(json.dumps({"statusLine": {"command": "orca-statusline.sh"}}))

    open(script, "w").write("#")
    m.check_display(settings=named, script=script)
    assert said == [], said                       # named, and there: nothing to say

    os.remove(script)
    m.check_display(settings=named, script=script)
    assert said and said[-1][0] == "display_missing", said
    assert "does not exist" in said[-1][1], said

    said.clear()
    m.check_display(settings=orca, script=script)
    assert said and "does not name statusline.py" in said[-1][1], said

    said.clear()
    m.check_display(settings=os.path.join(d, "gone.json"), script=script)
    assert said == [], said                       # unreadable settings is not evidence either way


def test_the_display_never_fails_the_slot():
    """It runs in every session on the machine, several times a minute, and almost never has a
    panel to show. A payload it cannot parse must still exit 0 having printed nothing — a
    traceback here lands somewhere the caller cannot dismiss (LAB-86).

    What this cannot cover is the forward to Orca: that lives in the settings command, in
    `dotfiles`, precisely so that this file being absent cannot take Orca's telemetry with
    it — so there is nothing here to test it against."""
    done = subprocess.run([sys.executable, STATUSLINE], input="not json at all",
                          text=True, capture_output=True)
    assert done.returncode == 0, done
    assert done.stdout == "", done.stdout
    assert done.stderr == "", done.stderr


def test_the_session_names_the_copy_it_loaded():
    """An installed copy's path ends in its SHA, so naming the root answers "which loop is this
    session running" with no tool call — and a --plugin-dir session names the worktree instead
    of passing its basename off as a version (LAB-97)."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "loop")
    done = subprocess.run(["bash", os.path.join(root, "hooks", "session-rules.sh")],
                          env={**os.environ, "CLAUDE_PLUGIN_ROOT": root},
                          text=True, capture_output=True)
    assert done.returncode == 0, done
    context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    first, _, rest = context.partition("\n\n")
    assert first == f"The loop plugin in this session is loaded from `{root}`.", first
    assert rest == open(os.path.join(root, "rules", "agent-workflow.md"), encoding="utf-8").read()


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
