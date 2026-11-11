/**
 * Command registry for the God View command line.
 *
 * `run(arg, ctx)` returns (or resolves to) { ok, key, params } where `key`
 * is an i18n message, or { ok, text } with the backend's own summary.
 * Commands marked `god` change or question the simulation; the backend
 * writes each one to the audit log. Commands with `pending` still need
 * backend support; they are listed so the operator can see what is coming,
 * and answer with what is missing instead of pretending to work.
 */
import {
  state, agents, setFocus, resolveAgent, selectAgent, scrubTo, goLive, liveRound,
  startPlayback, stopPlayback, stepRound
} from '../../store/godTerminal'
import {
  godPause, godResume, godStep, godInject, godWhisper, godInterview, godPoll, godReport,
  godFork, getBranches
} from '../../api/god'

const ok = (key, params) => ({ ok: true, key, params })
const fail = (key, params) => ({ ok: false, key, params })

/** Split "Maya Chen what do you think" (or "4 what...") into agent and the rest. */
export function splitAgent(arg) {
  const text = (arg || '').trim()
  const lower = text.toLowerCase()
  const first = text.split(/\s+/)[0] || ''
  if (/^\d+$/.test(first)) {
    return { agent: resolveAgent(first), rest: text.slice(first.length).trim() }
  }
  // Longest full name that the argument starts with.
  const named = agents.value
    .filter(a => lower === a.name.toLowerCase() || lower.startsWith(a.name.toLowerCase() + ' '))
    .sort((a, b) => b.name.length - a.name.length)[0]
  if (named) return { agent: named, rest: text.slice(named.name.length).trim() }
  return { agent: resolveAgent(first), rest: text.slice(first.length).trim() }
}

/** Pull leading key=value options off "stance=opposing options=a|b question...". */
function splitOptions(arg, keys) {
  const options = {}
  let rest = (arg || '').trim()
  for (;;) {
    const match = rest.match(/^(\w+)=(\S+)\s*/)
    if (!match || !keys.includes(match[1])) break
    options[match[1]] = match[2]
    rest = rest.slice(match[0].length)
  }
  return { options, rest }
}

/** Send an intervention; the reply (or the error) is the backend's audit summary. */
async function send(request) {
  try {
    const res = await request
    return { ok: true, text: res.data?.summary || '' }
  } catch (err) {
    return { ok: false, text: err.message || String(err) }
  }
}

