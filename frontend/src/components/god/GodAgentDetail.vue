<template>
  <section
    class="gp detail"
    tabindex="0"
    data-panel="detail"
    :aria-label="$t('god.detail.title')"
  >
    <header class="gp-head">
      <span class="gp-key">3</span>
      <span class="gp-title">{{ $t('god.detail.title') }}</span>
      <span v-if="agent" class="gp-meta">#{{ agent.id }} {{ agent.name }}</span>
      <span class="gp-spacer"></span>
      <button v-if="agent" class="g-link" @click="setFocus(String(agent.id))">{{ $t('god.detail.focus') }}</button>
    </header>

    <div v-if="!agent" class="g-empty">{{ $t('god.detail.empty') }}</div>
    <div v-else class="body">
      <dl class="facts">
        <div><dt>{{ $t('god.roster.colType') }}</dt><dd>{{ agent.type || '—' }}</dd></div>
        <div><dt>{{ $t('god.roster.colStance') }}</dt><dd><i class="dot" :class="'st-' + (agent.stance || 'unknown')"></i>{{ agent.stance || '—' }}</dd></div>
        <div><dt>{{ $t('god.detail.sentimentBias') }}</dt><dd>{{ agent.sentimentBias ?? '—' }}</dd></div>
        <div><dt>{{ $t('god.roster.colInfluence') }}</dt><dd>{{ agent.influenceWeight ?? '—' }}</dd></div>
        <div><dt>{{ $t('god.detail.activityLevel') }}</dt><dd>{{ agent.activityLevel == null ? '—' : Math.round(agent.activityLevel * 100) / 100 }}</dd></div>
        <div><dt>{{ $t('god.roster.colActivity') }}</dt><dd>{{ stats.activity }}</dd></div>
        <div><dt>{{ $t('god.roster.colReach') }}</dt><dd>{{ stats.reach }}</dd></div>
        <div><dt>{{ $t('god.detail.username') }}</dt><dd>{{ agent.username || '—' }}</dd></div>
        <div v-for="f in extraFacts" :key="f.k"><dt>{{ f.k }}</dt><dd>{{ f.v }}</dd></div>
        <div><dt>{{ $t('god.detail.activeHours') }}</dt><dd>{{ hours }}</dd></div>
        <div><dt>{{ $t('god.detail.entity') }}</dt><dd>{{ agent.entityUuid || '—' }}</dd></div>
      </dl>

      <h3>{{ $t('god.detail.bio') }}</h3>
      <p>{{ agent.bio || '—' }}</p>
      <h3>{{ $t('god.detail.persona') }}</h3>
      <p>{{ agent.persona || '—' }}</p>

      <h3>
        {{ $t('god.detail.memory') }}
        <button v-if="clock !== 'off'" class="g-link" :disabled="memory.loading" @click="loadMemory">
          {{ memory.data ? $t('god.detail.memoryReload') : $t('god.detail.memoryLoad') }}
        </button>
      </h3>
      <p v-if="clock === 'off'" class="note">{{ $t('god.detail.memoryOff') }}</p>
      <p v-else-if="memory.loading" class="note">{{ $t('god.detail.memoryLoading') }}</p>
      <p v-else-if="memory.error" class="note err">{{ memory.error }}</p>
      <p v-else-if="!memory.data" class="note">{{ $t('god.detail.memoryHint') }}</p>
      <div v-else>
        <div v-for="(m, platform) in memory.data" :key="platform" class="mem">
          <div class="mem-head">{{ platform }} · {{ m.error || $t('god.detail.memoryCount', { n: m.total }) }}</div>
          <ol v-if="m.messages">
            <li v-for="(msg, i) in m.messages" :key="i"><span class="role">{{ msg.role }}</span>{{ msg.content }}</li>
          </ol>
        </div>
      </div>

      <h3>{{ $t('god.detail.history', { n: history.length, round: asOfRound }) }}</h3>
      <p v-if="!history.length" class="note">{{ $t('god.detail.noHistory') }}</p>
      <ol v-else class="history">
        <li v-for="e in shown" :key="e.key">
          <span class="h-meta">R{{ e.round }} {{ e.platform === 'twitter' ? 'TW' : 'RD' }} {{ e.action_type }}</span>
          <span v-if="eventTargetName(e)" class="h-target"> → {{ eventTargetName(e) }}</span>
          <div v-if="eventText(e)">{{ eventText(e) }}</div>
          <div v-else-if="eventTargetText(e)" class="h-quoted">“{{ eventTargetText(e) }}”</div>
        </li>
      </ol>
      <button v-if="history.length > limit" class="g-link" @click="limit += 200">
        {{ $t('god.detail.more', { n: history.length - limit }) }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { getAgentMemory } from '../../api/god'
import {
  state, getAgent, agentStats, scopedEvents, asOfRound, setFocus, clock,
  eventText, eventTargetName, eventTargetText
} from '../../store/godTerminal'

const limit = ref(200)
// Memory is read from the running simulation process on request; it is the
// agent's memory now, not as of the viewed round.
const memory = reactive({ loading: false, error: '', data: null })

watch(() => state.selectedAgentId, () => {
  limit.value = 200
  Object.assign(memory, { loading: false, error: '', data: null })
})

async function loadMemory() {
  const id = state.selectedAgentId
  Object.assign(memory, { loading: true, error: '' })
  try {
    const res = await getAgentMemory(state.simulationId, id)
    if (state.selectedAgentId === id) memory.data = res.data.platforms
  } catch (err) {
    if (state.selectedAgentId === id) memory.error = err.message || String(err)
  } finally {
    if (state.selectedAgentId === id) memory.loading = false
  }
}

const agent = computed(() => {
  state.version
  return state.selectedAgentId === null ? null : getAgent(state.selectedAgentId)
})
const stats = computed(() => agentStats.value.get(state.selectedAgentId) || { activity: 0, reach: 0 })

const extraFacts = computed(() => {
  const p = agent.value?.reddit || {}
  const tw = agent.value?.twitter || {}
  return [
    ['age', p.age], ['gender', p.gender], ['mbti', p.mbti], ['country', p.country],
    ['profession', p.profession], ['karma', p.karma],
    ['followers', tw.follower_count], ['topics', (p.interested_topics || []).join(', ')]
  ].filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => ({ k, v }))
})

