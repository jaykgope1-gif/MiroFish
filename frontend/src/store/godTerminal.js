/**
 * God View Terminal state.
 *
 * One simulation at a time. Agent actions arrive over SSE and are appended to
 * a plain (non-reactive) array; `state.version` is bumped at most once per
 * animation frame so panels re-derive in batches instead of per event.
 */
import { reactive, computed, shallowRef } from 'vue'
import { godStreamUrl } from '../api/god'
import {
  getSimulation,
  getSimulationConfig,
  getSimulationProfiles
} from '../api/simulation'

export const STANCES = ['supportive', 'opposing', 'neutral', 'observer']

// Engagement an author receives; used for the roster's REACH column.
const REACH_ACTIONS = new Set([
  'LIKE_POST', 'REPOST', 'QUOTE_POST', 'CREATE_COMMENT', 'LIKE_COMMENT', 'FOLLOW'
])
// Actions whose text was written by the acting agent (topic counting).
const AUTHORED_ACTIONS = new Set(['CREATE_POST', 'CREATE_COMMENT', 'QUOTE_POST'])

const RETRY_DELAYS = [1, 2, 4, 8, 15]
// The server pings every 10s; this long without anything means the link is dead.
const STALL_MS = 25000

let events = []
let auditEntries = []
let eventSource = null
let retryTimer = null
let stallTimer = null
let playTimer = null
let frameRequested = false
let cursor = ''

export const state = reactive({
  simulationId: null,
  // idle | connecting | live | reconnecting | notfound
  conn: 'idle',
  attempt: 0,
  retryIn: 0,
  metaLoading: false,
  metaError: '',
  sim: null,
  config: null,
  status: null,
  version: 0,
  maxRound: 0,
  // null = follow the live edge; a number = view the world as of that round
  scrubRound: null,
  playing: false,
  selectedAgentId: null,
  // null | { type: 'agent', id, label } | { type: 'topic', text, label }
  focus: null,
  filters: { platform: 'all', actionType: 'all', keyword: '' }
})

export const agents = shallowRef([])
const agentById = shallowRef(new Map())
const agentIdByName = shallowRef(new Map())

/* ---------- helpers ---------- */

export function eventText(e) {
  const a = e.action_args || {}
  return a.content || a.quote_content || a.query || ''
}

export function eventTargetName(e) {
  const a = e.action_args || {}
  return a.post_author_name || a.original_author_name || a.comment_author_name || a.target_user_name || ''
}

export function eventTargetText(e) {
  const a = e.action_args || {}
  return a.post_content || a.original_content || a.comment_content || ''
}

function searchable(e) {
  if (e._s === undefined) {
    e._s = `${e.agent_name} ${e.action_type} ${eventText(e)} ${eventTargetName(e)} ${eventTargetText(e)}`.toLowerCase()
  }
  return e._s
}

export function getAgent(id) {
  return agentById.value.get(id) || null
}

/** Resolve "3", "Maya Chen" or an unambiguous name prefix to an agent. */
export function resolveAgent(token) {
  const text = String(token || '').trim().toLowerCase()
  if (!text) return null
  if (/^\d+$/.test(text)) return getAgent(Number(text))
  const list = agents.value
  return (
    list.find(a => a.name.toLowerCase() === text) ||
    (list.filter(a => a.name.toLowerCase().startsWith(text)).length === 1
      ? list.find(a => a.name.toLowerCase().startsWith(text))
      : null)
  )
}

function matchesFocus(e) {
  const f = state.focus
  if (!f) return true
  if (f.type === 'agent') {
    return e.agent_id === f.id || agentIdByName.value.get(eventTargetName(e)) === f.id
  }
  return searchable(e).includes(f.text)
}

/* ---------- derived views ---------- */

export const liveRound = computed(() =>
  Math.max(state.maxRound, state.status?.current_round || 0)
)
export const totalRounds = computed(() =>
  Math.max(state.status?.total_rounds || 0, liveRound.value)
)
export const asOfRound = computed(() =>
  state.scrubRound === null ? liveRound.value : state.scrubRound
)
export const isLiveView = computed(() => state.scrubRound === null)