export const COMMANDS = [
  {
    name: 'focus', usage: 'focus <agent|topic>', arg: 'agent',
    run: arg => {
      if (!arg) return fail('god.cmd.needArg', { usage: 'focus <agent|topic>' })
      const f = setFocus(arg)
      return ok(f.type === 'agent' ? 'god.cmd.focusAgent' : 'god.cmd.focusTopic', { label: f.label })
    }
  },
  {
    name: 'unfocus', usage: 'unfocus',
    run: () => { setFocus(null); return ok('god.cmd.unfocused') }
  },
  {
    name: 'select', usage: 'select <agent>', arg: 'agent',
    run: arg => {
      const agent = resolveAgent(arg)
      if (!agent) return fail('god.cmd.noAgent', { name: arg || '' })
      selectAgent(agent.id)
      return ok('god.cmd.selected', { label: agent.name })
    }
  },
  {
    name: 'goto', usage: 'goto <round>',
    run: arg => {
      const round = Number(arg)
      if (!arg || !Number.isInteger(round) || round < 0) return fail('god.cmd.needArg', { usage: 'goto <round>' })
      if (round > liveRound.value) return fail('god.cmd.roundAhead', { round, live: liveRound.value })
      stopPlayback()
      scrubTo(round)
      return ok('god.cmd.wentTo', { round })
    }
  },
  { name: 'live', usage: 'live', run: () => { goLive(); return ok('god.cmd.live') } },
  { name: 'replay', usage: 'replay', run: () => { startPlayback(); return ok('god.cmd.replaying') } },
  { name: 'stop', usage: 'stop', run: () => { stopPlayback(); return ok('god.cmd.replayStopped') } },
  { name: 'back', usage: 'back', run: () => { stepRound(-1); return ok('god.cmd.wentTo', { round: state.scrubRound ?? liveRound.value }) } },
  { name: 'next', usage: 'next', run: () => { stepRound(1); return ok('god.cmd.wentTo', { round: state.scrubRound ?? liveRound.value }) } },
  {
    name: 'filter', usage: 'filter <twitter|reddit|ACTION_TYPE|keyword|clear>',
    run: arg => {
      const value = (arg || '').trim()
      if (!value) return fail('god.cmd.needArg', { usage: 'filter <twitter|reddit|ACTION_TYPE|keyword|clear>' })
      if (value === 'clear') {
        Object.assign(state.filters, { platform: 'all', actionType: 'all', keyword: '' })
      } else if (value === 'twitter' || value === 'reddit') state.filters.platform = value
      else if (/^[A-Z_]+$/.test(value)) state.filters.actionType = value
      else state.filters.keyword = value
      return ok('god.cmd.filtered', { value })
    }
  },
  { name: 'help', usage: 'help', run: (_arg, ctx) => { ctx.openHelp(); return ok('god.cmd.helpOpened') } },

  {
    name: 'pause', usage: 'pause', god: true,
    run: () => send(godPause(state.simulationId))
  },
  {
    name: 'resume', usage: 'resume', god: true,
    run: () => send(godResume(state.simulationId))
  },
  {
    name: 'step', usage: 'step', god: true,
    run: () => send(godStep(state.simulationId))
  },
  {
    name: 'inject', usage: 'inject [as=<agent id>] <event text>', god: true,
    run: arg => {
      const { options, rest } = splitOptions(arg, ['as', 'platform'])
      if (!rest) return fail('god.cmd.needArg', { usage: 'inject [as=<agent id>] <event text>' })
      const data = { text: rest }
      if (options.as !== undefined) {
        const agent = resolveAgent(options.as)
        if (!agent) return fail('god.cmd.noAgent', { name: options.as })
        data.agent_id = agent.id
      }
      if (options.platform) data.platform = options.platform
      return send(godInject(state.simulationId, data))
    }
  },
  {
    name: 'whisper', usage: 'whisper <agent> <text>', arg: 'agent', god: true,
    run: arg => {
      const { agent, rest } = splitAgent(arg)
      if (!agent) return fail('god.cmd.noAgent', { name: (arg || '').split(/\s+/)[0] })
      if (!rest) return fail('god.cmd.needArg', { usage: 'whisper <agent> <text>' })
      return send(godWhisper(state.simulationId, { agent_id: agent.id, text: rest }))
    }
  },
  {
    name: 'interview', usage: 'interview <agent> <question>', arg: 'agent', god: true,
    run: arg => {
      const { agent, rest } = splitAgent(arg)
      if (!agent) return fail('god.cmd.noAgent', { name: (arg || '').split(/\s+/)[0] })
      if (!rest) return fail('god.cmd.needArg', { usage: 'interview <agent> <question>' })
      selectAgent(agent.id)
      return send(godInterview(state.simulationId, { agent_id: agent.id, question: rest }))
    }
  },
  {
    name: 'poll', usage: 'poll [stance=..] [type=..] [options=a|b|c] <question>', god: true,
    run: arg => {
      const { options, rest } = splitOptions(arg, ['stance', 'type', 'options', 'platform'])
      if (!rest) return fail('god.cmd.needArg', { usage: 'poll [stance=..] [type=..] [options=a|b|c] <question>' })
      const data = { question: rest }
      if (options.stance || options.type) {
        const chosen = agents.value.filter(a =>
          (!options.stance || a.stance.toLowerCase() === options.stance.toLowerCase()) &&
          (!options.type || a.type.toLowerCase() === options.type.toLowerCase())
        )
        if (!chosen.length) return fail('god.cmd.pollNobody')
        data.agent_ids = chosen.map(a => a.id)
      }
      if (options.options) data.options = options.options.split('|').filter(Boolean)
      if (options.platform) data.platform = options.platform
      return send(godPoll(state.simulationId, data))
    }
  },
  {
    name: 'report', usage: 'report', god: true,
    run: () => send(godReport(state.simulationId))
  },

  {
    name: 'fork', usage: 'fork <name>', god: true,
    run: arg => {
      if (!arg || /\s/.test(arg)) return fail('god.cmd.needArg', { usage: 'fork <name>' })
      return send(godFork(state.simulationId, arg))
    }
  },
  {
    name: 'branches', usage: 'branches',
    run: async () => {
      try {
        const { branches, current } = (await getBranches(state.simulationId)).data
        const text = branches.map(b =>
          `${b.name === current ? '*' : ''}${b.name}` +
          (b.fork_round === null ? '' : `@R${b.fork_round}`) + ` (${b.runner_status} R${b.current_round})`
        ).join('  ')
        return { ok: true, text }
      } catch (err) {
        return { ok: false, text: err.message || String(err) }
      }
    }
  },
  {
    name: 'switch', usage: 'switch <branch|base>',
    run: async (arg, ctx) => {
      if (!arg) return fail('god.cmd.needArg', { usage: 'switch <branch|base>' })
      try {
        const { branches } = (await getBranches(state.simulationId)).data
        const target = branches.find(b => b.name === arg || b.simulation_id === arg)
        if (!target) return fail('god.cmd.noBranch', { name: arg })
        ctx.openSimulation(target.simulation_id)
        return ok('god.cmd.switched', { name: target.name })
      } catch (err) {
        return { ok: false, text: err.message || String(err) }
      }
    }
  },
  {
    name: 'diff', usage: 'diff <branch> <branch>',
    run: (arg, ctx) => {
      const names = (arg || '').split(/\s+/).filter(Boolean)
      if (names.length !== 2) return fail('god.cmd.needArg', { usage: 'diff <branch> <branch>' })
      ctx.openDiff(names[0], names[1])
      return ok('god.cmd.diffOpened', { a: names[0], b: names[1] })
    }
  }
]

export async function execute(line, ctx) {
  const text = line.trim()
  if (!text) return null
  const space = text.indexOf(' ')
  const name = (space < 0 ? text : text.slice(0, space)).toLowerCase()
  const arg = space < 0 ? '' : text.slice(space + 1).trim()
  const command = COMMANDS.find(c => c.name === name)
  if (!command) return fail('god.cmd.unknown', { name })
  if (command.pending) return fail('god.cmd.pending', { name })
  return command.run(arg, ctx)
}
