// Stops a juror spending a run on a call the room has already refused: it counts them, tells
// the juror what it has hit, and blocks the eleventh identical one. Why not `doom_loop: deny`,
// and what each layer is worth, is on LAB-71.

// Keyed by session rather than held per instance: the plugin loads into several independent
// module scopes in one run, and a count kept outside this map fragments across them (LAB-71).
const sessions = new Map()

// Identical attempts before the call is blocked outright. ~1% of the measured 786 and far
// above any honest retry — deliberately generous, because a refusal and a transient failure
// are indistinguishable from here and only the second is worth retrying at all (LAB-71).
const BLOCK_AT = 10

function stateFor(sessionID) {
  let state = sessions.get(sessionID)
  if (!state) {
    state = { walls: new Map(), open: new Map(), agent: null, told: 0 }
    sessions.set(sessionID, state)
  }
  return state
}

// Every key a tool uses to name its target. Matching jury.py's `observed()`: a missing key
// makes two different calls look like one repeated, which would block an innocent call.
function targetOf(args) {
  const a = args && typeof args === "object" ? args : {}
  return String(a.command ?? a.filePath ?? a.pattern ?? a.path ?? a.name ?? a.patchText ?? "")
}

function wallFor(state, key) {
  let wall = state.walls.get(key)
  if (!wall) {
    wall = { incomplete: 0 }
    state.walls.set(key, wall)
  }
  return wall
}

function blockedMessage(target, incomplete) {
  return `This call has already been refused or has failed ${incomplete} times, and it will `
    + `not succeed on another attempt. It is now blocked for the rest of this review. Record `
    + `it in impediments with attempts: ${incomplete} and finish your review with what you `
    + `can reach. Target: ${oneLine(target)}`
}

// The only place a call is called dead: still open when the next turn is assembled means it
// never reached `after`, and a step's calls have all finished by then. Compaction calls this
// hook off a turn boundary too, costing one early settle — never a block, which needs ten.
function settleOpen(state) {
  for (const [callID, key] of state.open) {
    state.open.delete(callID)
    wallFor(state, key).incomplete += 1
  }
}

function oneLine(target, limit = 120) {
  const flat = String(target).split(/\s+/).filter(Boolean).join(" ")
  return flat.length > limit ? flat.slice(0, limit - 1) + "…" : flat
}

function statusNote(state) {
  const hit = [...state.walls.entries()].filter(([, w]) => w.incomplete > 0)
  if (!hit.length) return null
  const lines = hit.map(([key, w]) => {
    const cut = key.indexOf("\u0000")
    // `incomplete`, not `attempts`: the count the juror copies into impediments is the count
    // of times it hit the wall, and jury.py renders it as ×N (LAB-57, LAB-71 review).
    return `- ${key.slice(0, cut)} ${oneLine(key.slice(cut + 1))} — ${w.incomplete} attempt(s)`
  })
  return "Room status, from the room itself. These calls did not go through:\n"
    + lines.join("\n")
    + `\n\nA refusal is final: the answer will not change on another attempt, and a different `
    + `spelling of a refused call is another attempt. Record each one in impediments with its `
    + `attempts count and review with what you can reach. A call that does not go through `
    + `${BLOCK_AT} times is blocked outright.`
}

export const NoRetry = async () => {
  return {
    "chat.message": async (input) => {
      try {
        if (input?.sessionID) stateFor(input.sessionID).agent = input.agent ?? null
      } catch {}
    },

    "tool.execute.before": async (input, output) => {
      // Never throws on its own account: an escape from here breaks the juror, the same rule
      // jury.py's `observed()` carries for the same reason (LAB-71).
      let blocked = null
      try {
        const state = stateFor(input?.sessionID)
        if (state.agent !== "juror") return
        const key = (input?.tool ?? "?") + "\u0000" + targetOf(output?.args)
        // Nothing is settled here. opencode starts a step's tool calls concurrently, so an
        // open call under this key may simply be in flight — settling it would count a
        // working command as a wall and eventually block it (LAB-71 review).
        const wall = wallFor(state, key)
        if (wall.incomplete >= BLOCK_AT) {
          blocked = blockedMessage(key.slice(key.indexOf("\u0000") + 1), wall.incomplete)
        } else {
          state.open.set(input?.callID, key)
        }
      } catch {}
      // Outside the try, or the throw that blocks the call would be swallowed by it.
      if (blocked) throw new Error(blocked)
    },

    "tool.execute.after": async (input) => {
      try {
        stateFor(input?.sessionID).open.delete(input?.callID)
      } catch {}
    },

    "experimental.chat.messages.transform": async (input, output) => {
      try {
        const msgs = output?.messages
        if (!Array.isArray(msgs) || !msgs.length) return
        // This hook is given no session id, so it comes off the messages themselves — which
        // also carry the agent, making this independent of chat.message having fired (LAB-71).
        const template = [...msgs].reverse().find((m) => m?.info?.role === "user")
        const sessionID = template?.info?.sessionID
        if (!sessionID || template?.info?.agent !== "juror") return
        const state = stateFor(sessionID)
        state.agent = "juror"
        settleOpen(state)
        const note = statusNote(state)
        if (!note) return
        const textPart = (template.parts ?? []).find((p) => p?.type === "text")
        if (!textPart) return
        // Cloned from a real user message rather than built from scratch: the part shape is
        // opencode's and changes with it (LAB-71).
        state.told += 1
        const id = `${template.info.id}_noretry_${state.told}`
        msgs.push({
          info: { ...template.info, id },
          parts: [{ ...textPart, id: `${textPart.id ?? "part"}_noretry_${state.told}`,
                    messageID: id, text: note }],
        })
      } catch {}
    },
  }
}
