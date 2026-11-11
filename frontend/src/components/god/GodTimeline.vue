<template>
  <section
    class="gp timeline"
    tabindex="0"
    data-panel="timeline"
    :aria-label="$t('god.timeline.title')"
    @keydown="onKey"
  >
    <span class="gp-key">5</span>
    <div class="buttons">
      <button :title="$t('god.timeline.first')" :aria-label="$t('god.timeline.first')" @click="scrubTo(0)">|◀</button>
      <button :title="$t('god.timeline.back')" :aria-label="$t('god.timeline.back')" @click="stepRound(-1)">◀</button>
      <button
        class="play"
        :title="state.playing ? $t('god.timeline.pauseReplay') : $t('god.timeline.replay')"
        :aria-label="state.playing ? $t('god.timeline.pauseReplay') : $t('god.timeline.replay')"
        @click="togglePlayback"
      >{{ state.playing ? '❚❚' : '▶' }}</button>
      <button :title="$t('god.timeline.forward')" :aria-label="$t('god.timeline.forward')" @click="stepRound(1)">▶|</button>
      <button class="live" :class="{ on: isLiveView }" @click="goLive">{{ $t('god.timeline.live') }}</button>
    </div>

    <div
      ref="track"
      class="track"
      role="slider"
      :aria-valuemin="0"
      :aria-valuemax="liveRound"
      :aria-valuenow="asOfRound"
      :aria-label="$t('god.timeline.scrubber')"
      @pointerdown="onDown"
      @pointermove="onDrag"
      @pointerup="dragging = false"
      @pointercancel="dragging = false"
    >
      <div class="rail"></div>
      <div class="done" :style="{ width: pct(liveRound) }"></div>
      <div class="seen" :style="{ width: pct(asOfRound) }"></div>
      <span v-for="t in ticks" :key="t" class="tick" :style="{ left: pct(t) }">{{ t }}</span>
      <span
        v-for="m in markers"
        :key="m.round"
        class="mark"
        :style="{ left: pct(m.round) }"
        :title="m.title"
      >▼</span>
      <div class="handle" :style="{ left: pct(asOfRound) }"></div>
    </div>

    <div class="readout">
      <span :class="isLiveView ? 'mode-live' : 'mode-replay'">
        {{ isLiveView ? $t('god.timeline.following') : $t('god.timeline.asOf') }}
      </span>
      R{{ asOfRound }}<span class="of"> / {{ liveRound }} · {{ $t('god.timeline.planned', { n: totalRounds }) }}</span>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import {
  state, asOfRound, liveRound, totalRounds, isLiveView, interventionsByRound,
  scrubTo, stepRound, goLive, togglePlayback, stopPlayback
} from '../../store/godTerminal'

const track = ref(null)
const dragging = ref(false)

const span = computed(() => Math.max(1, totalRounds.value))
const pct = round => `${(Math.min(round, span.value) / span.value) * 100}%`

const ticks = computed(() => {
  const n = span.value
  const every = [1, 2, 5, 10, 20, 50, 100, 200, 500].find(s => n / s <= 12) || 1000
  const out = []
  for (let t = 0; t <= n; t += every) out.push(t)
  return out
})

// One marker per round that has interventions; the tooltip lists them.
const markers = computed(() =>
  [...interventionsByRound.value.entries()].map(([round, entries]) => ({
    round,
    title: `R${round}: ` + entries.map(e => `${e.command} — ${e.summary}`).join('\n')
  }))
)

function roundAt(ev) {
  const rect = track.value.getBoundingClientRect()
  return Math.round(((ev.clientX - rect.left) / rect.width) * span.value)
}

function apply(ev) {
  stopPlayback()
  const round = roundAt(ev)
  if (round >= liveRound.value) goLive()
  else scrubTo(round)
}

function onDown(ev) {
  dragging.value = true
  track.value.setPointerCapture(ev.pointerId)
  apply(ev)
}
function onDrag(ev) {
  if (dragging.value) apply(ev)
}

function onKey(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return
  const handlers = {
    ArrowLeft: () => stepRound(-1), h: () => stepRound(-1),
    ArrowRight: () => stepRound(1), l: () => stepRound(1),
    ' ': togglePlayback,
    Home: () => { stopPlayback(); scrubTo(0) },
    End: goLive
  }
  const handler = handlers[ev.key]
  if (handler) { ev.preventDefault(); handler() }
}
</script>

<style scoped>
.gp.timeline { flex-direction: row; align-items: center; gap: 10px; padding: 0 8px; }
.buttons { display: flex; gap: 2px; flex: none; }
button {
  background: none; border: 1px solid var(--g-line); color: var(--g-ink); height: 22px; min-width: 28px;
  padding: 0 6px; font: inherit; font-size: 11px; cursor: pointer;
}
button:hover { border-color: var(--g-ink2); }
button:focus-visible { outline: 1px solid var(--g-ink-hi); }
button.live.on { background: var(--g-good); border-color: var(--g-good); color: var(--g-bg); }
.track { flex: 1; position: relative; height: 30px; cursor: pointer; touch-action: none; }
.rail, .done, .seen { position: absolute; left: 0; top: 8px; height: 6px; }
.rail { right: 0; background: var(--g-line-soft); }
.done { background: var(--g-mute); }
.seen { background: var(--g-ink); }
.handle { position: absolute; top: 3px; width: 2px; height: 16px; margin-left: -1px; background: var(--g-ink-hi); box-shadow: 0 0 0 2px var(--g-panel); }
.tick { position: absolute; top: 17px; transform: translateX(-50%); font-size: 10px; color: var(--g-mute); pointer-events: none; }
.tick:first-of-type { transform: none; }
.mark { position: absolute; top: -3px; transform: translateX(-50%); font-size: 9px; line-height: 10px; color: var(--g-warn); }
.readout { flex: none; min-width: 230px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.of { color: var(--g-mute); }
.mode-live { color: var(--g-good); margin-right: 6px; }
.mode-replay { color: var(--g-warn); margin-right: 6px; }
</style>
