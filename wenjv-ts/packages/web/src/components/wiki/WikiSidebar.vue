<template>
  <aside class="wiki-sidebar-panel">
    <!-- Tabs Header -->
    <div class="sidebar-tabs">
      <button
        :class="['tab-btn', activeTab === 'toc' ? 'active' : '']"
        @click="activeTab = 'toc'"
        title="目录大纲"
      >
        大纲
      </button>
      <button
        :class="['tab-btn', activeTab === 'backlinks' ? 'active' : '']"
        @click="activeTab = 'backlinks'"
        title="反向链接"
      >
        反链 ({{ backlinks.length }})
      </button>
      <button
        :class="['tab-btn', activeTab === 'diff' ? 'active' : '']"
        @click="fetchRevisionsAndDiff"
        title="版本对比"
      >
        历史对比
      </button>
      <button
        :class="['tab-btn copilot-tab', activeTab === 'copilot' ? 'active' : '']"
        @click="activeTab = 'copilot'"
        title="AI 伴随助手"
      >
        ✨ 助手
      </button>
    </div>

    <!-- 1. TOC Tab -->
    <div v-if="activeTab === 'toc'" class="tab-content">
      <div v-if="!toc.length" class="empty-state">当前文档无标题层级</div>
      <div v-else class="toc-list">
        <div
          v-for="item in toc"
          :key="item.text"
          :class="['toc-item', `level-${item.level}`]"
          @click="$emit('scroll-to-heading', item.text)"
        >
          {{ item.text }}
        </div>
      </div>
    </div>

    <!-- 2. Backlinks & Unlinked Mentions Tab -->
    <div v-else-if="activeTab === 'backlinks'" class="tab-content">
      <div class="sidebar-sub-section">
        <div class="sub-section-title">已建立引用的反链 ({{ backlinks.length }})</div>
        <div v-if="!backlinks.length" class="empty-state">当前页面未被其他页面引用</div>
        <div v-else class="link-list">
          <div
            v-for="link in backlinks"
            :key="link.source_page_id"
            class="link-card"
            @click="$emit('open-page', link.source_page_id)"
          >
            <div class="link-title">{{ link.source_title }}</div>
            <div v-if="link.alias" class="link-alias">作为: {{ link.alias }}</div>
            <div v-if="link.section_anchor" class="link-anchor">锚点: #{{ link.section_anchor }}</div>
          </div>
        </div>
      </div>

      <div class="sidebar-sub-section mt-4">
        <div class="flex items-center justify-between">
          <div class="sub-section-title">未链接提及 (Unlinked Mentions)</div>
          <button type="button" class="refresh-mentions-btn" @click="fetchUnlinkedMentions" title="刷新未链接提及">🔄</button>
        </div>
        <div v-if="loadingMentions" class="empty-state">检索提及中...</div>
        <div v-else-if="!unlinkedMentions.length" class="empty-state">未发现提及本页面标题的内容</div>
        <div v-else class="link-list">
          <div
            v-for="item in unlinkedMentions"
            :key="item.page_id"
            class="unlinked-card"
          >
            <div class="flex items-center justify-between">
              <span class="unlinked-title" @click="$emit('open-page', item.page_id)">📄 {{ item.title }}</span>
              <button
                type="button"
                class="link-mention-btn"
                @click="onLinkMention(item.page_id)"
                title="一键将该页面中的文本转换为 [[双链]]"
              >
                + 链接
              </button>
            </div>
            <div
              v-for="(m, midx) in item.mentions"
              :key="midx"
              class="unlinked-excerpt"
            >
              “...{{ m.excerpt }}...”
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. Diff Tab -->
    <div v-else-if="activeTab === 'diff'" class="tab-content">
      <div v-if="loadingRevisions" class="empty-state">加载版本中...</div>
      <div v-else-if="revisions.length < 2" class="empty-state">需要至少两个历史快照才能进行 Diff 对比</div>
      <div v-else class="diff-container">
        <div class="diff-selectors">
          <label class="text-xs text-gray-500">对比版本：</label>
          <div class="flex items-center gap-2 mt-1">
            <select v-model="fromRev" class="select-sm" @change="onDiffChange">
              <option v-for="r in revisions" :key="r.rev_no" :value="r.rev_no">v{{ r.rev_no }}</option>
            </select>
            <span class="text-xs text-gray-400">→</span>
            <select v-model="toRev" class="select-sm" @change="onDiffChange">
              <option v-for="r in revisions" :key="r.rev_no" :value="r.rev_no">v{{ r.rev_no }}</option>
            </select>
          </div>
        </div>

        <div v-if="diffLines.length" class="diff-viewer mt-3">
          <div
            v-for="(line, idx) in diffLines"
            :key="idx"
            :class="['diff-line', line.type]"
          >
            <span class="line-prefix">{{ line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' ' }}</span>
            <span class="line-text">{{ line.content }}</span>
          </div>
        </div>
        <div v-else class="empty-state mt-4">两版本内容完全一致</div>

        <button class="rollback-btn-full mt-4" @click="$emit('rollback', toRev)">
          恢复至选中的目标版本 v{{ toRev }}
        </button>
      </div>
    </div>

    <!-- 4. Copilot Tab -->
    <div v-else-if="activeTab === 'copilot'" class="tab-content copilot-box">
      <div class="copilot-mode-toggle">
        <button
          :class="['mode-chip', copilotMode === 'page' ? 'active' : '']"
          @click="copilotMode = 'page'"
        >
          单篇精读
        </button>
        <button
          :class="['mode-chip', copilotMode === 'kb' ? 'active' : '']"
          @click="copilotMode = 'kb'"
        >
          全库综合
        </button>
      </div>

      <!-- Messages View -->
      <div class="copilot-messages" ref="msgContainerRef">
        <div v-if="!chatMessages.length" class="empty-state">
          💡 可以就当前 Wiki 页面向 AI 提问、请求提炼核心要点或查找图表证据。
        </div>
        <div v-for="(msg, idx) in chatMessages" :key="idx" :class="['chat-bubble', msg.role]">
          <div class="bubble-text">{{ msg.content }}</div>
          <!-- Citations display in copilot -->
          <div v-if="msg.citations && msg.citations.length" class="copilot-cite-list">
            <div class="cite-header">📎 引用依据:</div>
            <div
              v-for="(c, cIdx) in msg.citations"
              :key="cIdx"
              class="copilot-cite-item"
              @click="c.source_page_id ? $emit('open-page', c.source_page_id) : null"
            >
              <span class="cite-badge">[{{ c.index || cIdx + 1 }}]</span>
              <span class="cite-title">{{ c.title }}</span>
              <span v-if="c.has_image" class="cite-img-pill">🖼️</span>
            </div>
          </div>
        </div>
        <div v-if="isStreaming" class="streaming-dot">正在思考并查阅依据...</div>
      </div>

      <!-- Input box -->
      <div class="copilot-input-row">
        <input
          v-model="inputQuestion"
          placeholder="就当前文档提问..."
          class="copilot-input"
          @keydown.enter="sendCopilotQuestion"
        />
        <button class="send-btn" :disabled="isStreaming || !inputQuestion.trim()" @click="sendCopilotQuestion">
          ➤
        </button>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { wikiApi } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