const hours = computed(() => {
  const h = agent.value?.activeHours || []
  if (!h.length) return '—'
  if (h.length === 24) return '00–23'
  return h.join(' ')
})

// Newest first, as of the viewed round.
const history = computed(() => {
  const id = state.selectedAgentId
  const out = []
  const src = scopedEvents.value
  for (let i = src.length - 1; i >= 0; i--) if (src[i].agent_id === id) out.push(src[i])
  return out
})
const shown = computed(() => history.value.slice(0, limit.value))
</script>

<style scoped>
.body { flex: 1; min-height: 0; overflow-y: auto; padding: 6px 8px 10px; }
.facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 0 16px; }
.facts > div { display: flex; gap: 8px; min-width: 0; line-height: 18px; }
dt { color: var(--g-mute); flex: none; width: 92px; text-transform: lowercase; }
dd { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
h3 { font-size: inherit; font-weight: 400; color: var(--g-mute); text-transform: uppercase; margin: 10px 0 2px; letter-spacing: .04em; }
p { line-height: 1.45; overflow-wrap: anywhere; max-width: 100ch; }
.note { color: var(--g-ink2); }
.note.err { color: var(--g-crit); }
h3 .g-link { text-transform: none; margin-left: 8px; }
.mem-head { color: var(--g-mute); margin-top: 4px; }
.mem ol { list-style: none; max-height: 260px; overflow-y: auto; border-left: 1px solid var(--g-line); padding-left: 8px; }
.mem li { padding: 2px 0; line-height: 1.4; overflow-wrap: anywhere; white-space: pre-wrap; }
.role { color: var(--g-mute); margin-right: 8px; }
.history { list-style: none; }
.history li { padding: 3px 0; border-bottom: 1px solid var(--g-line-soft); line-height: 1.45; overflow-wrap: anywhere; }
.h-meta, .h-target { color: var(--g-mute); }
.h-quoted { color: var(--g-ink2); }
</style>
