<template>
  <section
    ref="root"
    class="gp feed"
    tabindex="0"
    data-panel="feed"
    :aria-label="$t('god.feed.title')"
    @keydown="onKey"
  >
    <header class="gp-head">
      <span class="gp-key">1</span>
      <span class="gp-title">{{ $t('god.feed.title') }}</span>
      <span class="gp-meta">{{ $t('god.feed.count', { shown: list.length, total: scopedEvents.length }) }}</span>
      <span class="gp-spacer"></span>
      <select v-model="state.filters.platform" class="g-input" :aria-label="$t('god.feed.platform')">
        <option value="all">{{ $t('god.feed.allPlatforms') }}</option>
        <option value="twitter">twitter</option>
        <option value="reddit">reddit</option>
      </select>
      <select v-model="state.filters.actionType" class="g-input" :aria-label="$t('god.feed.actionType')">
        <option value="all">{{ $t('god.feed.allTypes') }}</option>
        <option v-for="t in actionTypes" :key="t" :value="t">{{ t }}</option>
      </select>
      <input
        ref="keywordInput"
        v-model="state.filters.keyword"
        class="g-input kw"
        type="search"
        :placeholder="$t('god.feed.keyword')"
        :aria-label="$t('god.feed.keyword')"
        @keydown.esc.stop="leaveKeyword"
        @keydown.enter.stop="leaveKeyword"
      />
    </header>

    <div ref="scroller" class="rows" @scroll="onScroll">
      <div v-if="!list.length" class="g-empty">
        <template v-if="state.conn === 'connecting'">{{ $t('god.state.connecting') }}</template>
        <template v-else-if="scopedEvents.length">{{ $t('god.feed.noMatch') }}</template>
        <template v-else-if="state.focus">{{ $t('god.feed.noFocusMatch', { focus: state.focus.label }) }}</template>
        <template v-else>{{ $t('god.feed.empty') }}</template>
      </div>
      <div v-else :style="{ height: list.length * ROW + 'px', position: 'relative' }">
        <div
          v-for="row in windowRows"
          :key="row.e.key"
          class="row"
          :class="{ sel: row.i === cursorIndex, picked: row.e.agent_id === state.selectedAgentId }"
          :style="{ transform: `translateY(${row.i * ROW}px)` }"
          @click="pick(row.i)"
          @dblclick="selectAgent(row.e.agent_id)"
        >
          <span class="c-round">R{{ String(row.e.round).padStart(3, '0') }}</span>
          <span class="c-time">{{ row.e.timestamp.slice(11, 19) }}</span>
          <span class="c-plat" :class="row.e.platform">{{ row.e.platform === 'twitter' ? 'TW' : 'RD' }}</span>
          <span class="c-agent"><i class="dot" :class="'st-' + stanceOf(row.e)"></i>{{ row.e.agent_name }}</span>
          <span class="c-type">{{ row.e.action_type }}</span>
          <span class="c-text">
            <span v-if="isInjected(row.e)" class="flag">{{ $t('god.feed.injected') }}</span>
            <template v-if="eventText(row.e)">{{ eventText(row.e) }}</template>
            <span v-if="eventTargetName(row.e)" class="target"> → {{ eventTargetName(row.e) }}</span>
            <span v-if="!eventText(row.e) && eventTargetText(row.e)" class="quoted"> “{{ eventTargetText(row.e) }}”</span>
          </span>
        </div>
      </div>
    </div>

    <button v-if="unseen > 0" class="newer" @click="toTop">{{ $t('god.feed.newer', { n: unseen }) }}</button>

    <footer v-if="current" class="expand">
      <div class="expand-head">
        <span>R{{ current.round }} · {{ current.platform }} · {{ current.action_type }}</span>
        <button class="g-link" @click="selectAgent(current.agent_id)">{{ current.agent_name }} ⏎</button>
      </div>
      <p v-if="eventText(current)">{{ eventText(current) }}</p>
      <p v-if="eventTargetText(current)" class="quoted">
        {{ $t('god.feed.inReplyTo', { name: eventTargetName(current) || '?' }) }} “{{ eventTargetText(current) }}”
      </p>
      <p v-else-if="eventTargetName(current)" class="quoted">→ {{ eventTargetName(current) }}</p>
    </footer>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import {
  state, feedEvents, scopedEvents, actionTypes, getAgent, selectAgent, isInjected,
  eventText, eventTargetName, eventTargetText
} from '../../store/godTerminal'

const ROW = 20
const OVERSCAN = 8

const root = ref(null)
const scroller = ref(null)
const keywordInput = ref(null)
const scrollTop = ref(0)
const viewHeight = ref(300)
const cursorKey = ref(null)
const unseen = ref(0)

// Newest first: row i shows the i-th event from the end.
const list = feedEvents
const at = i => list.value[list.value.length - 1 - i]

