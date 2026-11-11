<template>
  <div class="veil" @click.self="$emit('close')">
    <div ref="dialog" class="sheet" role="dialog" aria-modal="true" :aria-label="$t('god.diff.title')" tabindex="-1" @keydown.esc.stop="$emit('close')">
      <header>
        <span>{{ $t('god.diff.title') }} · {{ a }} ↔ {{ b }}</span>
        <button class="g-link" @click="$emit('close')">esc</button>
      </header>

      <p v-if="loading" class="g-empty">{{ $t('god.diff.loading') }}</p>
      <p v-else-if="error" class="g-empty err">{{ error }}</p>
      <div v-else class="body">
        <p class="lead">
          {{ $t('god.diff.span', { from: d.diverged_at, to: d.compared_through }) }}
          <span v-if="d.note" class="warn">{{ d.note }}</span>
        </p>
        <p v-if="d.compared_through < d.diverged_at" class="g-empty">{{ $t('god.diff.tooEarly') }}</p>

        <template v-else>
          <div class="cols">
            <section>
              <h3>{{ $t('god.diff.totals') }}</h3>
              <table>
                <thead><tr><th></th><th class="n">{{ d.a.name }}</th><th class="n">{{ d.b.name }}</th><th class="n">Δ</th></tr></thead>
                <tbody>
                  <tr><th>{{ $t('god.diff.actions') }}</th><td class="n">{{ d.a.totals.actions }}</td><td class="n">{{ d.b.totals.actions }}</td><td class="n" v-html="delta(d.a.totals.actions, d.b.totals.actions)"></td></tr>
                  <tr v-for="s in STANCES" :key="s">
                    <th><i class="dot" :class="'st-' + s"></i>{{ s }}</th>
                    <td class="n">{{ share(d.a.totals, s) }}</td><td class="n">{{ share(d.b.totals, s) }}</td>
                    <td class="n" v-html="deltaPts(d.a.totals, d.b.totals, s)"></td>
                  </tr>
                </tbody>
              </table>
              <h3>{{ $t('god.diff.topics') }}</h3>
              <table>
                <tbody>
                  <tr v-for="t in d.topics" :key="t">
                    <th>{{ t }}</th><td class="n">{{ d.a.by_topic[t] || 0 }}</td><td class="n">{{ d.b.by_topic[t] || 0 }}</td>
                    <td class="n" v-html="delta(d.a.by_topic[t] || 0, d.b.by_topic[t] || 0)"></td>
                  </tr>
                  <tr v-if="!d.topics.length"><td class="dim">{{ $t('god.pulse.noTopics') }}</td></tr>
                </tbody>
              </table>
            </section>

            <section>
              <h3>{{ $t('god.diff.agents') }}</h3>
              <table>
                <thead><tr><th></th><th class="n">{{ d.a.name }}</th><th class="n">{{ d.b.name }}</th><th class="n">Δ</th></tr></thead>
                <tbody>
                  <tr v-for="row in d.agents" :key="row.agent_id">
                    <th>{{ row.name }}</th><td class="n">{{ row.a }}</td><td class="n">{{ row.b }}</td><td class="n" v-html="delta(row.a, row.b)"></td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section>
              <h3>{{ $t('god.diff.interventions') }}</h3>
              <div v-for="side in [d.a, d.b]" :key="side.name" class="side">
                <div class="side-name">{{ side.name }}</div>
                <div v-if="!side.interventions.length" class="dim">{{ $t('god.diff.none') }}</div>
                <div v-for="(e, i) in side.interventions" :key="i" class="iv">
                  <span class="dim">R{{ e.round }}</span> {{ e.command }} <span class="dim">{{ e.summary }}</span>
                </div>
              </div>
            </section>
          </div>

          <h3>{{ $t('god.diff.perRound') }}</h3>
          <table class="rounds">
            <thead>
              <tr>
                <th class="n">{{ $t('god.pulse.round') }}</th>
                <th class="n">{{ d.a.name }}</th><th class="n">{{ d.b.name }}</th><th class="n">Δ</th>
                <th>{{ $t('god.diff.stanceOf', { name: d.a.name }) }}</th>
                <th>{{ $t('god.diff.stanceOf', { name: d.b.name }) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in d.rounds" :key="r.round">
                <td class="n">{{ r.round }}</td><td class="n">{{ r.a.total }}</td><td class="n">{{ r.b.total }}</td>
                <td class="n" v-html="delta(r.a.total, r.b.total)"></td>
                <td v-for="k in ['a', 'b']" :key="k" class="bar" :title="stanceTitle(r[k])">
                  <i v-for="s in STANCES" :key="s" :class="'st-' + s" :style="{ width: pct(r[k], s) }"></i>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getBranchDiff } from '../../api/god'
import { state, STANCES } from '../../store/godTerminal'

const props = defineProps({ a: { type: String, required: true }, b: { type: String, required: true } })
defineEmits(['close'])

const dialog = ref(null)
const loading = ref(true)
const error = ref('')
const d = ref(null)

const sum = totals => STANCES.reduce((n, s) => n + (totals.stance[s] || 0), 0)
const shareOf = (totals, s) => (sum(totals) ? (totals.stance[s] / sum(totals)) * 100 : 0)
const share = (totals, s) => `${Math.round(shareOf(totals, s))}%`
const pct = (row, s) => `${row.total ? (row.stance[s] / row.total) * 100 : 0}%`
const stanceTitle = row => STANCES.map(s => `${s} ${row.stance[s]}`).join(' · ')

// Deltas are b minus a. The sign is written out so it does not rely on colour.
function signed(n, suffix = '') {
  if (!n) return `<span class="dim">0${suffix}</span>`
  return `<span class="${n > 0 ? 'up' : 'down'}">${n > 0 ? '+' : '−'}${Math.abs(n)}${suffix}</span>`
}
const delta = (x, y) => signed(y - x)
const deltaPts = (ta, tb, s) => signed(Math.round(shareOf(tb, s) - shareOf(ta, s)), 'pt')

onMounted(async () => {
  dialog.value.focus()
  try {
    d.value = (await getBranchDiff(state.simulationId, props.a, props.b)).data
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.veil { position: absolute; inset: 0; z-index: 50; background: rgba(0, 0, 0, .6); display: flex; align-items: center; justify-content: center; padding: 16px; }
.sheet { background: var(--g-bg); border: 1px solid var(--g-ink2); max-width: 1200px; width: 100%; max-height: 100%; overflow-y: auto; outline: 0; }
header { display: flex; justify-content: space-between; padding: 6px 12px; border-bottom: 1px solid var(--g-line); color: var(--g-ink-hi); text-transform: uppercase; letter-spacing: .04em; position: sticky; top: 0; background: var(--g-bg); }
.body { padding: 8px 12px 14px; }
.lead { color: var(--g-ink-hi); }
.warn { color: var(--g-warn); margin-left: 12px; }
.err { color: var(--g-crit); }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0 28px; }
h3 { font-size: inherit; font-weight: 400; color: var(--g-mute); text-transform: uppercase; letter-spacing: .04em; margin: 12px 0 4px; }
table { border-collapse: collapse; width: 100%; }
th, td { height: 20px; padding: 0 8px 0 0; text-align: left; font-weight: 400; white-space: nowrap; }
thead th { color: var(--g-mute); }
.n { text-align: right; font-variant-numeric: tabular-nums; }
.dim, :deep(.dim) { color: var(--g-mute); }
:deep(.up), :deep(.down) { color: var(--g-ink-hi); }
.side { margin-bottom: 6px; }
.side-name { color: var(--g-ink-hi); }
.iv { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rounds .bar { width: 28%; padding: 0 12px 0 8px; }
.rounds .bar i { display: inline-block; height: 9px; vertical-align: middle; }
</style>