const props = defineProps({
  pageId: { type: Number, default: null },
  backlinks: { type: Array, default: () => [] },
  toc: { type: Array, default: () => [] },
})

const emit = defineEmits(['open-page', 'rollback', 'scroll-to-heading'])

const auth = useAuthStore()
const activeTab = ref('toc')

// Unlinked Mentions state
const unlinkedMentions = ref([])
const loadingMentions = ref(false)

async function fetchUnlinkedMentions() {
  if (!props.pageId) return
  loadingMentions.value = true
  try {
    const data = await wikiApi.getUnlinkedMentions(props.pageId, auth.token)
    unlinkedMentions.value = Array.isArray(data) ? data : []
  } catch (err) {
    console.warn('Failed to load unlinked mentions:', err)
  } finally {
    loadingMentions.value = false
  }
}

async function onLinkMention(sourcePageId) {
  if (!props.pageId) return
  try {
    await wikiApi.linkMention(props.pageId, sourcePageId, auth.token)
    await fetchUnlinkedMentions()
    // Refresh page if needed
  } catch (err) {
    alert(`链接失败: ${err.message || err}`)
  }
}

watch(
  () => [props.pageId, activeTab.value],
  ([pid, tab]) => {
    if (pid && tab === 'backlinks') {
      fetchUnlinkedMentions()
    }
  }
)

// Diff state
const revisions = ref([])
const fromRev = ref(1)
const toRev = ref(2)
const diffLines = ref([])
const loadingRevisions = ref(false)

// Copilot state
const copilotMode = ref('page')
const inputQuestion = ref('')
const isStreaming = ref(false)
const chatMessages = ref([])
const msgContainerRef = ref(null)

async function fetchRevisionsAndDiff() {
  activeTab.value = 'diff'
  if (!props.pageId) return
  loadingRevisions.value = true
  try {
    revisions.value = await wikiApi.getRevisions(props.pageId, auth.token)
    if (revisions.value.length >= 2) {
      fromRev.value = revisions.value[1].rev_no
      toRev.value = revisions.value[0].rev_no
      await onDiffChange()
    }
  } catch (err) {
    console.error('Failed to load revisions', err)
  } finally {
    loadingRevisions.value = false
  }
}

async function onDiffChange() {
  if (!props.pageId || !fromRev.value || !toRev.value) return
  try {
    const res = await wikiApi.getDiff(props.pageId, fromRev.value, toRev.value, auth.token)
    diffLines.value = res.diff_lines || []
  } catch (err) {
    console.error('Failed to compute diff', err)
  }
}

let copilotAbortCtrl = null

onBeforeUnmount(() => {
  if (copilotAbortCtrl) {
    copilotAbortCtrl.abort()
    copilotAbortCtrl = null
  }
})

