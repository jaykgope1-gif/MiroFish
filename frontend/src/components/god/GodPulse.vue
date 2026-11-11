<template>
  <section
    class="gp pulse"
    tabindex="0"
    data-panel="pulse"
    :aria-label="$t('god.pulse.title')"
    @keydown="onKey"
  >
    <header class="gp-head">
      <span class="gp-key">4</span>
      <span class="gp-title">{{ $t('god.pulse.title') }}</span>
      <span class="gp-meta">{{ $t('god.pulse.perRound') }}</span>
      <span class="gp-spacer"></span>
      <button class="g-link" :aria-pressed="showTable" @click="showTable = !showTable">
        {{ showTable ? $t('god.pulse.chart') : $t('god.pulse.table') }}
      </button>
    </header>

    <div v-if="!hasData" class="g-empty">{{ $t('god.pulse.empty') }}</div>

    <div v-else-if="showTable" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{{ $t('god.pulse.round') }}</th><th>twitter</th><th>reddit</th>
            <th v-for="s in STANCES" :key="s">{{ s }}</th>
            <th v-for="t in topicRows" :key="t.name">{{ t.name }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in series" :key="r.round" :class="{ future: r.round > asOfRound }">
            <td>{{ r.round }}</td><td>{{ r.twitter }}</td><td>{{ r.reddit }}</td>
            <td v-for="s in STANCES" :key="s">{{ r.stance[s] }}</td>
            <td v-for="t in topicRows" :key="t.name">{{ r.topics[t.index] }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="chart">
      <div class="labels">
        <div class="lab" :style="{ height: H_VOL + 'px' }">
          <b>{{ $t('god.pulse.volume') }}</b>
          <span><i class="sw" style="background: var(--g-plat-tw)"></i>twitter</span>
          <span><i class="sw" style="background: var(--g-plat-rd)"></i>reddit</span>
        </div>
        <div class="lab" :style="{ height: H_STANCE + 'px' }" :title="$t('god.pulse.stanceHint')">
          <b>{{ $t('god.pulse.stance') }}</b>
          <span v-for="s in STANCES" :key="s"><i class="sw" :class="'st-' + s"></i>{{ s }}</span>
        </div>
        <div class="lab topics" :style="{ height: topicsHeight + 'px' }">
          <b v-if="!topicRows.length">{{ $t('god.pulse.topics') }}</b>
          <span v-for="t in topicRows" :key="t.name" class="topic" :title="t.name">{{ t.name }}</span>
        </div>
      </div>

      <div ref="plot" class="plot" @mousemove="onMove" @mouseleave="hover = null" @click="onClick">
        <svg :width="width" :height="height" role="img" :aria-label="$t('god.pulse.title')">
          <!-- volume: stacked bars, reddit at the baseline -->
          <g>
            <template v-for="r in series" :key="'v' + r.round">
              <rect
                v-if="r.reddit"
                :x="x(r.round)" :width="barW"
                :y="H_VOL - volH(r.reddit)" :height="volH(r.reddit)"
                fill="var(--g-plat-rd)" :opacity="dim(r.round)"
              />
              <rect
                v-if="r.twitter"
                :x="x(r.round)" :width="barW"
                :y="H_VOL - volH(r.total) " :height="Math.max(0, volH(r.twitter) - 1)"
                fill="var(--g-plat-tw)" :opacity="dim(r.round)"
              />
            </template>
            <text :x="width - 2" y="9" text-anchor="end" class="axis">{{ $t('god.pulse.max', { n: maxTotal }) }}</text>
            <line x1="0" :x2="width" :y1="H_VOL" :y2="H_VOL" class="base" />
          </g>

          <!-- stance: share of each round's actions by the acting agent's stance -->
          <g :transform="`translate(0, ${H_VOL + GAP})`">
            <template v-for="r in series" :key="'s' + r.round">
              <rect
                v-for="seg in stanceSegments(r)"
                :key="seg.s"
                :x="x(r.round)" :width="barW" :y="seg.y" :height="seg.h"
                :class="'fill-' + seg.s" :opacity="dim(r.round)"
              />
            </template>
            <line x1="0" :x2="width" :y1="H_STANCE" :y2="H_STANCE" class="base" />
          </g>

          <!-- topics: one strip per topic, darker = more mentions that round -->
          <g :transform="`translate(0, ${H_VOL + H_STANCE + GAP * 2})`">
            <template v-for="(t, ti) in topicRows" :key="t.name">
              <rect
                v-for="r in series"
                :key="r.round"
                :x="x(r.round)" :width="barW" :y="ti * TOPIC_ROW + 1" :height="TOPIC_ROW - 3"
                :fill="r.topics[t.index] ? 'var(--g-seq)' : 'var(--g-line-soft)'"
                :opacity="r.topics[t.index] ? (0.25 + 0.75 * r.topics[t.index] / maxTopic) * dim(r.round) : dim(r.round)"
              />
            </template>
            <text v-if="!topicRows.length" x="4" y="12" class="axis">{{ $t('god.pulse.noTopics') }}</text>
          </g>

          <!-- interventions -->
          <path
            v-for="round in markedRounds"
            :key="'m' + round"
            :d="`M${cx(round) - 4} 0 L${cx(round) + 4} 0 L${cx(round)} 6 Z`"
            class="mark"
          />

          <!-- viewed round and hover crosshair -->
          <line :x1="cx(asOfRound)" :x2="cx(asOfRound)" y1="0" :y2="height" class="cursor" />
          <line v-if="hover" :x1="cx(hover.round)" :x2="cx(hover.round)" y1="0" :y2="height" class="cross" />
        </svg>

        <div v-if="hover" class="tip" :style="tipStyle">
          <div class="tip-head">{{ $t('god.pulse.round') }} {{ hover.round }}</div>
          <div><i class="sw" style="background: var(--g-plat-tw)"></i>twitter <b>{{ hover.row.twitter }}</b></div>
          <div><i class="sw" style="background: var(--g-plat-rd)"></i>reddit <b>{{ hover.row.reddit }}</b></div>
          <div class="tip-sep"></div>
          <div v-for="s in STANCES" :key="s"><i class="sw" :class="'st-' + s"></i>{{ s }} <b>{{ hover.row.stance[s] }}</b></div>
          <template v-if="topicRows.length">
            <div class="tip-sep"></div>
            <div v-for="t in topicRows" :key="t.name">{{ t.name }} <b>{{ hover.row.topics[t.index] }}</b></div>
          </template>
          <template v-if="interventionsByRound.get(hover.round)">
            <div class="tip-sep"></div>
            <div v-for="e in interventionsByRound.get(hover.round)" :key="e.id" class="tip-mark">▼ {{ e.command }}</div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import {
  STANCES, roundSeries, hotTopics, asOfRound, liveRound, totalRounds, interventionsByRound,
  scrubTo, goLive, stepRound
} from '../../store/godTerminal'

const H_VOL = 40
const H_STANCE = 44
const GAP = 6
const TOPIC_ROW = 12
const MAX_TOPICS = 4

const plot = ref(null)
const width = ref(600)
const hover = ref(null)
const showTable = ref(false)

const series = roundSeries
const markedRounds = computed(() => [...interventionsByRound.value.keys()])
const hasData = computed(() => series.value.some(r => r.total > 0))
const maxTotal = computed(() => Math.max(1, ...series.value.map(r => r.total)))

// The most-mentioned configured topics, in a stable order.
const topicRows = computed(() => {
  const totals = hotTopics.value.map((name, index) => ({
    name, index, total: series.value.reduce((sum, r) => sum + r.topics[index], 0)
  }))
  return totals.sort((a, b) => b.total - a.total || a.index - b.index).slice(0, MAX_TOPICS)
})
const maxTopic = computed(() =>
  Math.max(1, ...series.value.flatMap(r => topicRows.value.map(t => r.topics[t.index])))
)
const topicsHeight = computed(() => Math.max(1, topicRows.value.length) * TOPIC_ROW + 4)
const height = computed(() => H_VOL + H_STANCE + GAP * 2 + topicsHeight.value)

const slots = computed(() => totalRounds.value + 1)
const step = computed(() => width.value / slots.value)
const barW = computed(() => Math.max(1, step.value - (step.value > 4 ? 2 : 0)))
const x = round => round * step.value
const cx = round => round * step.value + barW.value / 2
const volH = n => (n / maxTotal.value) * (H_VOL - 12)
const dim = round => (round > asOfRound.value ? 0.28 : 1)

function stanceSegments(r) {
  const total = STANCES.reduce((sum, s) => sum + r.stance[s], 0)
  if (!total) return []
  const out = []
  let y = 0
  for (const s of STANCES) {
    const h = (r.stance[s] / total) * H_STANCE
    if (h > 0) out.push({ s, y, h: Math.max(0.5, h - 1) })
    y += h
  }
  return out
}

function roundAt(ev) {
  const rect = plot.value.getBoundingClientRect()
  return Math.max(0, Math.min(slots.value - 1, Math.floor((ev.clientX - rect.left) / step.value)))
}

function onMove(ev) {
  const round = roundAt(ev)
  hover.value = { round, row: series.value[round] }
}

function onClick(ev) {
  const round = roundAt(ev)
  if (round >= liveRound.value) goLive()
  else scrubTo(round)
}

// The tooltip is taller than the strip, so it is fixed to the viewport and
// grows upward from the strip's bottom edge instead of being clipped by it.
const tipStyle = computed(() => {
  const rect = plot.value.getBoundingClientRect()
  const left = rect.left + cx(hover.value.round)
  const flip = left > window.innerWidth - 200
  return {
    left: flip ? 'auto' : `${left + 10}px`,
    right: flip ? `${window.innerWidth - left + 10}px` : 'auto',
    bottom: `${Math.max(4, window.innerHeight - rect.bottom)}px`
  }
})

function onKey(ev) {
  if (ev.key === 'ArrowLeft') { ev.preventDefault(); stepRound(-1) }
  else if (ev.key === 'ArrowRight') { ev.preventDefault(); stepRound(1) }
  else if (ev.key === 'v') { showTable.value = !showTable.value }
}

let observer
function observe() {
  observer?.disconnect()
  if (!plot.value) return
  observer = new ResizeObserver(() => { width.value = Math.max(50, plot.value.clientWidth) })
  observer.observe(plot.value)
}
onMounted(observe)
watch([hasData, showTable], () => nextTick(observe))
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.chart { flex: 1; min-height: 0; display: flex; overflow-y: auto; padding: 4px 8px 4px 0; }
.labels { flex: none; width: 180px; padding-left: 8px; }
.lab { display: flex; flex-wrap: wrap; align-content: flex-start; gap: 0 10px; margin-bottom: 6px; overflow: hidden; color: var(--g-ink2); line-height: 14px; font-size: 11px; }
.lab b { width: 100%; font-weight: 400; color: var(--g-mute); text-transform: uppercase; letter-spacing: .04em; }
.lab.topics { display: block; margin-bottom: 0; }
.lab .topic { display: block; height: 12px; line-height: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sw { display: inline-block; width: 7px; height: 7px; margin-right: 4px; }
.plot { flex: 1; min-width: 0; position: relative; cursor: crosshair; }
svg { display: block; }
.axis { fill: var(--g-mute); font-size: 10px; }
.base { stroke: var(--g-line); stroke-width: 1; }
.cursor { stroke: var(--g-ink-hi); stroke-width: 1; }
.mark { fill: var(--g-warn); }
.tip-mark { color: var(--g-warn); }
.cross { stroke: var(--g-ink2); stroke-width: 1; stroke-dasharray: 2 2; }
.fill-supportive { fill: var(--g-st-supportive); }
.fill-opposing { fill: var(--g-st-opposing); }
.fill-neutral { fill: var(--g-st-neutral); }
.fill-observer { fill: var(--g-st-observer); }
.tip {
  position: fixed; z-index: 30; min-width: 150px; pointer-events: none;
  background: var(--g-bg); border: 1px solid var(--g-ink2); padding: 4px 8px; line-height: 15px; font-size: 11px;
  color: var(--g-ink2); white-space: nowrap;
}
.tip b { color: var(--g-ink-hi); font-weight: 400; float: right; margin-left: 12px; }
.tip-head { color: var(--g-ink-hi); }
.tip-sep { border-top: 1px solid var(--g-line); margin: 3px 0; }
.table-wrap { flex: 1; min-height: 0; overflow: auto; }
table { border-collapse: collapse; }
th, td { padding: 0 10px; height: 18px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
th { position: sticky; top: 0; background: var(--g-panel2); color: var(--g-mute); font-weight: 400; }
tr.future td { color: var(--g-mute); }
</style>
