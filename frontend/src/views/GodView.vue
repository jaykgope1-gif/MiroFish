<template>
  <div class="god-root">
    <!-- status line -->
    <header class="statusbar">
      <button class="brand" @click="router.push('/')">MIROFISH</button>
      <span class="sep">//</span>
      <span class="hi">{{ $t('god.title') }}</span>
      <template v-if="simulationId">
        <span class="cell"><span class="k">{{ $t('god.status.sim') }}</span>{{ simulationId.split('__')[0] }}</span>
        <span class="cell"><span class="k">{{ $t('god.status.branch') }}</span>{{ simulationId.split('__')[1] || 'base' }}</span>
        <span class="cell" :class="'conn-' + state.conn">
          <i class="lamp"></i>{{ $t('god.conn.' + state.conn) }}
        </span>
        <span class="cell"><span class="k">{{ $t('god.status.run') }}</span>{{ $t('god.phase.' + phase) }}</span>
        <span v-if="clock === 'paused' || clock === 'pausing'" class="cell clock">{{ $t('god.clock.' + clock) }}</span>
        <span class="cell">
          <span class="k">{{ $t('god.status.round') }}</span>{{ liveRound }}/{{ totalRounds }}
          <span class="k k2">TW</span>{{ state.status?.twitter_current_round ?? '—' }}
          <span class="k k2">RD</span>{{ state.status?.reddit_current_round ?? '—' }}
        </span>
        <span class="cell"><span class="k">{{ $t('god.status.actions') }}</span>{{ scopedEvents.length }}</span>
        <span v-if="state.focus" class="cell focus">
          <span class="k">{{ $t('god.status.focus') }}</span>{{ state.focus.label }}
          <button class="g-link" :aria-label="$t('god.status.clearFocus')" @click="setFocus(null)">✕</button>
        </span>
      </template>
      <span class="gp-spacer"></span>
      <button class="g-link" :aria-label="$t('god.status.language')" @click="nextLocale">{{ locale.toUpperCase() }}</button>
      <button class="g-link" @click="helpOpen = true">? {{ $t('god.status.keys') }}</button>
    </header>

    <!-- connection problems are stated in words, across the full width -->
    <div v-if="simulationId && state.conn === 'reconnecting'" class="banner crit" role="alert">
      {{ $t('god.banner.disconnected', { n: state.retryIn, attempt: state.attempt }) }}
      <button class="g-link" @click="reconnectNow">{{ $t('god.banner.retryNow') }}</button>
    </div>
    <div v-else-if="simulationId && state.conn === 'notfound'" class="banner crit" role="alert">
      {{ $t('god.banner.notFound', { id: simulationId }) }}
      <button class="g-link" @click="router.push('/god')">{{ $t('god.banner.pick') }}</button>
    </div>
    <div v-else-if="simulationId && state.status?.runner_status === 'failed'" class="banner warn" role="status">
      {{ $t('god.banner.failed', { error: (state.status.error || '').slice(0, 300) }) }}
    </div>

    <!-- no simulation chosen: pick one -->
    <main v-if="!simulationId" class="picker">
      <h2>{{ $t('god.picker.title') }}</h2>
      <p v-if="pickerLoading" class="g-empty">{{ $t('god.picker.loading') }}</p>
      <p v-else-if="pickerError" class="g-empty">
        {{ $t('god.picker.error', { error: pickerError }) }}
        <button class="g-link" @click="loadSimulations">{{ $t('god.state.retry') }}</button>
      </p>
      <p v-else-if="!simulations.length" class="g-empty">{{ $t('god.picker.empty') }}</p>
      <ul v-else>
        <li v-for="s in simulations" :key="s.simulation_id">
          <button @click="router.push('/god/' + s.simulation_id)">
            <span class="hi">{{ s.simulation_id }}</span>
            <span>{{ s.status }}</span>
            <span>{{ $t('god.picker.agents', { n: s.profiles_count }) }}</span>
            <span class="dim">{{ (s.created_at || '').slice(0, 16).replace('T', ' ') }}</span>
          </button>
        </li>
      </ul>
    </main>

    <!-- the terminal -->
    <main v-else ref="grid" class="grid">
      <div class="upper">
        <div class="left" :style="{ width: layout.feedPct + '%' }">
          <GodFeed class="fill" />
          <div
            class="split h" role="separator" tabindex="0" aria-orientation="horizontal"
            :aria-label="$t('god.layout.resizeAudit')"
            @pointerdown="startDrag($event, 'auditPct')" @keydown="nudge($event, 'auditPct')"
          ></div>
          <GodAudit :style="{ height: layout.auditPct + '%' }" />
        </div>
        <div
          class="split v" role="separator" tabindex="0" aria-orientation="vertical"
          :aria-label="$t('god.layout.resizeFeed')"
          @pointerdown="startDrag($event, 'feedPct')" @keydown="nudge($event, 'feedPct')"
        ></div>
        <div class="right">
          <div class="right-top" :class="{ both: wide }" :style="{ height: layout.rosterPct + '%' }">
            <GodRoster v-show="wide || rightTop === 'roster'" class="fill" />
            <GodGraph v-if="graphOpened" v-show="wide || rightTop === 'graph'" class="fill" />
          </div>
          <div
            class="split h" role="separator" tabindex="0" aria-orientation="horizontal"
            :aria-label="$t('god.layout.resizeRoster')"
            @pointerdown="startDrag($event, 'rosterPct')" @keydown="nudge($event, 'rosterPct')"
          ></div>
          <GodAgentDetail class="fill" />
        </div>
      </div>
      <div
        class="split h" role="separator" tabindex="0" aria-orientation="horizontal"
        :aria-label="$t('god.layout.resizePulse')"
        @pointerdown="startDrag($event, 'pulsePx')" @keydown="nudge($event, 'pulsePx')"
      ></div>
      <GodPulse :style="{ height: layout.pulsePx + 'px' }" />
      <GodTimeline class="timeline-row" />
    </main>

    <GodCommandLine
      v-if="simulationId"
      ref="commandLine"
      @open-help="helpOpen = true"
      @open-diff="diffOpen = $event"
      @open-simulation="router.push('/god/' + $event)"
      @leave="focusPanel(lastPanel)"
    />
    <GodHelp v-if="helpOpen" @close="closeHelp" />
    <GodDiff v-if="diffOpen" :a="diffOpen.a" :b="diffOpen.b" @close="closeDiff" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { availableLocales } from '../i18n'