/** Events up to the viewed round that match the current focus, oldest first. */
export const scopedEvents = computed(() => {
  state.version // dependency
  const limit = state.scrubRound === null ? Infinity : state.scrubRound
  const out = []
  for (let i = 0; i < events.length; i++) {
    const e = events[i]
    if (e.round <= limit && matchesFocus(e)) out.push(e)
  }
  return out
})

/** scopedEvents narrowed by the feed's own filters, oldest first. */
export const feedEvents = computed(() => {
  const { platform, actionType, keyword } = state.filters
  const kw = keyword.trim().toLowerCase()
  const src = scopedEvents.value
  if (platform === 'all' && actionType === 'all' && !kw) return src
  return src.filter(e =>
    (platform === 'all' || e.platform === platform) &&
    (actionType === 'all' || e.action_type === actionType) &&
    (!kw || searchable(e).includes(kw))
  )
})

export const actionTypes = computed(() => {
  state.version
  const seen = new Set()
  for (let i = 0; i < events.length; i++) seen.add(events[i].action_type)
  return [...seen].sort()
})

/** Per-agent activity and reach as of the viewed round (focus applied). */
export const agentStats = computed(() => {
  const stats = new Map()
  const byName = agentIdByName.value
  const bump = (id, key) => {
    let s = stats.get(id)
    if (!s) { s = { activity: 0, reach: 0 }; stats.set(id, s) }
    s[key]++
  }
  for (const e of scopedEvents.value) {
    bump(e.agent_id, 'activity')
    if (REACH_ACTIONS.has(e.action_type)) {
      const target = byName.get(eventTargetName(e))
      if (target !== undefined && target !== e.agent_id) bump(target, 'reach')
    }
  }
  return stats
})

/** Interventions up to the viewed round, oldest first. */
export const auditLog = computed(() => {
  state.version
  const limit = state.scrubRound === null ? Infinity : state.scrubRound
  return auditEntries.filter(e => (e.round || 0) <= limit)
})

/** Successful interventions grouped by round, for timeline and pulse markers. */
export const interventionsByRound = computed(() => {
  state.version
  const byRound = new Map()
  for (const e of auditEntries) {
    if (!e.ok) continue
    const round = e.round || 0
    if (!byRound.has(round)) byRound.set(round, [])
    byRound.get(round).push(e)
  }
  return byRound
})

/** "agentId|content" of every injected post, so the feed can flag them. */
export const injectedPosts = computed(() => {
  state.version
  const keys = new Set()
  for (const e of auditEntries) {
    if (e.ok && e.command === 'inject' && e.result) keys.add(`${e.result.agent_id}|${e.result.content}`)
  }
  return keys
})

export function isInjected(e) {
  return e.action_type === 'CREATE_POST' && injectedPosts.value.has(`${e.agent_id}|${eventText(e)}`)
}

/** Operator clock control as reported by the backend. */
export const clock = computed(() => {
  const g = state.status?.god
  if (!g?.available) return 'off'
  if (!g.paused) return 'running'
  return g.holding ? 'paused' : 'pausing'
})

export const hotTopics = computed(() =>
  (state.config?.event_config?.hot_topics || []).filter(Boolean)
)

/**
 * One entry per round, for the whole run (focus applied, not cut at the
 * viewed round: the pulse strip draws the cursor itself).
 */
export const roundSeries = computed(() => {
  state.version
  const topics = hotTopics.value.map(t => t.toLowerCase())
  const n = totalRounds.value + 1
  const rows = Array.from({ length: n }, (_, round) => ({
    round, twitter: 0, reddit: 0, total: 0,
    stance: { supportive: 0, opposing: 0, neutral: 0, observer: 0, unknown: 0 },
    topics: topics.map(() => 0)
  }))
  for (let i = 0; i < events.length; i++) {
    const e = events[i]
    if (!matchesFocus(e)) continue
    const row = rows[e.round]
    if (!row) continue
    row[e.platform === 'twitter' ? 'twitter' : 'reddit']++
    row.total++
    const stance = agentById.value.get(e.agent_id)?.stance
    row.stance[STANCES.includes(stance) ? stance : 'unknown']++
    if (topics.length && AUTHORED_ACTIONS.has(e.action_type)) {
      const text = eventText(e).toLowerCase()
      for (let t = 0; t < topics.length; t++) if (text.includes(topics[t])) row.topics[t]++
    }
  }
  return rows
})

