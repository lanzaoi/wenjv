<template>
  <div v-if="isOpen" class="cmd-overlay" @click.self="close">
    <div class="cmd-modal">
      <div class="cmd-header">
        <span class="cmd-icon">🔍</span>
        <input
          ref="inputRef"
          v-model="query"
          type="text"
          class="cmd-input"
          placeholder="搜索 Wiki 页面或输入新页面名称回车创建... (ESC 关闭)"
          @keydown="handleKeydown"
        />
        <kbd class="cmd-badge">ESC</kbd>
      </div>

      <div class="cmd-body">
        <div v-if="loading" class="cmd-loading">
          <span class="spinner"></span> 搜索中...
        </div>

        <div v-else-if="results.length > 0" class="cmd-list">
          <div
            v-for="(item, idx) in results"
            :key="item.id"
            class="cmd-item"
            :class="{ active: idx === selectedIndex }"
            @mouseenter="selectedIndex = idx"
            @click="selectItem(item)"
          >
            <div class="cmd-item-icon">{{ item.icon || '📄' }}</div>
            <div class="cmd-item-info">
              <div class="cmd-item-title">
                {{ item.title }}
                <span v-if="item.match_source === 'content'" class="cmd-match-tag">正文匹配</span>
              </div>
              <div v-if="item.snippet" class="cmd-item-snippet">{{ item.snippet }}</div>
            </div>
            <div class="cmd-item-action">跳转 ↵</div>
          </div>
        </div>

        <div v-else-if="query.trim()" class="cmd-empty">
          <div class="cmd-empty-tip">未找到匹配页面</div>
          <button type="button" class="cmd-create-btn" @click="createNewPage">
            ➕ 快速新建并打开：<strong>{{ query.trim() }}</strong>
          </button>
        </div>

        <div v-else class="cmd-hint">
          <span>输入关键词快速搜索页面标题与全文内容</span>
          <span>按 <kbd>↑</kbd> <kbd>↓</kbd> 选择，<kbd>Enter</kbd> 确认跳转</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { wikiApi } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

interface WikiSearchResult {
  id: number
  title: string
  icon?: string
  match_source?: string
  path?: string
  snippet?: string
}

const props = withDefaults(
  defineProps<{
    isOpen?: boolean
  }>(),
  {
    isOpen: false,
  },
)

const emit = defineEmits<{
  close: []
  'select-page': [id: number]
  'create-page': [title: string]
}>()

const authStore = useAuthStore()
const query = ref('')
const results = ref<WikiSearchResult[]>([])
const loading = ref(false)
const selectedIndex = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

let searchTimeout: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.isOpen,
  (val) => {
    if (val) {
      query.value = ''
      results.value = []
      selectedIndex.value = 0
      nextTick(() => {
        inputRef.value?.focus()
      })
    }
  }
)

watch(query, (val) => {
  if (searchTimeout) clearTimeout(searchTimeout)
  const q = val.trim()
  if (!q) {
    results.value = []
    loading.value = false
    return
  }
  loading.value = true
  searchTimeout = setTimeout(async () => {
    try {
      const data = await wikiApi.searchWiki(q, authStore.token)
      results.value = Array.isArray(data) ? (data as WikiSearchResult[]) : []
      selectedIndex.value = 0
    } catch (err) {
      console.warn('Wiki search error:', err)
      results.value = []
    } finally {
      loading.value = false
    }
  }, 180)
})

function close() {
  emit('close')
}

function selectItem(item: WikiSearchResult) {
  emit('select-page', item.id)
  close()
}

function createNewPage() {
  if (!query.value.trim()) return
  emit('create-page', query.value.trim())
  close()
}

function handleKeydown(e: KeyboardEvent) {
  if (e.isComposing) return
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (results.value.length > 0) {
      selectedIndex.value = (selectedIndex.value + 1) % results.value.length
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (results.value.length > 0) {
      selectedIndex.value = (selectedIndex.value - 1 + results.value.length) % results.value.length
    }
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (loading.value) {
      // Still searching, ignore premature Enter to prevent ghost page creation
      return
    }
    const current = results.value[selectedIndex.value]
    if (current) {
      selectItem(current)
    } else if (query.value.trim()) {
      createNewPage()
    }
  }
}
</script>

<style scoped>
.cmd-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}

.cmd-modal {
  width: 620px;
  max-width: 92vw;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.18), 0 0 0 1px rgba(0, 0, 0, 0.06);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.cmd-header {
  display: flex;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid #e2e8f0;
  gap: 12px;
}

.cmd-icon {
  font-size: 1.1rem;
}

.cmd-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 1rem;
  color: #1e293b;
  background: transparent;
}

.cmd-badge {
  font-size: 0.75rem;
  padding: 2px 6px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  color: #64748b;
}

.cmd-body {
  max-height: 380px;
  overflow-y: auto;
  padding: 8px;
}

.cmd-loading {
  padding: 24px;
  text-align: center;
  font-size: 0.9rem;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #cbd5e1;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.cmd-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cmd-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
  gap: 12px;
}

.cmd-item.active {
  background: #eff6ff;
}

.cmd-item-icon {
  font-size: 1.2rem;
}

.cmd-item-info {
  flex: 1;
  min-width: 0;
}

.cmd-item-title {
  font-size: 0.92rem;
  font-weight: 500;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}

.cmd-match-tag {
  font-size: 0.7rem;
  font-weight: 400;
  background: #e0f2fe;
  color: #0284c7;
  padding: 1px 5px;
  border-radius: 4px;
}

.cmd-item-snippet {
  font-size: 0.8rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 2px;
}

.cmd-item-action {
  font-size: 0.75rem;
  color: #94a3b8;
}

.cmd-empty {
  padding: 24px 16px;
  text-align: center;
}

.cmd-empty-tip {
  font-size: 0.88rem;
  color: #94a3b8;
  margin-bottom: 12px;
}

.cmd-create-btn {
  background: #3b82f6;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 0.88rem;
  cursor: pointer;
  transition: background 0.15s;
}

.cmd-create-btn:hover {
  background: #2563eb;
}

.cmd-hint {
  padding: 20px;
  text-align: center;
  font-size: 0.82rem;
  color: #94a3b8;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cmd-hint kbd {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 1px 4px;
  border-radius: 3px;
}
</style>