import GodFeed from '../components/god/GodFeed.vue'
import GodRoster from '../components/god/GodRoster.vue'
import GodAgentDetail from '../components/god/GodAgentDetail.vue'
import GodPulse from '../components/god/GodPulse.vue'
import GodTimeline from '../components/god/GodTimeline.vue'
import GodCommandLine from '../components/god/GodCommandLine.vue'
import GodHelp from '../components/god/GodHelp.vue'
import GodAudit from '../components/god/GodAudit.vue'
import GodDiff from '../components/god/GodDiff.vue'
import GodGraph from '../components/god/GodGraph.vue'
import { listSimulations } from '../api/simulation'
import {
  state, connect, disconnect, reconnectNow, setFocus, scopedEvents,
  liveRound, totalRounds, stepRound, goLive, clock
} from '../store/godTerminal'

const route = useRoute()
const { locale } = useI18n()

// Same persistence as LanguageSwitcher, as a single button that fits the status line.
function nextLocale() {
  const keys = availableLocales.map(l => l.key)
  const next = keys[(keys.indexOf(locale.value) + 1) % keys.length]
  locale.value = next
  localStorage.setItem('locale', next)
  document.documentElement.lang = next
}
const router = useRouter()

const simulationId = computed(() => route.params.simulationId || '')

/* ---------- status ---------- */


