// Tests for the juror's no-retry plugin: `node tests/test_no_retry.mjs`,
// by path from the worktree root. Driven through the hooks because no panel can reach the
// blocking path — asked to repeat a refused call twelve times, a juror made four and stopped.

import { readFileSync } from "node:fs"

const PLUGIN = new URL("../opencode/.config/opencode/plugins/no-retry.js", import.meta.url)
// Imported as a data URL, which is always a module: importing the `.js` directly would need a
// `package.json` declaring `"type": "module"`, and this repo has neither a package.json nor a
// lockfile to add one to (LAB-71 review).
const { NoRetry } = await import(
  "data:text/javascript," + encodeURIComponent(readFileSync(PLUGIN, "utf8")))

let seq = 0
const session = () => `ses_${++seq}`
let failures = 0

function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) failures++
  console.log(`${ok ? "  ok  " : " FAIL "} ${name}`
    + (ok ? "" : `  got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`))
}

function conversation(sessionID, agent = "juror") {
  return { messages: [{ info: { role: "user", id: "m1", sessionID, agent },
                        parts: [{ type: "text", id: "p1", text: "review this" }] }] }
}

// One refused call per turn, which is the shape the 786-call run had. The turn boundary
// matters: a call is only counted dead when the next turn is assembled, because within a
// step opencode may still be running it (LAB-71 review).
async function repeat(hooks, sessionID, n, command = "git diff --stat", agent = "juror") {
  let blockedAt = null
  for (let i = 1; i <= n; i++) {
    try {
      await hooks["tool.execute.before"]({ tool: "bash", sessionID, callID: `c${i}` },
                                         { args: { command } })
    } catch {
      blockedAt = blockedAt ?? i
    }
    await hooks["experimental.chat.messages.transform"]({}, conversation(sessionID, agent))
  }
  return blockedAt
}

async function juror() {
  const id = session()
  const hooks = await NoRetry()
  await hooks["chat.message"]({ sessionID: id, agent: "juror" })
  return { id, hooks }
}

// The measurement this whole plugin exists for: glm-5.3-flash made 786 identical refused
// calls in 21 minutes and produced no verdict (LAB-65 panel, 12 Sep 2026).
{
  const { id, hooks } = await juror()
  check("blocks the 11th identical call, so ten reach the room",
        await repeat(hooks, id, 15), 11)
}

// The plugin is stowed user-global, so it is loaded for every opencode agent on the machine,
// not only jurors (LAB-71).
{
  const hooks = await NoRetry()
  const id = session()
  await hooks["chat.message"]({ sessionID: id, agent: "build" })
  check("never fires for another agent",
        await repeat(hooks, id, 30, "git diff --stat", "build"), null)
}

// A call that completes is not a wall however often it is made: re-reading a file looks
// identical from out here, which is why jury.py reports ×N as a count and not a diagnosis.
{
  const { id, hooks } = await juror()
  let blocked = null
  for (let i = 1; i <= 30; i++) {
    const call = { tool: "bash", sessionID: id, callID: `d${i}` }
    try { await hooks["tool.execute.before"](call, { args: { command: "inspect.sh status" } }) }
    catch { blocked = blocked ?? i }
    await hooks["tool.execute.after"]({ ...call, args: {} })
  }
  check("never blocks a call that completes", blocked, null)
}

// Near-identical variations are deliberately not capped here — what they cost has never been
// measured, and capping them blocks calls that would have succeeded (LAB-71, moved to LAB-37).
{
  const { id, hooks } = await juror()
  let blocked = null
  for (let i = 1; i <= 30; i++) {
    try {
      await hooks["tool.execute.before"]({ tool: "bash", sessionID: id, callID: `e${i}` },
                                         { args: { command: `git log -${i}` } })
    } catch { blocked = blocked ?? i }
  }
  check("never blocks near-identical variations", blocked, null)
}

// Two different calls must never collapse into one key: truncating the target collapsed six
// files into one, and a missing key made two different calls look like one repeated (LAB-65
// review). Here that would block an innocent call.
{
  const { id, hooks } = await juror()
  let blocked = null
  for (let i = 1; i <= 30; i++) {
    try {
      await hooks["tool.execute.before"]({ tool: "read", sessionID: id, callID: `f${i}` },
                                         { args: { filePath: `/repo/file-${i}.md` } })
    } catch { blocked = blocked ?? i }
  }
  check("keys on the whole target, so different files are different walls", blocked, null)
}

// The informing layer. Measured to do the real work: with the room's own count in front of it,
// a juror told to make twelve identical calls made four and stopped (LAB-71).
{
  const { id, hooks } = await juror()
  let out = conversation(id)
  await hooks["experimental.chat.messages.transform"]({}, out)
  check("says nothing when no wall was hit", out.messages.length, 1)

  await repeat(hooks, id, 3)
  out = conversation(id)
  await hooks["experimental.chat.messages.transform"]({}, out)
  const note = out.messages[1]?.parts?.[0]?.text ?? ""
  check("appends one message once a wall exists", out.messages.length, 2)
  // The whole line, not a substring: the key joins tool and target with a separator, and a
  // mismatched one still contains the target while naming it wrongly (LAB-71 review).
  check("names the tool and target, and nothing else",
        note.includes("- bash git diff --stat — 3 attempt(s)"), true)
}

// A juror refused once and moving on is the issue's first scenario, and the count it needs is
// only knowable a turn later: nothing tells a hook a call was refused, so an unclosed call is
// settled when the next turn is assembled (LAB-71 review).
{
  const { id, hooks } = await juror()
  await repeat(hooks, id, 1)
  const out = conversation(id)
  await hooks["experimental.chat.messages.transform"]({}, out)
  const note = out.messages[1]?.parts?.[0]?.text ?? ""
  check("tells a juror refused exactly once", note.includes("1 attempt(s)"), true)
}

// The separator is a NUL, which no command can contain — but written raw it makes the source a
// binary file to git and grep, and it reached review as `Bin 0 -> 6563 bytes` (LAB-71 review).
{
  check("the plugin source is text, not binary", readFileSync(PLUGIN).includes(0), false)
}

// A hook that throws takes the juror down with it, so every path but the deliberate block
// swallows its own errors — the rule jury.py's observed() carries for the same reason.
{
  const { id, hooks } = await juror()
  let threw = false
  try { await hooks["tool.execute.before"]({ tool: "bash", sessionID: id, callID: "z" }, null) }
  catch { threw = true }
  check("survives a call with no args object", threw, false)

  threw = false
  try { await hooks["experimental.chat.messages.transform"]({}, { messages: "not an array" }) }
  catch { threw = true }
  check("survives a malformed messages array", threw, false)

  threw = false
  try { await hooks["tool.execute.after"]({ sessionID: undefined, callID: undefined }) }
  catch { threw = true }
  check("survives a completion it has no record of", threw, false)
}

console.log(failures ? `\n${failures} failed` : "\nall passed")
process.exit(failures ? 1 : 0)