const windowRows = computed(() => {
  const n = list.value.length
  const first = Math.max(0, Math.floor(scrollTop.value / ROW) - OVERSCAN)
  const last = Math.min(n, Math.ceil((scrollTop.value + viewHeight.value) / ROW) + OVERSCAN)
  const rows = []
  for (let i = first; i < last; i++) rows.push({ i, e: at(i) })
  return rows
})

const cursorIndex = computed(() => {
  if (cursorKey.value === null) return -1
  const arr = list.value
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i].key === cursorKey.value) return arr.length - 1 - i
  }
  return -1
})
const current = computed(() => (cursorIndex.value >= 0 ? at(cursorIndex.value) : null))

const stanceOf = e => getAgent(e.agent_id)?.stance || 'unknown'

function onScroll() {
  scrollTop.value = scroller.value.scrollTop
  if (scrollTop.value < ROW) unseen.value = 0
}

// Keep the reader's place when new events arrive above the viewport.
watch(() => list.value.length, (n, old) => {
  const el = scroller.value
  if (!el || n <= old || el.scrollTop < ROW) return
  const added = n - old
  unseen.value += added
  nextTick(() => { el.scrollTop += added * ROW })
})
// A different filter, focus or scrub position is a different list: go to the top.
watch(
  () => [state.filters.platform, state.filters.actionType, state.filters.keyword, state.focus, state.scrubRound === null],
  () => nextTick(toTop)
)

function toTop() {
  unseen.value = 0
  if (scroller.value) scroller.value.scrollTop = 0
}

function pick(i) {
  const e = at(i)
  if (e) cursorKey.value = e.key
}

function move(delta) {
  const n = list.value.length
  if (!n) return
  const next = Math.max(0, Math.min(n - 1, (cursorIndex.value < 0 ? (delta > 0 ? -1 : 0) : cursorIndex.value) + delta))
  pick(next)
  const el = scroller.value
  const top = next * ROW
  if (top < el.scrollTop) el.scrollTop = top
  else if (top + ROW > el.scrollTop + el.clientHeight) el.scrollTop = top + ROW - el.clientHeight
}

function leaveKeyword() {
  root.value.focus()
}

function cycle(key, options) {
  const i = options.indexOf(state.filters[key])
  state.filters[key] = options[(i + 1) % options.length]
}

function onKey(ev) {
  if (ev.target !== root.value || ev.ctrlKey || ev.metaKey || ev.altKey) return
  const page = Math.max(1, Math.floor(viewHeight.value / ROW) - 1)
  const handlers = {
    j: () => move(1), ArrowDown: () => move(1),
    k: () => move(-1), ArrowUp: () => move(-1),
    PageDown: () => move(page), PageUp: () => move(-page),
    g: () => { toTop(); pick(0) }, Home: () => { toTop(); pick(0) },
    G: () => move(list.value.length), End: () => move(list.value.length),
    Enter: () => current.value && selectAgent(current.value.agent_id),
    f: () => keywordInput.value.focus(),
    p: () => cycle('platform', ['all', 'twitter', 'reddit']),
    t: () => cycle('actionType', ['all', ...actionTypes.value]),
    x: () => { state.filters.platform = 'all'; state.filters.actionType = 'all'; state.filters.keyword = '' }
  }
  const handler = handlers[ev.key]
  if (handler) { ev.preventDefault(); handler() }
}

let observer
onMounted(() => {
  observer = new ResizeObserver(() => { viewHeight.value = scroller.value.clientHeight })
  observer.observe(scroller.value)
})
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.feed { position: relative; }
.kw { width: 120px; }
.rows { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; }
.row {
  position: absolute; left: 0; right: 0; top: 0;
  height: 20px; line-height: 20px;
  display: flex; gap: 8px; padding: 0 8px;
  white-space: nowrap; cursor: default;
}
.row:hover { background: var(--g-hover); }
.row.picked { background: var(--g-picked); }
.row.sel { background: var(--g-sel); color: var(--g-ink-hi); }
.c-round, .c-time { color: var(--g-mute); flex: none; }
.c-plat { flex: none; width: 18px; color: var(--g-ink2); }
.c-agent { flex: none; width: 150px; overflow: hidden; text-overflow: ellipsis; }
.c-type { flex: none; width: 118px; color: var(--g-ink2); overflow: hidden; text-overflow: ellipsis; }
.c-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.target, .quoted { color: var(--g-mute); }
.flag { background: var(--g-warn); color: #111; padding: 0 4px; margin-right: 6px; }
.newer {
  position: absolute; top: 30px; left: 50%; transform: translateX(-50%);
  background: var(--g-ink-hi); color: var(--g-bg); border: 0; padding: 2px 10px;
  font: inherit; cursor: pointer;
}
.expand {
  flex: none; max-height: 34%; overflow-y: auto;
  border-top: 1px solid var(--g-line); padding: 6px 8px; background: var(--g-panel2);
}
.expand-head { display: flex; justify-content: space-between; color: var(--g-mute); margin-bottom: 4px; }
.expand p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.45; margin-bottom: 4px; }
.expand p.quoted { color: var(--g-ink2); }
</style>
