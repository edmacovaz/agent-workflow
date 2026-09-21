# Jury dispatch mechanics

Open this while a panel is running — for the progress-line format, or to work out which
files under `agents/out/` are juror reports.

## What a Monitor event carries

The runner's line itself, verbatim. This file said the opposite until 12 Sep 2026, and the
progress file below was built to work around a constraint that measurement showed is not there
(LAB-65) — so run the panel *as* the Monitor command and let it speak for itself.

## Reading the progress file

`agents/out/<run>.progress.jsonl` holds the same lines, appended and flushed as they are printed.
It is the record, not the channel: read it when the stream was missed, when a run is picked up
from another session, or when a crash has to be reconstructed afterwards. The lines look like:

```
glm-5.3-flash returned in 214s, $0.0535 — 1 of 4
qwen3.7-plus — running 120s, last read claude/.claude/scripts/jury.py (×3)
LAB-83.artifact: $0.1719 over 39 steps and 57 calls
```

Name the model, say what changed, and give the count against the panel size. A settled juror
carries what it spent, including one that died — the figure comes from its own event stream, so
it survives a juror that wrote no verdict, and the panel's own total lands once after the last
juror settles. A juror still running is reported with what it last called — repo-relative, so
the part that identifies it survives — and carries no cost, because the line is about what it
is doing and a running total there is noise. A panel that read no figures at all says
nothing rather than `$0.0000`, which would be a claim nobody measured. It carries
`×N` where it has made that exact call N times
across the review, which is a count and not a verdict — ordinary re-checking and a loop look the
same from out here. Pass it on and let the caller judge. A juror that has called
nothing yet is reported as such, never as stuck: one long model call looks identical from here.

## Which files are which

Everything a run writes is prefixed by the run id, so `agents/out/<run>.*` matches more than
the reports:

| Path | Holds |
| --- | --- |
| `<run>.<artifact>.<model>.json` | a juror's report — these, and only these, are verdicts |
| `<run>.progress.jsonl` | the runner's appended progress lines |
| `<run>.jury-result.json` | the settled run |

A juror's event stream and stderr are **not** here. They live under `~/.cache/jury/<run>/`, and
the settle file's `streams` field names the directory. That is not tidiness: a juror may read
anything inside the worktree, so streams kept beside the reports let one juror read another's
reasoning as it forms — which one did. Outside the worktree, the juror's own
`external_directory: deny` is what stops it.

Glob on the full `<run>.<artifact>.<model>.json` form, never on `<run>.*`. The artifact segment
is the pack filename with `.md` stripped, so it carries a dot of its own: a real report path is
`<run>.LAB-41.artifact.glm-4.6.json`.
