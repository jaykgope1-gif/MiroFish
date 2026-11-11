<template>
  <section class="cmd" data-panel="command">
    <ul v-if="suggestions.length" class="suggest" role="listbox">
      <li
        v-for="(s, i) in suggestions"
        :key="s.value"
        role="option"
        :aria-selected="i === suggestIndex"
        :class="{ on: i === suggestIndex, pending: s.pending }"
        @mousedown.prevent="accept(s)"
      >
        <span>{{ s.label }}</span>
        <span v-if="s.hint" class="hint">{{ s.hint }}</span>
      </li>
    </ul>

    <div v-if="log.length" class="log" aria-live="polite">
      <div v-for="entry in log" :key="entry.id" :class="entry.ok ? 'ok' : 'err'">
        <span class="echo">› {{ entry.line }}</span>
        <span v-if="entry.busy" class="msg busy">{{ $t('god.cmd.working') }}</span>
        <span v-else class="msg">{{ entry.ok ? '' : '✕ ' }}{{ entry.key ? $t(entry.key, entry.params || {}) : entry.text }}</span>
      </div>
    </div>

    <label class="prompt">
      <span class="ps1">god&gt;</span>
      <input
        ref="input"
        v-model="line"
        type="text"
        spellcheck="false"
        autocomplete="off"
        :placeholder="$t('god.cmd.placeholder')"
        :aria-label="$t('god.cmd.label')"
        @keydown="onKey"
        @blur="suggestIndex = -1; open = false"
        @focus="open = true"
        @input="open = true; suggestIndex = -1"
      />
    </label>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { agents } from '../../store/godTerminal'
import { COMMANDS, execute } from './godCommands'

const emit = defineEmits(['open-help', 'open-diff', 'open-simulation', 'leave'])
const { t } = useI18n()

const HISTORY_KEY = 'god.history'
const MAX_HISTORY = 100
const MAX_LOG = 3

const input = ref(null)
const line = ref('')
const open = ref(false)
const suggestIndex = ref(-1)
const log = ref([])
let logId = 0

let history = []
try { history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') } catch { history = [] }
let historyIndex = history.length
let draft = ''

const suggestions = computed(() => {
  if (!open.value) return []
  const text = line.value
  const space = text.indexOf(' ')
  if (space < 0) {
    const prefix = text.toLowerCase()
    if (!prefix) return []
    return COMMANDS.filter(c => c.name.startsWith(prefix)).map(c => ({
      value: c.name + (c.usage.includes(' ') ? ' ' : ''),
      label: c.usage,
      hint: c.pending ? t('god.cmd.pendingTag') : '',
      pending: c.pending
    }))
  }
  const command = COMMANDS.find(c => c.name === text.slice(0, space).toLowerCase())
  if (!command || command.arg !== 'agent') return []
  const rest = text.slice(space + 1).toLowerCase()
  // Only complete the first argument (the agent); stop once it is typed out.
  const exact = agents.value.some(a => rest.startsWith(a.name.toLowerCase() + ' '))
  if (exact) return []
  return agents.value
    .filter(a => a.name.toLowerCase().includes(rest) || String(a.id) === rest)
    .slice(0, 8)
    .map(a => ({ value: `${command.name} ${a.name} `, label: a.name, hint: `#${a.id} ${a.stance || ''}` }))
})

function accept(s) {
  line.value = s.value
  suggestIndex.value = -1
  input.value.focus()
}

function submit() {
  const text = line.value.trim()
  if (!text) return
  // Show the command at once; god commands can take as long as a round.
  const id = ++logId
  log.value = [...log.value, { id, line: text, ok: true, busy: true }].slice(-MAX_LOG)
  const ctx = {
    openHelp: () => emit('open-help'),
    openDiff: (a, b) => emit('open-diff', { a, b }),
    openSimulation: id => emit('open-simulation', id)
  }
  execute(text, ctx).then(result => {
    log.value = log.value.map(entry => (entry.id === id ? { id, line: text, ...result } : entry))
  })
  if (history[history.length - 1] !== text) {
    history.push(text)
    history = history.slice(-MAX_HISTORY)
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(history)) } catch { /* storage unavailable */ }
  }
  historyIndex = history.length
  line.value = ''
  open.value = false
}

function recall(delta) {
  if (!history.length) return
  if (historyIndex === history.length) draft = line.value
  historyIndex = Math.max(0, Math.min(history.length, historyIndex + delta))
  line.value = historyIndex === history.length ? draft : history[historyIndex]
  open.value = false
}

function onKey(ev) {
  const list = suggestions.value
  if (ev.key === 'Tab') {
    ev.preventDefault()
    if (!list.length) return
    if (list.length === 1) { accept(list[0]); return }
    suggestIndex.value = (suggestIndex.value + (ev.shiftKey ? -1 : 1) + list.length) % list.length
  } else if (ev.key === 'Enter') {
    ev.preventDefault()
    if (suggestIndex.value >= 0 && list[suggestIndex.value]) accept(list[suggestIndex.value])
    else submit()
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault()
    if (list.length && suggestIndex.value >= 0) suggestIndex.value = Math.max(0, suggestIndex.value - 1)
    else recall(-1)
  } else if (ev.key === 'ArrowDown') {
    ev.preventDefault()
    if (list.length && suggestIndex.value >= 0) suggestIndex.value = Math.min(list.length - 1, suggestIndex.value + 1)
    else recall(1)
  } else if (ev.key === 'Escape') {
    ev.preventDefault()
    if (open.value && list.length) open.value = false
    else if (line.value) line.value = ''
    else emit('leave')
  }
}

defineExpose({ focus: () => input.value?.focus() })
</script>

<style scoped>
.cmd { position: relative; flex: none; border-top: 1px solid var(--g-line); background: var(--g-panel); }
.prompt { display: flex; align-items: center; gap: 8px; height: 28px; padding: 0 8px; }
.ps1 { color: var(--g-ink-hi); flex: none; }
input { flex: 1; min-width: 0; background: none; border: 0; outline: 0; color: var(--g-ink-hi); font: inherit; caret-color: var(--g-ink-hi); }
input::placeholder { color: var(--g-mute); }
.cmd:focus-within { box-shadow: inset 0 1px 0 var(--g-ink-hi); }
.log { padding: 3px 8px 0; line-height: 17px; }
.log > div { display: flex; gap: 12px; white-space: nowrap; overflow: hidden; }
.echo { color: var(--g-mute); flex: none; max-width: 45%; overflow: hidden; text-overflow: ellipsis; }
.msg { overflow: hidden; text-overflow: ellipsis; }
.err .msg { color: var(--g-crit); }
.msg.busy { color: var(--g-warn); }
.suggest {
  position: absolute; left: 44px; bottom: 100%; z-index: 20; list-style: none; min-width: 320px; max-width: 70vw;
  background: var(--g-bg); border: 1px solid var(--g-ink2);
}
.suggest li { display: flex; justify-content: space-between; gap: 24px; padding: 0 8px; line-height: 20px; cursor: pointer; white-space: nowrap; }
.suggest li.on { background: var(--g-sel); color: var(--g-ink-hi); }
.suggest li.pending { color: var(--g-mute); }
.hint { color: var(--g-mute); }
</style>
