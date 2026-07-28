<template>
  <span class="status" :class="tone" :title="label">
    <span class="dot" aria-hidden="true" />
    <span v-if="showLabel" class="label">{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: [String, null], default: '' },
  showLabel: { type: Boolean, default: true },
})

const tone = computed(() => {
  const x = String(props.status || '').toLowerCase()
  if (!x || x === '—' || x === '-') return 'neutral'
  if (x.includes('fail') || x.includes('error')) return 'fail'
  if (
    x.includes('finish') ||
    x.includes('done') ||
    x.includes('success') ||
    x === 'completed' ||
    x.includes('ready')
  )
    return 'ok'
  if (x.includes('queue') || x.includes('pend') || x.includes('process') || x.includes('run'))
    return 'pending'
  return 'pending'
})

const label = computed(() => {
  const raw = props.status
  if (raw == null || raw === '') return '未知'
  return String(raw)
})
</script>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-secondary);
  max-width: 100%;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #c7c7cc;
  box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.03);
}
.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}
.status.ok {
  color: #1b7a35;
}
.status.ok .dot {
  background: var(--success);
  box-shadow: 0 0 0 3px rgba(52, 199, 89, 0.16);
}
.status.fail {
  color: var(--danger);
}
.status.fail .dot {
  background: var(--danger);
  box-shadow: 0 0 0 3px rgba(255, 59, 48, 0.14);
}
.status.pending {
  color: var(--accent);
}
.status.pending .dot {
  background: var(--accent);
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.14);
  animation: pulse-dot 1.4s var(--ease-out) infinite;
}
.status.neutral .dot {
  background: #c7c7cc;
}
@keyframes pulse-dot {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.55;
    transform: scale(0.92);
  }
}
@media (prefers-reduced-motion: reduce) {
  .status.pending .dot {
    animation: none;
  }
}
</style>