// MiroFish keeps runner_status "running" after the last round while the
// environment stays open for interviews; show that as its own phase.
const phase = computed(() => {
  const s = state.status
  if (!s) return 'unknown'
  if (s.runner_status === 'running' && !s.twitter_running && !s.reddit_running &&
      (s.twitter_completed || s.reddit_completed)) return 'roundsDone'
  return ['idle', 'starting', 'running', 'paused', 'stopping', 'stopped', 'completed', 'failed']
    .includes(s.runner_status) ? s.runner_status : 'unknown'
})

/* ---------- simulation picker ---------- */

const simulations = ref([])
const pickerLoading = ref(false)
const pickerError = ref('')

async function loadSimulations() {
  pickerLoading.value = true
  pickerError.value = ''
  try {
    const res = await listSimulations()
    simulations.value = (res.data || []).slice().sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
  } catch (err) {
    pickerError.value = err.message || String(err)
  } finally {
    pickerLoading.value = false
  }
}

watch(simulationId, id => {
  if (id) connect(id)
  else { disconnect(); loadSimulations() }
}, { immediate: true })
onUnmounted(disconnect)

/* ---------- resizable layout ---------- */

const LAYOUT_KEY = 'god.layout'
const LIMITS = { feedPct: [25, 75], rosterPct: [20, 80], auditPct: [12, 70], pulsePx: [60, 400] }
const layout = reactive({ feedPct: 46, rosterPct: 45, auditPct: 30, pulsePx: 184 })
try { Object.assign(layout, JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}')) } catch { /* keep defaults */ }

const grid = ref(null)

function setSize(key, value) {
  const [min, max] = LIMITS[key]
  layout[key] = Math.round(Math.max(min, Math.min(max, value)) * 10) / 10
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)) } catch { /* storage unavailable */ }
}

function startDrag(ev, key) {
  ev.preventDefault()
  const upper = grid.value.querySelector('.upper').getBoundingClientRect()
  const all = grid.value.getBoundingClientRect()
  const move = e => {
    if (key === 'feedPct') setSize(key, ((e.clientX - upper.left) / upper.width) * 100)
    else if (key === 'rosterPct') setSize(key, ((e.clientY - upper.top) / upper.height) * 100)
    else if (key === 'auditPct') setSize(key, ((upper.bottom - e.clientY) / upper.height) * 100)
    else setSize(key, all.bottom - TIMELINE_PX - e.clientY)
  }
  const stop = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
}
const TIMELINE_PX = 38

function nudge(ev, key) {
  const dir = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[ev.key]
  if (!dir) return
  ev.preventDefault()
  ev.stopPropagation()
  // The pulse strip and the audit log grow upward, so their arrows are inverted.
  const step = key === 'pulsePx' ? -dir * 12 : key === 'auditPct' ? -dir * 2 : dir * 2
  setSize(key, layout[key] + step)
}

/* ---------- keyboard ---------- */

const PANELS = { 1: 'feed', 2: 'roster', 3: 'detail', 4: 'pulse', 5: 'timeline', 6: 'audit', 7: 'graph' }

// On a laptop the roster and the graph share one slot (keys 2 and 7 switch);
// on a wide monitor they sit side by side.
const WIDE_QUERY = window.matchMedia('(min-width: 1800px)')
const wide = ref(WIDE_QUERY.matches)
const onWide = ev => { wide.value = ev.matches }
onMounted(() => WIDE_QUERY.addEventListener('change', onWide))
onUnmounted(() => WIDE_QUERY.removeEventListener('change', onWide))
const rightTop = ref('roster')
// The graph is loaded the first time it is shown, then kept mounted so
// switching back to the roster does not throw away its layout.
const graphOpened = ref(wide.value)
watch([wide, rightTop], () => { if (wide.value || rightTop.value === 'graph') graphOpened.value = true })
const commandLine = ref(null)
const helpOpen = ref(false)
const lastPanel = ref('feed')

function focusPanel(name) {
  if (name === 'roster' || name === 'graph') rightTop.value = name
  nextTick(() => {
    const el = document.querySelector(`.god-root [data-panel="${name}"]`)
    if (el) { el.focus(); lastPanel.value = name }
  })
}

const diffOpen = ref(null)

function closeDiff() {
  diffOpen.value = null
  nextTick(() => focusPanel(lastPanel.value))
}

