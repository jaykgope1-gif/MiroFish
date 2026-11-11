<template>
  <section
    ref="root"
    class="gp graph"
    tabindex="0"
    data-panel="graph"
    :aria-label="$t('god.graph.title')"
    @keydown="onKey"
  >
    <header class="gp-head">
      <span class="gp-key">7</span>
      <span class="gp-title">{{ $t('god.graph.title') }}</span>
      <span v-if="nodes.length" class="gp-meta">{{ $t('god.graph.count', { nodes: nodes.length, edges: links.length, agents: agentNodes.length }) }}</span>
      <span class="gp-spacer"></span>
      <span v-if="nodes.length" class="legend">
        <span v-for="item in legend" :key="item.label"><i class="dot" :style="{ background: item.color }"></i>{{ item.label }}</span>
      </span>
      <button v-if="nodes.length" class="g-link" @click="toggleColor">
        {{ colorBy === 'stance' ? $t('god.graph.byType') : $t('god.graph.byStance') }}
      </button>
    </header>

    <div v-if="loading" class="g-empty">{{ $t('god.graph.loading') }}</div>
    <div v-else-if="error" class="g-empty">
      {{ $t('god.graph.error', { error }) }}
      <button class="g-link" @click="load">{{ $t('god.state.retry') }}</button>
    </div>
    <div v-else-if="!graphId" class="g-empty">{{ $t('god.graph.noGraph') }}</div>
    <div v-else-if="!nodes.length" class="g-empty">{{ $t('god.graph.empty') }}</div>

    <div v-else ref="stage" class="stage">
      <svg ref="svg" :width="size.w" :height="size.h">
        <g :transform="transform">
          <line
            v-for="l in links"
            :key="l.id"
            :x1="l.source.x" :y1="l.source.y" :x2="l.target.x" :y2="l.target.y"
            class="edge"
            :class="{ lit: isLit(l.source) && isLit(l.target) && highlight }"
          />
          <g
            v-for="n in nodes"
            :key="n.id"
            class="node"
            :class="{ agent: n.agent, dim: highlight && !isLit(n), picked: n.agent && n.agent.id === state.selectedAgentId, cursor: n === cursorNode }"
            :transform="`translate(${n.x},${n.y})`"
            @click="pick(n)"
            @mouseenter="hover = n"
            @mouseleave="hover = null"
          >
            <circle v-if="n.agent && (n.agent.id === state.selectedAgentId || n === cursorNode)" :r="radius(n) + 4" class="ring" />
            <circle :r="radius(n)" :fill="colorOf(n)" />
            <text v-if="labelled.has(n.id)" :y="-radius(n) - 4" text-anchor="middle">{{ n.name }}</text>
          </g>
        </g>
      </svg>
      <div v-if="hover" class="tip">
        <div class="tip-name">{{ hover.name }}</div>
        <div class="tip-meta">
          {{ hover.labels.join(', ') || '—' }}
          <template v-if="hover.agent"> · {{ hover.agent.stance || '—' }} · {{ $t('god.roster.colReach') }} {{ reachOf(hover) }} · {{ $t('god.roster.colInfluence') }} {{ hover.agent.influenceWeight ?? '—' }}</template>
          <template v-else> · {{ $t('god.graph.notAgent') }}</template>
        </div>
        <div v-if="hover.summary" class="tip-sum">{{ hover.summary }}</div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted, shallowRef } from 'vue'
import * as d3 from 'd3'
import { useI18n } from 'vue-i18n'
import { getGraphData } from '../../api/graph'
import { state, agents, agentStats, selectAgent } from '../../store/godTerminal'

const { t } = useI18n()

const STANCE_COLORS = {
  supportive: 'var(--g-st-supportive)', opposing: 'var(--g-st-opposing)',
  neutral: 'var(--g-st-neutral)', observer: 'var(--g-st-observer)'
}
// Colour by entity type uses the same four validated slots; further types fold into "other".
const SLOT_COLORS = Object.values(STANCE_COLORS)
const OTHER = 'var(--g-st-unknown)'
const MAX_LABELS = 14

const root = ref(null)
const stage = ref(null)
const svg = ref(null)
const loading = ref(false)
const error = ref('')
const nodes = shallowRef([])
const links = shallowRef([])
const size = reactive({ w: 400, h: 300 })
const transform = ref('')
// shallowRef: nodes are compared by identity with the entries of `nodes`.
const hover = shallowRef(null)
const colorBy = ref('stance')
const cursorNode = shallowRef(null)

