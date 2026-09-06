# Jury dispatch mechanics

Open this while a panel is running — for the progress-line format, or to work out which
files under `agents/out/` are juror reports.

## Why a Monitor wake carries no content

Monitor renders only its own description, never the line that woke it. The runner's wording
never reaches the caller, so a wake means only *something changed, go and look*.

## Reading the progress file

`agents/out/<run>.progress.jsonl` is how the runner's inspected state reaches the caller. On
each wake read the lines added since the last one and report them:

```
glm-5.3-flash returned — 1 of 4
qwen3.7-plus — still reviewing, heartbeat 40s ago
```

Name the model, say what changed, and give the count against the panel size. A juror that has
gone quiet is reported with how long ago it last beat.

## Which files are which

Everything a run writes is prefixed by the run id, so `agents/out/<run>.*` matches more than
the reports:

| Path | Holds |
| --- | --- |
| `<run>.<artifact>.<model>.json` | a juror's report — these, and only these, are verdicts |
| `<run>.progress.jsonl` | the runner's appended progress lines |
| `<run>.jury-result.json` | the settled run |

Glob on the full `<run>.<artifact>.<model>.json` form, never on `<run>.*`. The artifact segment
is the pack filename with `.md` stripped, so it carries a dot of its own: a real report path is
`<run>.LAB-41.artifact.glm-4.6.json`.