/* ---------- metadata (existing REST endpoints) ---------- */

async function loadMeta(simulationId) {
  state.metaLoading = true
  state.metaError = ''
  try {
    const [sim, config] = await Promise.all([
      getSimulation(simulationId),
      getSimulationConfig(simulationId)
    ])
    const profileSets = await Promise.all(
      ['reddit', 'twitter'].map(p =>
        getSimulationProfiles(simulationId, p).then(r => r.data?.profiles || []).catch(() => [])
      )
    )
    if (state.simulationId !== simulationId) return
    state.sim = sim.data
    state.config = config.data
    buildAgents(config.data, profileSets[0], profileSets[1])
  } catch (err) {
    if (state.simulationId === simulationId) state.metaError = err.message || String(err)
  } finally {
    if (state.simulationId === simulationId) state.metaLoading = false
  }
}

function buildAgents(config, redditProfiles, twitterProfiles) {
  const reddit = new Map(redditProfiles.map(p => [Number(p.user_id), p]))
  const twitter = new Map(twitterProfiles.map(p => [Number(p.user_id), p]))
  const list = (config?.agent_configs || []).map(c => {
    const rd = reddit.get(c.agent_id)
    const tw = twitter.get(c.agent_id)
    return {
      id: c.agent_id,
      name: c.entity_name || rd?.name || tw?.name || `Agent_${c.agent_id}`,
      type: c.entity_type || '',
      stance: c.stance || '',
      sentimentBias: c.sentiment_bias,
      influenceWeight: c.influence_weight,
      activityLevel: c.activity_level,
      activeHours: c.active_hours || [],
      entityUuid: c.entity_uuid || '',
      username: rd?.username || tw?.username || '',
      bio: rd?.bio || tw?.description || '',
      persona: rd?.persona || tw?.user_char || '',
      reddit: rd || null,
      twitter: tw || null
    }
  })
  agents.value = list
  agentById.value = new Map(list.map(a => [a.id, a]))
  agentIdByName.value = new Map(list.map(a => [a.name, a.id]))
  state.version++
}

/* ---------- stream ---------- */

function scheduleVersionBump() {
  if (frameRequested) return
  frameRequested = true
  requestAnimationFrame(() => {
    frameRequested = false
    state.version++
  })
}

function armStallTimer() {
  clearTimeout(stallTimer)
  stallTimer = setTimeout(() => dropAndRetry(), STALL_MS)
}

function onActions(payload) {
  for (const item of payload.items) {
    if (item.event_type || item.agent_id === undefined) continue
    item.round = item.round || 0
    item.key = `${item.platform}:${item.seq}`
    events.push(item)
    if (item.round > state.maxRound) state.maxRound = item.round
  }
  scheduleVersionBump()
}

function onAudit(payload) {
  for (const item of payload.items) auditEntries.push(item)
  scheduleVersionBump()
}

function onReset(payload) {
  if (payload.platform === 'audit') {
    auditEntries = []
    scheduleVersionBump()
    return
  }
  // The simulation was restarted and its logs cleaned: forget that platform.
  events = events.filter(e => e.platform !== payload.platform)
  state.maxRound = events.reduce((m, e) => Math.max(m, e.round), 0)
  if (state.scrubRound !== null && state.scrubRound > state.maxRound) state.scrubRound = null
  scheduleVersionBump()
}

function openStream() {
  clearTimeout(retryTimer)
  const simulationId = state.simulationId
  if (!simulationId) return
  state.conn = state.attempt === 0 ? 'connecting' : 'reconnecting'
  state.retryIn = 0

  const es = new EventSource(godStreamUrl(simulationId, cursor))
  eventSource = es
  const on = (name, handler) => es.addEventListener(name, ev => {
    if (eventSource !== es) return
    armStallTimer()
    if (ev.lastEventId) cursor = ev.lastEventId
    handler(JSON.parse(ev.data))
  })
  on('hello', () => {
    state.conn = 'live'
    state.attempt = 0
    // Only ask the REST endpoints about a simulation the stream confirmed
    // exists: they create an empty directory for unknown ids.
    if (!state.sim && !state.metaLoading) loadMeta(simulationId)
  })
  on('status', data => { state.status = data })
  on('actions', onActions)
  on('audit', onAudit)
  on('reset', onReset)
  on('ping', () => {})
  es.onerror = () => {
    if (eventSource === es) dropAndRetry()
  }
  armStallTimer()
}

