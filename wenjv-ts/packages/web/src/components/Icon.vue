<template>
  <svg
    class="ui-icon"
    :class="[`s-${size}`, { spin }]"
    :width="px"
    :height="px"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    focusable="false"
  >
    <!-- stroke icons -->
    <g
      v-if="kind === 'stroke'"
      :stroke="color"
      :stroke-width="strokeWidth"
      stroke-linecap="round"
      stroke-linejoin="round"
      fill="none"
    >
      <template v-if="name === 'chat'">
        <path d="M7.5 18.5 4 21V7.5A2.5 2.5 0 0 1 6.5 5h11A2.5 2.5 0 0 1 20 7.5v8a2.5 2.5 0 0 1-2.5 2.5H7.5Z" />
        <path d="M8.5 10h7M8.5 13.5h4.5" />
      </template>
      <template v-else-if="name === 'library'">
        <path d="M6 5.5v13" />
        <path d="M10 5.5v13" />
        <path d="M14 6.2 18.5 18.5" />
        <path d="M13.5 18.5h5.5" />
      </template>
      <template v-else-if="name === 'logout'">
        <path d="M10 12h9m0 0-3-3m3 3-3 3" />
        <path d="M14 6.5V6a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5a2 2 0 0 0 2-2v-.5" />
      </template>
      <template v-else-if="name === 'send'">
        <path d="M5.2 12 19 5.5 14.2 18.5 11.5 13.8 5.2 12Z" />
        <path d="m11.5 13.8 7.5-8.3" />
      </template>
      <template v-else-if="name === 'upload'">
        <path d="M12 16V7m0 0 3.25 3.25M12 7 8.75 10.25" />
        <path d="M6.5 16.5V18A1.5 1.5 0 0 0 8 19.5h8a1.5 1.5 0 0 0 1.5-1.5v-1.5" />
      </template>
      <template v-else-if="name === 'file'">
        <path d="M8 4.5h5.2L17.5 9v10.5A1.5 1.5 0 0 1 16 21H8a1.5 1.5 0 0 1-1.5-1.5v-13A1.5 1.5 0 0 1 8 4.5Z" />
        <path d="M13 4.5V9h4.5" />
        <path d="M9.5 13h5M9.5 16.5h3.5" />
      </template>
      <template v-else-if="name === 'image'">
        <rect x="4.5" y="5.5" width="15" height="13" rx="2.2" />
        <circle cx="9.2" cy="10" r="1.4" />
        <path d="m8 16.5 3.2-3.4a1.2 1.2 0 0 1 1.7 0L16.8 16.5" />
      </template>
      <template v-else-if="name === 'note'">
        <path d="M7 4.5h7.2L17.5 8v11.5A1.5 1.5 0 0 1 16 21H7a1.5 1.5 0 0 1-1.5-1.5v-14A1.5 1.5 0 0 1 7 4.5Z" />
        <path d="M14 4.5V8h3.5" />
        <path d="M9 12h6M9 15.5h6M9 19h3.5" />
      </template>
      <template v-else-if="name === 'link'">
        <path d="M10.2 13.8a3.6 3.6 0 0 0 5.1 0l2.1-2.1a3.6 3.6 0 1 0-5.1-5.1l-1.1 1.1" />
        <path d="M13.8 10.2a3.6 3.6 0 0 0-5.1 0L6.6 12.3a3.6 3.6 0 1 0 5.1 5.1l1.1-1.1" />
      </template>
      <template v-else-if="name === 'search'">
        <circle cx="11" cy="11" r="5.5" />
        <path d="m15.5 15.5 3.8 3.8" />
      </template>
      <template v-else-if="name === 'sparkles'">
        <path d="M12 4.5v2.2M12 17.3v2.2M4.5 12h2.2M17.3 12h2.2M6.9 6.9l1.5 1.5M15.6 15.6l1.5 1.5M17.1 6.9l-1.5 1.5M8.4 15.6l-1.5 1.5" />
        <circle cx="12" cy="12" r="2.4" />
      </template>
      <template v-else-if="name === 'tag'">
        <path d="M20.5 13.5 12 5H5v7l8.5 8.5a2.12 2.12 0 0 0 3 0l4-4a2.12 2.12 0 0 0 0-3Z" />
        <circle cx="8" cy="8" r="1.5" />
      </template>
      <template v-else-if="name === 'check'">
        <path d="m5.5 12.5 4.2 4.2 8.8-9.4" />
      </template>
      <template v-else-if="name === 'x'">
        <path d="m7 7 10 10M17 7 7 17" />
      </template>
      <template v-else-if="name === 'refresh'">
        <path d="M19 12a7 7 0 1 1-2-4.9" />
        <path d="M19 5v5h-5" />
      </template>
      <template v-else-if="name === 'user'">
        <circle cx="12" cy="9" r="3.2" />
        <path d="M6.2 18.5c.9-2.8 3-4.3 5.8-4.3s4.9 1.5 5.8 4.3" />
      </template>
      <template v-else-if="name === 'bot'">
        <rect x="5.5" y="8" width="13" height="10.5" rx="3" />
        <path d="M12 8V5.5M9.5 5.5h5" />
        <circle cx="9.5" cy="13" r="1" fill="currentColor" stroke="none" />
        <circle cx="14.5" cy="13" r="1" fill="currentColor" stroke="none" />
        <path d="M9.5 16h5" />
      </template>
      <template v-else-if="name === 'folder'">
        <path d="M4.5 8.5A2 2 0 0 1 6.5 6.5h3.2l1.6 1.8H17.5a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2V8.5Z" />
      </template>
      <template v-else-if="name === 'book'">
        <path d="M5.5 5.5A2 2 0 0 1 7.5 3.5H18v15H7.5a2 2 0 0 0 0 4H18" />
        <path d="M7.5 18.5h10.5" />
      </template>
      <template v-else-if="name === 'globe'">
        <circle cx="12" cy="12" r="7.5" />
        <path d="M4.5 12h15M12 4.5c2.2 2.4 3.3 5 3.3 7.5S14.2 17.1 12 19.5M12 4.5C9.8 6.9 8.7 9.5 8.7 12s1.1 5.1 3.3 7.5" />
      </template>
      <template v-else-if="name === 'image-search'">
        <rect x="3.5" y="5" width="12.5" height="11" rx="2" />
        <circle cx="7.5" cy="9.2" r="1.1" />
        <path d="m6.2 14.2 2.4-2.5a1 1 0 0 1 1.4 0l2.2 2.3" />
        <circle cx="16.2" cy="15.8" r="3.2" />
        <path d="m18.6 18.2 2 2" />
      </template>
      <template v-else-if="name === 'quote'">
        <path d="M8.5 17.5c-2 0-3.5-1.6-3.5-3.8 0-2.6 1.8-5 4.4-6.7l.8 1.2c-1.8 1.1-2.8 2.5-2.9 3.9.4-.3 1-.4 1.6-.4 1.5 0 2.6 1.1 2.6 2.6s-1.2 3.2-3 3.2Zm8 0c-2 0-3.5-1.6-3.5-3.8 0-2.6 1.8-5 4.4-6.7l.8 1.2c-1.8 1.1-2.8 2.5-2.9 3.9.4-.3 1-.4 1.6-.4 1.5 0 2.6 1.1 2.6 2.6s-1.2 3.2-3 3.2Z" />
      </template>
      <template v-else-if="name === 'sliders'">
        <path d="M5 8h7M16 8h3M12 5.5v5M5 16h3M12 16h7M9 13.5v5" />
      </template>
      <template v-else-if="name === 'plus'">
        <path d="M12 6v12M6 12h12" />
      </template>
      <template v-else-if="name === 'arrow-up'">
        <path d="M12 18V7m0 0 4 4M12 7 8 11" />
      </template>
      <template v-else-if="name === 'arrow-right'">
        <path d="M5 12h12m0 0-4-4m4 4-4 4" />
      </template>
      <template v-else-if="name === 'chevron-down'">
        <path d="m7 10 5 5 5-5" />
      </template>
      <template v-else-if="name === 'lock'">
        <rect x="6" y="10.5" width="12" height="9" rx="2" />
        <path d="M9 10.5V8a3 3 0 0 1 6 0v2.5" />
      </template>
      <template v-else-if="name === 'mail'">
        <rect x="4" y="6" width="16" height="12" rx="2.2" />
        <path d="m5.5 8.5 6.5 5 6.5-5" />
      </template>
      <template v-else>
        <circle cx="12" cy="12" r="7" />
      </template>
    </g>

    <!-- filled brand mark -->
    <g v-else-if="name === 'logo'">
      <rect x="2" y="2" width="20" height="20" rx="5.5" fill="currentColor" />
      <path
        d="M7.2 15.8V8.2h2.1c1.7 0 2.7.9 2.7 2.3 0 1-.5 1.7-1.3 2l1.6 3.3h-1.9l-1.4-3H9v3h-1.8Zm1.8-4.4h.3c.6 0 1-.3 1-.9s-.4-.9-1-.9h-.3v1.8Z"
        fill="#fff"
      />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name: string
    size?: number | string
    strokeWidth?: number | string
    color?: string
    spin?: boolean
  }>(),
  {
    size: 18,
    strokeWidth: 1.75,
    color: 'currentColor',
    spin: false,
  },
)

const filled = new Set(['logo'])
const kind = computed(() => (filled.has(props.name) ? 'fill' : 'stroke'))
const px = computed(() => Number(props.size) || 18)
</script>

<style scoped>
.ui-icon {
  display: block;
  flex-shrink: 0;
  /* optical center: SF-style glyphs sit slightly high */
  transform: translateY(0.5px);
}
.ui-icon.spin {
  transform: none;
  transform-origin: center center;
  animation: icon-spin 0.7s linear infinite;
}
@keyframes icon-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .ui-icon.spin {
    animation: none;
  }
}
</style>
