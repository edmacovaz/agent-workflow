#!/usr/bin/env python3
"""Fan an artifact out to a panel of opencode jurors and collect their verdicts.

Jurors are separate processes with no tools, so nothing here trusts their output:
it is parsed as data and a juror that returns unparseable text is recorded as a
parse failure rather than dropped, because how often that happens is a result.
"""
import argparse, concurrent.futures, json, subprocess, sys, time

DEFAULT_MODELS = ["opencode-go/gpt-5.6-luna", "opencode-go/glm-5.3", "opencode-go/qwen3.8-max"]

PROMPT = """Review the ARTIFACT below against the INTENT.

=== INTENT ===
{intent}

=== ARTIFACT ===
{artifact}
"""


def run_juror(model, prompt, cwd, timeout):
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["opencode", "run", "--agent", "juror", "-m", model, "--format", "json", prompt],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # Keep whatever arrived: a timeout usually means slow, not dead, and the
        # partial stream is the only evidence of which.
        return {"model": model, "error": "timeout", "seconds": round(time.monotonic() - started, 1),
                "partial_stdout": (exc.stdout or b"").decode(errors="replace")[-3000:] if isinstance(exc.stdout, bytes) else (exc.stdout or "")[-3000:],
                "stderr": (exc.stderr or b"").decode(errors="replace")[-3000:] if isinstance(exc.stderr, bytes) else (exc.stderr or "")[-3000:]}

    text, cost, tokens, tools = "", 0.0, {}, []
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue                      # opencode interleaves non-JSON banner lines
        part = ev.get("part") or {}
        if ev.get("type") == "text":
            text += part.get("text", "")
        elif ev.get("type") == "tool":
            tools.append(part.get("tool"))
        elif ev.get("type") == "step_finish":
            cost += part.get("cost") or 0.0
            tokens = part.get("tokens") or tokens

    out = {"model": model, "seconds": round(time.monotonic() - started, 1),
           "cost": round(cost, 6), "tokens": tokens.get("total"), "exit": proc.returncode,
           "tools": tools, "stderr": (proc.stderr or "")[-3000:]}

    body = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        out.update(parse_ok=False, raw=text[:2000])
        return out
    out.update(parse_ok=True, verdict=parsed.get("verdict"), findings=parsed.get("findings") or [])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True, help="file holding the plan or diff under review")
    ap.add_argument("--intent", required=True, help="file holding the issue intent / conventions")
    ap.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--timeout", type=int, default=400)
    args = ap.parse_args()

    prompt = PROMPT.format(intent=open(args.intent).read(), artifact=open(args.artifact).read())

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.models)) as pool:
        results = list(pool.map(lambda m: run_juror(m, prompt, args.cwd, args.timeout), args.models))

    json.dump({"artifact": args.artifact, "jurors": results,
               "total_cost": round(sum(r.get("cost") or 0 for r in results), 6)},
              sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