const graphId = computed(() => state.sim?.graph_id || '')
const agentNodes = computed(() => nodes.value.filter(n => n.agent))

async function load() {
  if (!graphId.value) return
  loading.value = true
  error.value = ''
  try {
    const res = await getGraphData(graphId.value)
    build(res.data)
  } catch (err) {
    error.value = err.message || String(err)
    nodes.value = []
    links.value = []
  } finally {
    loading.value = false
  }
  nextTick(observe)
}

function build(data) {
  // An agent is the graph entity it was generated from (config entity_uuid).
  const agentByUuid = new Map(agents.value.filter(a => a.entityUuid).map(a => [a.entityUuid, a]))
  const list = (data.nodes || []).map(n => ({
    id: n.uuid, name: n.name || '', summary: n.summary || '',
    labels: (n.labels || []).filter(l => l !== 'Entity' && l !== 'Node'),
    agent: agentByUuid.get(n.uuid) || null
  }))
  const byId = new Map(list.map(n => [n.id, n]))
  const edges = (data.edges || [])
    .filter(e => byId.has(e.source_node_uuid) && byId.has(e.target_node_uuid))
    .map(e => ({ id: e.uuid, source: e.source_node_uuid, target: e.target_node_uuid, name: e.name || e.fact_type || '' }))

  // Lay out once, synchronously, then draw a static picture: no per-frame work.
  const sim = d3.forceSimulation(list)
    .force('link', d3.forceLink(edges).id(n => n.id).distance(46))
    .force('charge', d3.forceManyBody().strength(-90))
    .force('x', d3.forceX().strength(0.06))
    .force('y', d3.forceY().strength(0.06))
    .force('collide', d3.forceCollide(10))
    .stop()
  sim.tick(Math.min(300, 60 + Math.ceil(12000 / Math.max(list.length, 1))))

  const neighbours = new Map(list.map(n => [n.id, new Set()]))
  for (const e of edges) {
    neighbours.get(e.source.id).add(e.target.id)
    neighbours.get(e.target.id).add(e.source.id)
  }
  list.forEach(n => { n.neighbours = neighbours.get(n.id) })
  nodes.value = list
  links.value = edges
  nextTick(fit)
}

/* ---------- encoding ---------- */

// Influence = engagement received so far plus the configured weight, so
// nodes are sized before anything has happened and grow as the run goes on.
const reachOf = n => (n.agent ? agentStats.value.get(n.agent.id)?.reach || 0 : 0)
const influence = n => (n.agent ? reachOf(n) + (n.agent.influenceWeight || 0) : 0)
const maxInfluence = computed(() => Math.max(1, ...agentNodes.value.map(influence)))
const radius = n => (n.agent ? 4 + 10 * Math.sqrt(influence(n) / maxInfluence.value) : 2.5)

const typeSlots = computed(() => {
  const counts = new Map()
  for (const n of agentNodes.value) counts.set(n.agent.type, (counts.get(n.agent.type) || 0) + 1)
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]))).slice(0, SLOT_COLORS.length)
  return new Map(top.map(([type], i) => [type, SLOT_COLORS[i]]))
})

function colorOf(n) {
  if (!n.agent) return 'var(--g-line)'
  if (colorBy.value === 'stance') return STANCE_COLORS[n.agent.stance] || OTHER
  return typeSlots.value.get(n.agent.type) || OTHER
}

const legend = computed(() => {
  const items = colorBy.value === 'stance'
    ? Object.entries(STANCE_COLORS).map(([label, color]) => ({ label, color }))
    : [...typeSlots.value.entries()].map(([label, color]) => ({ label: label || '—', color }))
  if (colorBy.value === 'type' && new Set(agentNodes.value.map(n => n.agent.type)).size > typeSlots.value.size) {
    items.push({ label: t('god.graph.other'), color: OTHER })
  }
  return items
})

function toggleColor() {
  colorBy.value = colorBy.value === 'stance' ? 'type' : 'stance'
}

// The biggest agents are always labelled; so are the selected and hovered ones.
const labelled = computed(() => {
  const ids = new Set(
    agentNodes.value.slice().sort((a, b) => influence(b) - influence(a)).slice(0, MAX_LABELS).map(n => n.id)
  )
  for (const n of [hover.value, cursorNode.value]) if (n) ids.add(n.id)
  const picked = nodes.value.find(n => n.agent && n.agent.id === state.selectedAgentId)
  if (picked) ids.add(picked.id)
  return ids
})

