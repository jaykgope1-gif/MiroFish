<template>
  <div class="veil" @click.self="$emit('close')">
    <div ref="dialog" class="sheet" role="dialog" aria-modal="true" :aria-label="$t('god.help.title')" tabindex="-1" @keydown.esc.stop="$emit('close')">
      <header>
        <span>{{ $t('god.help.title') }}</span>
        <button class="g-link" @click="$emit('close')">esc</button>
      </header>
      <div class="cols">
        <section v-for="group in GROUPS" :key="group.title">
          <h3>{{ $t(group.title) }}</h3>
          <dl>
            <div v-for="row in group.rows" :key="row.keys">
              <dt><kbd v-for="k in row.keys.split(' ')" :key="k">{{ k }}</kbd></dt>
              <dd>{{ $t(row.text) }}</dd>
            </div>
          </dl>
        </section>
        <section>
          <h3>{{ $t('god.help.commands') }}</h3>
          <dl class="commands">
            <div v-for="c in ready" :key="c.name"><dt>{{ c.usage }}</dt><dd>{{ $t('god.help.cmd.' + c.name) }}</dd></div>
          </dl>
          <h3>{{ $t('god.help.godCommands') }}</h3>
          <dl class="commands">
            <div v-for="c in god" :key="c.name"><dt>{{ c.usage }}</dt><dd>{{ $t('god.help.cmd.' + c.name) }}</dd></div>
          </dl>
          <template v-if="pending.length">
            <h3>{{ $t('god.help.pendingCommands') }}</h3>
            <dl class="commands pending">
              <div v-for="c in pending" :key="c.name"><dt>{{ c.usage }}</dt><dd>{{ $t('god.help.cmd.' + c.name) }}</dd></div>
            </dl>
          </template>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { COMMANDS } from './godCommands'

defineEmits(['close'])

const GROUPS = [
  {
    title: 'god.help.global',
    rows: [
      { keys: '1 2 3 4 5 6 7', text: 'god.help.k.panels' },
      { keys: ': `', text: 'god.help.k.command' },
      { keys: ', .', text: 'god.help.k.stepRound' },
      { keys: 'L', text: 'god.help.k.live' },
      { keys: 'Esc', text: 'god.help.k.esc' },
      { keys: '?', text: 'god.help.k.help' }
    ]
  },
  {
    title: 'god.help.feedRoster',
    rows: [
      { keys: 'j k ↑ ↓', text: 'god.help.k.move' },
      { keys: 'g G', text: 'god.help.k.ends' },
      { keys: 'Enter', text: 'god.help.k.select' },
      { keys: 'f', text: 'god.help.k.keyword' },
      { keys: 'p t x', text: 'god.help.k.cycle' },
      { keys: 's S', text: 'god.help.k.sort' },
      { keys: 'c 0', text: 'god.help.k.graph' }
    ]
  },
  {
    title: 'god.help.time',
    rows: [
      { keys: '← →', text: 'god.help.k.scrub' },
      { keys: 'Space', text: 'god.help.k.replay' },
      { keys: 'Home End', text: 'god.help.k.homeEnd' },
      { keys: 'v', text: 'god.help.k.table' },
      { keys: 'Tab', text: 'god.help.k.tab' },
      { keys: '↑ ↓', text: 'god.help.k.history' }
    ]
  }
]

const ready = COMMANDS.filter(c => !c.pending && !c.god)
const god = COMMANDS.filter(c => c.god)
const pending = COMMANDS.filter(c => c.pending)

const dialog = ref(null)
onMounted(() => dialog.value.focus())
</script>

<style scoped>
.veil { position: absolute; inset: 0; z-index: 50; background: rgba(0, 0, 0, .6); display: flex; align-items: center; justify-content: center; padding: 16px; }
.sheet { background: var(--g-bg); border: 1px solid var(--g-ink2); max-width: 1100px; width: 100%; max-height: 100%; overflow-y: auto; outline: 0; }
header { display: flex; justify-content: space-between; padding: 6px 12px; border-bottom: 1px solid var(--g-line); color: var(--g-ink-hi); text-transform: uppercase; letter-spacing: .04em; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 4px 24px; padding: 8px 12px 12px; }
.cols > section:last-child { grid-column: 1 / -1; }
h3 { font-size: inherit; font-weight: 400; color: var(--g-mute); text-transform: uppercase; letter-spacing: .04em; margin: 8px 0 4px; }
dl > div { display: flex; gap: 12px; line-height: 20px; }
dt { flex: none; width: 110px; white-space: nowrap; }
dd { color: var(--g-ink2); }
kbd { font: inherit; border: 1px solid var(--g-line); padding: 0 4px; margin-right: 3px; color: var(--g-ink-hi); }
.commands { columns: 2 460px; column-gap: 24px; }
.commands > div { break-inside: avoid; }
.commands dt { width: 330px; color: var(--g-ink-hi); overflow: hidden; text-overflow: ellipsis; }
.commands.pending dt { color: var(--g-mute); }
</style>
