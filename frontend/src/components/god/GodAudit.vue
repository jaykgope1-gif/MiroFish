<template>
  <section
    ref="root"
    class="gp audit"
    tabindex="0"
    data-panel="audit"
    :aria-label="$t('god.audit.title')"
    @keydown="onKey"
  >
    <header class="gp-head">
      <span class="gp-key">6</span>
      <span class="gp-title">{{ $t('god.audit.title') }}</span>
      <span class="gp-meta">{{ $t('god.audit.count', { n: rows.length }) }}</span>
    </header>

    <div v-if="!rows.length" class="g-empty">{{ $t('god.audit.empty') }}</div>
    <div v-else class="body">
      <ol class="rows">
        <li
          v-for="(e, i) in rows"
          :key="e.id"
          :ref="el => { if (i === cursor) cursorEl = el }"
          :class="{ sel: i === cursor, failed: !e.ok }"
          @click="cursor = i"
        >
          <span class="c-round">R{{ String(e.round).padStart(3, '0') }}</span>
          <span class="c-time">{{ e.timestamp.slice(11, 19) }}</span>
          <span class="c-cmd">{{ e.command }}</span>
          <span class="c-ok">{{ e.ok ? 'ok' : $t('god.audit.failed') }}</span>
          <span class="c-sum">{{ e.summary }}</span>
        </li>
      </ol>

      <div v-if="current" class="result">
        <div class="result-head">
          R{{ current.round }} · {{ current.timestamp.slice(0, 19).replace('T', ' ') }} · {{ current.command }}
          <button class="g-link" @click="scrubTo(current.round)">{{ $t('god.audit.goto') }}</button>
        </div>
        <p v-if="!current.ok" class="error">{{ current.summary }}</p>

        <template v-if="current.command === 'poll' && current.result?.counts">
          <p class="q">{{ current.result.question }}</p>
          <table class="tally">
            <tr v-for="(count, option) in current.result.counts" :key="option">
              <th>{{ option }}</th>
              <td class="bar"><i :style="{ width: (count / pollMax) * 100 + '%' }"></i></td>
              <td class="n">{{ count }}</td>
            </tr>
          </table>
          <ul class="answers">
            <li v-for="a in current.result.answers" :key="a.agent_id">
              <button class="g-link" @click="selectAgent(a.agent_id)">{{ a.agent_name }}</button>
              <span class="choice">{{ a.choice || '?' }}</span>
              <span>{{ a.response || a.error }}</span>
            </li>
          </ul>
        </template>

        <template v-else-if="current.result?.platforms">
          <p v-if="current.result.question" class="q">{{ current.result.question }}</p>
          <p v-if="current.result.content" class="q">{{ current.result.content }}</p>
          <p v-if="current.result.text" class="q">{{ current.result.text }}</p>
          <div v-for="(r, platform) in current.result.platforms" :key="platform" class="plat">
            <span class="plat-name">{{ platform }}</span>
            <span v-if="r.error" class="error">{{ r.error }}</span>
            <span v-else-if="r.response !== undefined">{{ r.response }}</span>
            <span v-else class="dim">{{ $t('god.audit.done') }}</span>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { auditLog, scrubTo, selectAgent } from '../../store/godTerminal'

const root = ref(null)
const cursor = ref(0)
let cursorEl = null

// Newest first.
const rows = computed(() => auditLog.value.slice().reverse())
const current = computed(() => rows.value[cursor.value] || null)
const pollMax = computed(() => Math.max(1, ...Object.values(current.value?.result?.counts || {})))

// A new entry arrives at the top: keep the cursor on it if it was at the top.
watch(() => rows.value.length, (n, old) => {
  if (cursor.value > 0 && n > old) cursor.value += n - old
  if (cursor.value >= n) cursor.value = Math.max(0, n - 1)
})

function move(delta) {
  const n = rows.value.length
  if (!n) return
  cursor.value = Math.max(0, Math.min(n - 1, cursor.value + delta))
  nextTick(() => cursorEl?.scrollIntoView({ block: 'nearest' }))
}

function onKey(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return
  const handlers = {
    j: () => move(1), ArrowDown: () => move(1),
    k: () => move(-1), ArrowUp: () => move(-1),
    g: () => move(-rows.value.length), G: () => move(rows.value.length),
    Enter: () => current.value && scrubTo(current.value.round)
  }
  const handler = handlers[ev.key]
  if (handler) { ev.preventDefault(); handler() }
}
</script>

<style scoped>
.body { flex: 1; min-height: 0; display: flex; }
.rows { flex: 1 1 56%; min-width: 0; overflow-y: auto; list-style: none; }
.rows li { display: flex; gap: 8px; height: 20px; line-height: 20px; padding: 0 8px; white-space: nowrap; cursor: default; }
.rows li:hover { background: var(--g-hover); }
.rows li.sel { background: var(--g-sel); color: var(--g-ink-hi); }
.c-round, .c-time { color: var(--g-mute); flex: none; }
.c-cmd { flex: none; width: 68px; color: var(--g-ink-hi); }
.c-ok { flex: none; width: 44px; color: var(--g-good); }
.failed .c-ok { color: var(--g-crit); }
.c-sum { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.result { flex: 1 1 44%; min-width: 0; overflow-y: auto; border-left: 1px solid var(--g-line); padding: 4px 8px 8px; background: var(--g-panel2); line-height: 1.45; overflow-wrap: anywhere; }
.result-head { display: flex; justify-content: space-between; gap: 8px; color: var(--g-mute); margin-bottom: 4px; }
.q { color: var(--g-ink-hi); margin-bottom: 4px; }
.error { color: var(--g-crit); }
.dim { color: var(--g-mute); }
.plat { margin-top: 3px; }
.plat-name { color: var(--g-mute); margin-right: 8px; }
.tally { border-collapse: collapse; width: 100%; margin: 4px 0; }
.tally th { text-align: left; font-weight: 400; padding-right: 8px; white-space: nowrap; width: 1%; }
.tally .bar { width: auto; }
.tally .bar i { display: block; height: 8px; background: var(--g-seq); min-width: 1px; }
.tally .n { text-align: right; padding-left: 8px; width: 1%; font-variant-numeric: tabular-nums; color: var(--g-ink-hi); }
.answers { list-style: none; margin-top: 4px; }
.answers li { padding: 2px 0; border-top: 1px solid var(--g-line-soft); }
.choice { color: var(--g-ink-hi); margin: 0 8px; }
</style>