async function sendCopilotQuestion() {
  const q = inputQuestion.value.trim()
  if (!q || isStreaming.value || !props.pageId) return

  if (copilotAbortCtrl) {
    copilotAbortCtrl.abort()
  }
  copilotAbortCtrl = new AbortController()

  chatMessages.value.push({ role: 'user', content: q })
  inputQuestion.value = ''
  isStreaming.value = true

  const assistantMsg = { role: 'assistant', content: '' }
  chatMessages.value.push(assistantMsg)

  await nextTick()
  if (msgContainerRef.value) {
    msgContainerRef.value.scrollTop = msgContainerRef.value.scrollHeight
  }

  try {
    await wikiApi.streamCopilot(
      props.pageId,
      { question: q, mode: copilotMode.value, include_images: true },
      auth.token,
      (ev) => {
        if (ev.type === 'token') {
          assistantMsg.content += ev.content
          if (msgContainerRef.value) {
            msgContainerRef.value.scrollTop = msgContainerRef.value.scrollHeight
          }
        } else if (ev.type === 'citations') {
          assistantMsg.citations = ev.citations || []
        }
      },
      copilotAbortCtrl.signal
    )
  } catch (err) {
    if (err.name !== 'AbortError') {
      assistantMsg.content += `\n[请求错误: ${err.message}]`
    }
  } finally {
    isStreaming.value = false
    copilotAbortCtrl = null
  }
}

watch(
  () => props.pageId,
  () => {
    if (copilotAbortCtrl) {
      copilotAbortCtrl.abort()
      copilotAbortCtrl = null
    }
    isStreaming.value = false
    chatMessages.value = []
    if (activeTab.value === 'diff') {
      fetchRevisionsAndDiff()
    }
  }
)
</script>

<style scoped>
.wiki-sidebar-panel {
  width: 280px;
  height: 100%;
  border-left: 1px solid rgba(0, 0, 0, 0.08);
  background: #fbfbfd;
  display: flex;
  flex-direction: column;
}

.sidebar-tabs {
  display: flex;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding: 6px 6px;
  gap: 2px;
}

.tab-btn {
  flex: 1;
  padding: 6px 4px;
  font-size: 11px;
  font-weight: 500;
  color: #6b7280;
  border-radius: 6px;
  text-align: center;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  color: #111827;
  background: rgba(0, 0, 0, 0.03);
}

.tab-btn.active {
  color: #0071e3;
  background: rgba(0, 113, 227, 0.08);
}

.copilot-tab.active {
  color: #8b5cf6;
  background: rgba(139, 92, 246, 0.1);
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px 10px;
}

.empty-state {
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
  padding: 24px 8px;
  line-height: 1.6;
}

/* TOC */
.toc-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.toc-item {
  font-size: 12px;
  color: #4b5563;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.toc-item:hover {
  background: rgba(0, 113, 227, 0.06);
  color: #0071e3;
}

.toc-item.level-2 { padding-left: 14px; }
.toc-item.level-3 { padding-left: 24px; color: #6b7280; }

/* Backlinks */
.link-card {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  margin-bottom: 8px;
}
.link-card:hover { border-color: #0071e3; }
.link-title { font-size: 13px; font-weight: 500; color: #111827; }
.link-alias { font-size: 11px; color: #6b7280; margin-top: 2px; }

/* Diff */
.diff-selectors {
  background: #ffffff;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.select-sm {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  background: #fff;
}

.diff-viewer {
  font-family: monospace;
  font-size: 11px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid rgba(0, 0, 0, 0.08);
}

.diff-line {
  padding: 2px 6px;
  display: flex;
  gap: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}

.diff-line.add { background: #ecfdf5; color: #065f46; }
.diff-line.del { background: #fef2f2; color: #991b1b; text-decoration: line-through; }
.diff-line.same { color: #6b7280; }

.rollback-btn-full {
  width: 100%;
  padding: 8px;
  font-size: 12px;
  border-radius: 6px;
  background: #0071e3;
  color: #fff;
  font-weight: 500;
  cursor: pointer;
  border: none;
}
.rollback-btn-full:hover { background: #0060c0; }

/* Copilot */
.copilot-box {
  display: flex;
  flex-direction: column;
  padding: 8px;
}

.copilot-mode-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.mode-chip {
  flex: 1;
  font-size: 11px;
  padding: 4px;
  border-radius: 4px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: #fff;
  color: #6b7280;
}
.mode-chip.active {
  background: #8b5cf6;
  color: #fff;
  border-color: #8b5cf6;
}

.copilot-messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px;
  min-height: 250px;
}

.chat-bubble {
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
  max-width: 90%;
}

.chat-bubble.user {
  align-self: flex-end;
  background: #0071e3;
  color: #fff;
}

.chat-bubble.assistant {
  align-self: flex-start;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  color: #1f2937;
}

.streaming-dot {
  font-size: 11px;
  color: #8b5cf6;
  animation: pulse 1s infinite;
}

.copilot-input-row {
  display: flex;
  gap: 4px;
  margin-top: 8px;
}

.copilot-input {
  flex: 1;
  font-size: 12px;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  outline: none;
}

.send-btn {
  padding: 6px 12px;
  border-radius: 6px;
  background: #8b5cf6;
  color: #fff;
  font-size: 12px;
  border: none;
  cursor: pointer;
}
.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