async function dropAndRetry() {
  clearTimeout(stallTimer)
  if (eventSource) { eventSource.close(); eventSource = null }
  const simulationId = state.simulationId
  if (!simulationId) return

  // EventSource hides HTTP status; ask once whether the simulation exists
  // so "unknown id" is not shown as "backend down".
  try {
    const res = await fetch(godStreamUrl(simulationId, cursor), { method: 'HEAD' })
    if (state.simulationId !== simulationId) return
    if (res.status === 404) { state.conn = 'notfound'; return }
  } catch { /* backend unreachable: fall through to retry */ }
  if (state.simulationId !== simulationId) return

  const delay = RETRY_DELAYS[Math.min(state.attempt, RETRY_DELAYS.length - 1)]
  state.attempt++
  state.conn = 'reconnecting'
  state.retryIn = delay
  const tick = () => {
    if (state.simulationId !== simulationId) return
    if (state.retryIn <= 1) { openStream(); return }
    state.retryIn--
    retryTimer = setTimeout(tick, 1000)
  }
  retryTimer = setTimeout(tick, 1000)
}

export function reconnectNow() {
  clearTimeout(retryTimer)
  if (eventSource) { eventSource.close(); eventSource = null }
  openStream()
}

export function connect(simulationId) {
  disconnect()
  state.simulationId = simulationId
  openStream()
}

export function disconnect() {
  clearTimeout(retryTimer)
  clearTimeout(stallTimer)
  stopPlayback()
  if (eventSource) { eventSource.close(); eventSource = null }
  events = []
  auditEntries = []
  cursor = ''
  agents.value = []
  agentById.value = new Map()
  agentIdByName.value = new Map()
  Object.assign(state, {
    simulationId: null, conn: 'idle', attempt: 0, retryIn: 0,
    metaLoading: false, metaError: '', sim: null, config: null, status: null,
    maxRound: 0, scrubRound: null, playing: false, selectedAgentId: null, focus: null
  })
  state.filters.platform = 'all'
  state.filters.actionType = 'all'
  state.filters.keyword = ''
  state.version++
}

export function retryMeta() {
  if (state.simulationId) loadMeta(state.simulationId)
}

/* ---------- actions used by panels and the command line ---------- */

export function selectAgent(id) {
  state.selectedAgentId = id
}

export function setFocus(target) {
  if (!target) { state.focus = null; return null }
  const agent = resolveAgent(target)
  if (agent) {
    state.focus = { type: 'agent', id: agent.id, label: agent.name }
    state.selectedAgentId = agent.id
  } else {
    const text = String(target).trim()
    state.focus = { type: 'topic', text: text.toLowerCase(), label: text }
  }
  return state.focus
}

export function scrubTo(round) {
  const live = liveRound.value
  const r = Math.max(0, Math.min(Math.round(round), live))
  state.scrubRound = r
}

export function goLive() {
  stopPlayback()
  state.scrubRound = null
}

export function stepRound(delta) {
  stopPlayback()
  const next = asOfRound.value + delta
  if (next >= liveRound.value && delta > 0) { state.scrubRound = null; return }
  scrubTo(next)
}

/** Replay recorded rounds from the viewed round forward. Does not touch the simulation. */
export function startPlayback() {
  if (state.playing) return
  if (state.scrubRound === null || state.scrubRound >= liveRound.value) state.scrubRound = 0
  state.playing = true
  playTimer = setInterval(() => {
    if (state.scrubRound === null || state.scrubRound >= liveRound.value) {
      goLive()
      return
    }
    state.scrubRound++
  }, 700)
}

export function stopPlayback() {
  clearInterval(playTimer)
  playTimer = null
  state.playing = false
}

export function togglePlayback() {
  state.playing ? stopPlayback() : startPlayback()
}