// With an agent selected or focused, light up it and its neighbours.
const anchor = computed(() => {
  const id = state.focus?.type === 'agent' ? state.focus.id : state.selectedAgentId
  return id === null ? null : nodes.value.find(n => n.agent && n.agent.id === id) || null
})
const highlight = computed(() => anchor.value !== null)
const isLit = n => !anchor.value || n === anchor.value || anchor.value.neighbours.has(n.id)

/* ---------- interaction ---------- */

function pick(n) {
  cursorNode.value = n
  if (n.agent) selectAgent(n.agent.id)
}

let zoom
function fit() {
  if (!svg.value || !nodes.value.length) return
  const xs = nodes.value.map(n => n.x)
  const ys = nodes.value.map(n => n.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  // Leave room for the largest node and its label around the layout.
  const pad = 36
  const k = Math.min(4, Math.min(
    Math.max(size.w - 2 * pad, 20) / Math.max(x1 - x0, 1),
    Math.max(size.h - 2 * pad, 20) / Math.max(y1 - y0, 1)
  ))
  const next = d3.zoomIdentity.translate(size.w / 2 - k * (x0 + x1) / 2, size.h / 2 - k * (y0 + y1) / 2).scale(k)
  if (!zoom) {
    zoom = d3.zoom().scaleExtent([0.1, 8]).on('zoom', ev => { transform.value = ev.transform.toString() })
    d3.select(svg.value).call(zoom).on('dblclick.zoom', null)
  }
  d3.select(svg.value).call(zoom.transform, next)
}

function moveCursor(delta) {
  const list = agentNodes.value.slice().sort((a, b) => influence(b) - influence(a))
  if (!list.length) return
  const i = list.indexOf(cursorNode.value)
  cursorNode.value = list[(i + delta + list.length) % list.length]
}

function onKey(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return
  const handlers = {
    j: () => moveCursor(1), ArrowDown: () => moveCursor(1), ArrowRight: () => moveCursor(1),
    k: () => moveCursor(-1), ArrowUp: () => moveCursor(-1), ArrowLeft: () => moveCursor(-1),
    Enter: () => cursorNode.value && pick(cursorNode.value),
    c: toggleColor,
    0: fit
  }
  const handler = handlers[ev.key]
  if (handler) { ev.preventDefault(); handler() }
}

let observer
function observe() {
  observer?.disconnect()
  zoom = null
  if (!stage.value) return
  observer = new ResizeObserver(() => {
    size.w = stage.value.clientWidth
    size.h = stage.value.clientHeight
    fit()
  })
  observer.observe(stage.value)
}

// Agents load after the simulation record; rebuild once both are known.
watch([graphId, () => agents.value.length], () => { if (graphId.value && agents.value.length) load() }, { immediate: true })
onMounted(observe)
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.legend { display: flex; gap: 10px; color: var(--g-ink2); font-size: 11px; overflow: hidden; }
.legend .dot { margin-right: 4px; }
.stage { flex: 1; min-height: 0; position: relative; overflow: hidden; cursor: grab; }
svg { display: block; }
.edge { stroke: var(--g-line); stroke-width: 1; }
.edge.lit { stroke: var(--g-ink2); }
.node { cursor: default; }
.node.agent { cursor: pointer; }
.node circle { stroke: var(--g-panel); stroke-width: 2; }
.node .ring { fill: none; stroke: var(--g-ink-hi); stroke-width: 1.5; }
.node.dim { opacity: .22; }
.node.dim text { display: none; }
.node text { fill: var(--g-ink); font-size: 10px; paint-order: stroke; stroke: var(--g-panel); stroke-width: 3px; pointer-events: none; }
.node.picked text, .node.cursor text { fill: var(--g-ink-hi); }
.tip {
  position: absolute; left: 8px; bottom: 8px; max-width: min(420px, 90%); pointer-events: none;
  background: var(--g-bg); border: 1px solid var(--g-ink2); padding: 4px 8px; line-height: 1.4;
}
.tip-name { color: var(--g-ink-hi); }
.tip-meta { color: var(--g-ink2); }
.tip-sum { color: var(--g-ink2); max-height: 5.6em; overflow: hidden; }
</style>