function closeHelp() {
  helpOpen.value = false
  nextTick(() => focusPanel(lastPanel.value))
}

function onGlobalKey(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey || helpOpen.value || diffOpen.value) return
  const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(ev.target.tagName)
  if (typing) return
  const panel = ev.target.closest?.('[data-panel]')?.dataset.panel
  if (panel && panel !== 'command') lastPanel.value = panel

  if (PANELS[ev.key]) { ev.preventDefault(); focusPanel(PANELS[ev.key]) }
  else if (ev.key === ':' || ev.key === '`') { ev.preventDefault(); commandLine.value?.focus() }
  else if (ev.key === '?') { ev.preventDefault(); helpOpen.value = true }
  else if (ev.key === ',') stepRound(-1)
  else if (ev.key === '.') stepRound(1)
  else if (ev.key === 'L') goLive()
  else if (ev.key === 'Escape' && state.focus) setFocus(null)
}

// Listen on the window: focus falls back to <body> when the focused element
// is removed (a button that hides itself), and keys must keep working.
onMounted(() => window.addEventListener('keydown', onGlobalKey))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKey))

// Keys should work as soon as the page opens, without a click.
onMounted(() => nextTick(() => { if (simulationId.value) focusPanel('feed') }))
watch(simulationId, id => { if (id) nextTick(() => focusPanel('feed')) })
</script>

<style>
/* Shared look for every God View panel. Scoped by the .god-root class. */
.god-root {
  --g-bg: #0a0b0b;
  --g-panel: #101211;
  --g-panel2: #151817;
  --g-line: #2a2e2c;
  --g-line-soft: #1c1f1e;
  --g-ink: #c9ccc6;
  --g-ink-hi: #f2f3ee;
  --g-ink2: #969a93;
  --g-mute: #6c706a;
  --g-hover: #171a19;
  --g-picked: #1b2430;
  --g-sel: #2b3a4f;
  --g-good: #3fae6a;
  --g-warn: #d9a23a;
  --g-crit: #e5484d;
  /* categorical: stance (validated for the dark surface) */
  --g-st-supportive: #3987e5;
  --g-st-opposing: #d95926;
  --g-st-neutral: #2fa39a;
  --g-st-observer: #8f7fe0;
  --g-st-unknown: #555955;
  /* platforms in the volume chart: two inks, told apart by lightness */
  --g-plat-tw: #d4d6d0;
  --g-plat-rd: #7b7f79;
  --g-seq: #3987e5;

  position: fixed; inset: 0;
  display: flex; flex-direction: column;
  background: var(--g-bg); color: var(--g-ink);
  font-family: 'JetBrains Mono', 'Noto Sans SC', ui-monospace, monospace;
  font-size: 12px; line-height: 1.3;
  font-variant-ligatures: none;
}
.god-root ::-webkit-scrollbar { width: 8px; height: 8px; }
.god-root ::-webkit-scrollbar-track { background: var(--g-panel); }
.god-root ::-webkit-scrollbar-thumb { background: var(--g-line); }
.god-root ::-webkit-scrollbar-thumb:hover { background: var(--g-mute); }

