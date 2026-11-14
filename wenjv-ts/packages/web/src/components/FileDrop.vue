<template>
  <label
    class="dropzone"
    :class="{ dragover, 'has-file': !!fileName }"
    @dragenter.prevent="onEnter"
    @dragover.prevent="onEnter"
    @dragleave.prevent="onLeave"
    @drop.prevent="onDrop"
  >
    <input
      type="file"
      :accept="accept"
      :disabled="disabled"
      @change="onChange"
    />
    <template v-if="!fileName">
      <div class="dz-icon" aria-hidden="true">
        <Icon :name="icon" :size="20" />
      </div>
      <div class="dz-title">{{ title }}</div>
      <div class="dz-sub">{{ subtitle }}</div>
    </template>
    <template v-else>
      <div class="file-row">
        <div class="file-left">
          <div class="file-type-icon" aria-hidden="true">
            <Icon :name="fileIcon" :size="18" />
          </div>
          <div class="file-meta">
            <div class="file-name">{{ fileName }}</div>
            <div class="dz-sub" v-if="fileSize">{{ fileSize }}</div>
          </div>
        </div>
        <button type="button" class="btn btn-ghost btn-sm clear" title="清除" @click.prevent.stop="clear">
          <Icon name="x" :size="16" />
        </button>
      </div>
      <img v-if="previewUrl" :src="previewUrl" class="preview" alt="" />
    </template>
  </label>
</template>

<script setup lang="ts">
import { ref, watch, computed, onBeforeUnmount } from 'vue'
import Icon from './Icon.vue'

const props = withDefaults(
  defineProps<{
    accept?: string
    title?: string
    subtitle?: string
    icon?: string
    disabled?: boolean
    modelValue?: File | null
  }>(),
  {
    accept: '',
    title: '拖拽或点击上传',
    subtitle: '支持常见文档与图片格式',
    icon: 'upload',
    disabled: false,
    modelValue: null,
  },
)
const emit = defineEmits<{
  'update:modelValue': [file: File | null]
}>()

const dragover = ref(false)
const fileName = ref('')
const fileSize = ref('')
const previewUrl = ref('')
const mime = ref('')
let dragDepth = 0

const fileIcon = computed(() => {
  if (mime.value.startsWith('image/')) return 'image'
  if (mime.value.includes('pdf')) return 'file'
  return 'file'
})

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function setFile(file: File | null) {
  emit('update:modelValue', file || null)
  applyMeta(file)
}

function applyMeta(file: File | null | undefined) {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  if (!file) {
    fileName.value = ''
    fileSize.value = ''
    mime.value = ''
    return
  }
  fileName.value = file.name
  fileSize.value = fmtSize(file.size)
  mime.value = file.type || ''
  if (file.type?.startsWith('image/')) {
    previewUrl.value = URL.createObjectURL(file)
  }
}

watch(
  () => props.modelValue,
  (f) => applyMeta(f),
  { immediate: true },
)

function onChange(e: Event) {
  const input = e.target as HTMLInputElement | null
  const f = input?.files?.[0] || null
  setFile(f)
  if (input) input.value = ''
}
function onEnter() {
  dragDepth += 1
  dragover.value = true
}
function onLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragover.value = false
}
function onDrop(e: DragEvent) {
  dragDepth = 0
  dragover.value = false
  if (props.disabled) return
  const f = e.dataTransfer?.files?.[0] || null
  if (f) setFile(f)
}
function clear() {
  setFile(null)
}

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
.file-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.file-left {
  display: flex;
  gap: 10px;
  min-width: 0;
  align-items: flex-start;
}
.file-type-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--bg);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  color: var(--accent);
  flex-shrink: 0;
}
.file-meta {
  min-width: 0;
}
.file-name {
  font-size: 13px;
  font-weight: 560;
  word-break: break-all;
  letter-spacing: -0.01em;
}
.preview {
  margin-top: 10px;
  width: 100%;
  max-height: 140px;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid var(--border);
}
.clear {
  flex-shrink: 0;
  padding: 6px !important;
  border-radius: 8px !important;
}
</style>
