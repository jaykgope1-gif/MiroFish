<template>
  <section
    ref="root"
    class="gp roster"
    tabindex="0"
    data-panel="roster"
    :aria-label="$t('god.roster.title')"
    @keydown="onKey"
  >
    <header class="gp-head">
      <span class="gp-key">2</span>
      <span class="gp-title">{{ $t('god.roster.title') }}</span>
      <span class="gp-meta">{{ $t('god.roster.count', { shown: rows.length, total: agents.length }) }}</span>
      <span class="gp-spacer"></span>
      <span class="gp-meta">{{ $t('god.roster.graphHint') }}</span>
    </header>

    <div v-if="state.metaLoading" class="g-empty">{{ $t('god.state.loadingAgents') }}</div>
    <div v-else-if="state.metaError" class="g-empty">
      {{ $t('god.state.metaError', { error: state.metaError }) }}
      <button class="g-link" @click="retryMeta">{{ $t('god.state.retry') }}</button>
    </div>
    <div v-else-if="!agents.length" class="g-empty">{{ $t('god.roster.empty') }}</div>
    <div v-else ref="scroller" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th
              v-for="col in COLUMNS"
              :key="col.key"
              :class="[col.cls, { sorted: sortKey === col.key }]"
              :aria-sort="sortKey === col.key ? (sortDir > 0 ? 'ascending' : 'descending') : 'none'"
              :title="col.hint ? $t(col.hint) : null"
            >
              <button @click="sortBy(col.key)">
                {{ $t(col.label) }}<span v-if="sortKey === col.key">{{ sortDir > 0 ? ' ▲' : ' ▼' }}</span>
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, i) in rows"
            :key="row.id"
            :ref="el => { if (i === cursor) cursorEl = el }"
            :class="{ sel: i === cursor, picked: row.id === state.selectedAgentId }"
            @click="choose(i)"
          >
            <td class="num">{{ row.id }}</td>
            <td class="name">{{ row.name }}</td>
            <td class="type">{{ row.type }}</td>
            <td class="stance"><i class="dot" :class="'st-' + (row.stance || 'unknown')"></i>{{ row.stance || '—' }}</td>
            <td class="num">{{ row.activity }}</td>
            <td class="num">{{ row.reach }}</td>
            <td class="num">{{ row.influenceWeight ?? '—' }}</td>
            <td class="persona">{{ row.bio }}</td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="g-empty">{{ $t('god.roster.noneInFocus') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { state, agents, agentStats, selectAgent, retryMeta } from '../../store/godTerminal'

const COLUMNS = [
  { key: 'id', label: 'god.roster.colId', cls: 'num' },
  { key: 'name', label: 'god.roster.colName' },
  { key: 'type', label: 'god.roster.colType' },
  { key: 'stance', label: 'god.roster.colStance' },
  { key: 'activity', label: 'god.roster.colActivity', cls: 'num', hint: 'god.roster.hintActivity' },
  { key: 'reach', label: 'god.roster.colReach', cls: 'num', hint: 'god.roster.hintReach' },
  { key: 'influenceWeight', label: 'god.roster.colInfluence', cls: 'num', hint: 'god.roster.hintInfluence' },
  { key: 'bio', label: 'god.roster.colPersona' }
]

const root = ref(null)
const sortKey = ref('activity')
const sortDir = ref(-1)
const cursor = ref(0)
let cursorEl = null

const rows = computed(() => {
  const stats = agentStats.value
  let list = agents.value.map(a => {
    const s = stats.get(a.id)
    return { ...a, activity: s?.activity || 0, reach: s?.reach || 0 }
  })
  // With a focus set, only show agents that take part in the focused subject.
  if (state.focus) list = list.filter(a => stats.has(a.id))
  const key = sortKey.value
  const dir = sortDir.value
  return list.sort((a, b) => {
    const x = a[key] ?? ''
    const y = b[key] ?? ''
    const cmp = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
    return cmp * dir || a.id - b.id
  })
})

function sortBy(key) {
  if (sortKey.value === key) sortDir.value = -sortDir.value
  else {
    sortKey.value = key
    sortDir.value = ['activity', 'reach', 'influenceWeight'].includes(key) ? -1 : 1
  }
}

function choose(i) {
  cursor.value = i
  const row = rows.value[i]
  if (row) selectAgent(row.id)
}

function move(delta) {
  const n = rows.value.length
  if (!n) return
  cursor.value = Math.max(0, Math.min(n - 1, cursor.value + delta))
  nextTick(() => cursorEl?.scrollIntoView({ block: 'nearest' }))
}

// Follow selections made elsewhere (feed, command line).
watch(() => [state.selectedAgentId, rows.value], () => {
  const i = rows.value.findIndex(r => r.id === state.selectedAgentId)
  if (i >= 0 && i !== cursor.value) {
    cursor.value = i
    nextTick(() => cursorEl?.scrollIntoView({ block: 'nearest' }))
  }
})

function onKey(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return
  const handlers = {
    j: () => move(1), ArrowDown: () => move(1),
    k: () => move(-1), ArrowUp: () => move(-1),
    g: () => move(-rows.value.length), Home: () => move(-rows.value.length),
    G: () => move(rows.value.length), End: () => move(rows.value.length),
    Enter: () => choose(cursor.value),
    s: () => {
      const i = COLUMNS.findIndex(c => c.key === sortKey.value)
      sortBy(COLUMNS[(i + 1) % COLUMNS.length].key)
    },
    S: () => { sortDir.value = -sortDir.value }
  }
  const handler = handlers[ev.key]
  if (handler) { ev.preventDefault(); handler() }
}
</script>

<style scoped>
.table-wrap { flex: 1; min-height: 0; overflow: auto; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { height: 20px; padding: 0 8px; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
thead th { position: sticky; top: 0; background: var(--g-panel2); border-bottom: 1px solid var(--g-line); font-weight: 400; z-index: 1; }
th button { all: unset; cursor: pointer; color: var(--g-mute); display: block; width: 100%; }
th.sorted button { color: var(--g-ink-hi); }
th button:focus-visible { outline: 1px solid var(--g-ink-hi); }
th:nth-child(1) { width: 40px; }
th:nth-child(2) { width: 140px; }
th:nth-child(3) { width: 110px; }
th:nth-child(4) { width: 100px; }
th:nth-child(5), th:nth-child(6), th:nth-child(7) { width: 52px; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
th.num button { text-align: right; }
td.type, td.persona { color: var(--g-ink2); }
tbody tr { cursor: default; scroll-margin-top: 22px; }
tbody tr:hover { background: var(--g-hover); }
tbody tr.picked { background: var(--g-picked); }
tbody tr.sel { background: var(--g-sel); color: var(--g-ink-hi); }
</style>