.god-root .gp {
  display: flex; flex-direction: column; min-width: 0; min-height: 0;
  background: var(--g-panel); outline: 1px solid var(--g-line); outline-offset: -1px;
}
.god-root .gp:focus, .god-root .gp:focus-within { outline-color: var(--g-ink2); }
.god-root .gp:focus { outline-color: var(--g-ink-hi); }
.god-root .gp-head {
  flex: none; display: flex; align-items: center; gap: 8px; height: 24px; padding: 0 8px;
  border-bottom: 1px solid var(--g-line); white-space: nowrap; overflow: hidden;
}
.god-root .gp-key { color: var(--g-bg); background: var(--g-mute); padding: 0 4px; flex: none; }
.god-root .gp:focus .gp-key, .god-root .gp:focus-within .gp-key { background: var(--g-ink-hi); }
.god-root .gp-title { color: var(--g-ink-hi); text-transform: uppercase; letter-spacing: .04em; }
.god-root .gp-meta { color: var(--g-mute); overflow: hidden; text-overflow: ellipsis; }
.god-root .gp-spacer { flex: 1; }
.god-root .g-empty { padding: 14px 10px; color: var(--g-ink2); }
.god-root .g-link { background: none; border: 0; color: var(--g-ink-hi); font: inherit; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; padding: 0 2px; }
.god-root .g-link:focus-visible { outline: 1px solid var(--g-ink-hi); }
.god-root .g-input {
  background: var(--g-bg); color: var(--g-ink); border: 1px solid var(--g-line); height: 18px;
  font: inherit; font-size: 11px; padding: 0 4px; min-width: 0; border-radius: 0;
}
.god-root .g-input:focus { outline: 0; border-color: var(--g-ink-hi); }
.god-root .dot { display: inline-block; width: 7px; height: 7px; margin-right: 6px; background: var(--g-st-unknown); }
.god-root .st-supportive { background: var(--g-st-supportive); }
.god-root .st-opposing { background: var(--g-st-opposing); }
.god-root .st-neutral { background: var(--g-st-neutral); }
.god-root .st-observer { background: var(--g-st-observer); }
.god-root .st-unknown { background: var(--g-st-unknown); }
</style>

<style scoped>
.statusbar {
  flex: none; display: flex; align-items: center; gap: 14px; height: 26px; padding: 0 8px;
  border-bottom: 1px solid var(--g-line); white-space: nowrap; overflow: hidden;
}
.brand { background: none; border: 0; color: var(--g-ink-hi); font: inherit; font-weight: 700; letter-spacing: .08em; cursor: pointer; padding: 0; }
.sep { color: var(--g-mute); margin: 0 -8px; }
.hi { color: var(--g-ink-hi); }
.cell { display: inline-flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
.k { color: var(--g-mute); text-transform: uppercase; }
.k2 { margin-left: 6px; }
.lamp { width: 7px; height: 7px; border-radius: 50%; background: var(--g-mute); }
.conn-live .lamp { background: var(--g-good); }
.conn-live { color: var(--g-good); }
.conn-connecting .lamp { background: var(--g-warn); }
.conn-reconnecting, .conn-notfound { color: var(--g-crit); }
.conn-reconnecting .lamp, .conn-notfound .lamp { background: var(--g-crit); }
.focus { color: var(--g-warn); }
.banner { flex: none; padding: 4px 8px; display: flex; gap: 12px; align-items: center; }
.banner.crit { background: var(--g-crit); color: #fff; }
.banner.crit .g-link { color: #fff; }
.banner.warn { background: var(--g-warn); color: #111; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }

.grid { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.upper { flex: 1; min-height: 0; display: flex; }
.left { flex: none; min-width: 0; display: flex; flex-direction: column; }
.right-top { flex: none; min-height: 0; display: flex; gap: 5px; }
.right-top > * { min-width: 0; }
.right { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.clock { background: var(--g-warn); color: #111; padding: 0 6px; }
.fill { flex: 1; }
.timeline-row { flex: none; height: 38px; }
.split { flex: none; background: var(--g-bg); }
.split.v { width: 5px; cursor: col-resize; }
.split.h { height: 5px; cursor: row-resize; }
.split:hover, .split:focus { background: var(--g-ink2); outline: 0; }

.picker { flex: 1; overflow-y: auto; padding: 24px 16px; max-width: 900px; }
.picker h2 { font-size: inherit; font-weight: 400; color: var(--g-mute); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 8px; }
.picker ul { list-style: none; }
.picker li button {
  display: grid; grid-template-columns: 2fr 1fr 1fr 1.4fr; gap: 16px; width: 100%; text-align: left;
  background: none; border: 0; border-bottom: 1px solid var(--g-line-soft); color: var(--g-ink);
  font: inherit; line-height: 24px; padding: 0 8px; cursor: pointer;
}
.picker li button:hover, .picker li button:focus { background: var(--g-sel); outline: 0; }
.dim { color: var(--g-mute); }
</style>
