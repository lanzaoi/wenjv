<template>
  <div class="chat-layout">
    <aside class="sidebar">
      <div class="side-head">
        <div class="side-title-row">
                  <div class="side-icon-wrap"><Icon name="folder" :size="18" /></div>
                  <div class="side-head-text">
                    <div class="side-head-top">
                      <h2>知识录入</h2>
                      <button
                        v-if="messages.length"
                        type="button"
                        class="btn btn-ghost btn-sm clear-chat"
                        title="清空当前对话"
                        @click="onClearChat"
                      >
                        <Icon name="x" :size="14" />
                        清空对话
                      </button>
                    </div>
                    <p class="muted tip">文件 · 图片 · 笔记 · 链接 → 异步入库</p>
                  </div>
                </div>
      </div>

      <div class="seg tabs">
        <button
          v-for="t in tabs"
          :key="t.id"
          type="button"
          :class="{ on: tab === t.id }"
          :title="t.label"
          @click="tab = t.id"
        >
          <Icon :name="t.icon" :size="15" />
          <span>{{ t.label }}</span>
        </button>
      </div>

      <div v-if="ingestMsg" class="success-banner">
        <Icon name="check" :size="15" />
        <span>{{ ingestMsg }}</span>
      </div>
      <div v-if="ingestErr" class="error-banner">
        <Icon name="x" :size="15" />
        <span>{{ ingestErr }}</span>
      </div>

      <div v-show="tab === 'file'" class="pane">
        <FileDrop
          v-model="file"
          icon="file"
          title="拖入文件或点击选择"
          subtitle="PDF · Markdown · Office · CSV…"
          :disabled="busy"
        />
        <button class="btn btn-primary btn-block" type="button" :disabled="!file || busy" @click="doUpload">
          <span v-if="busy && uploading === 'file'" class="spinner" />
          <template v-else>
            <Icon name="upload" :size="16" />
            上传入库
          </template>
        </button>
      </div>

      <div v-show="tab === 'image'" class="pane">
        <p class="hint muted">png / jpg / jpeg · OCR → 描述入库（非向量以图搜图）</p>
        <FileDrop
          v-model="imageIngestFile"
          icon="image"
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          title="拖入图片或点击选择"
          subtitle="仅 png · jpg · jpeg"
          :disabled="busy"
        />
        <button
          class="btn btn-primary btn-block"
          type="button"
          :disabled="!imageIngestFile || busy"
          @click="doImageIngest"
        >
          <span v-if="busy && uploading === 'image'" class="spinner" />
          <template v-else>
            <Icon name="image" :size="16" />
            提交图片入库
          </template>
        </button>
      </div>

      <div v-show="tab === 'note'" class="pane">
        <div class="field">
          <label>标题</label>
          <input v-model="noteTitle" placeholder="笔记标题" />
        </div>
        <div class="field">
          <label>正文</label>
          <textarea v-model="noteBody" rows="7" placeholder="Markdown / 纯文本" />
        </div>
        <button
          class="btn btn-primary btn-block"
          type="button"
          :disabled="!noteTitle || !noteBody || busy"
          @click="doNote"
        >
          <Icon name="note" :size="16" />
          保存笔记
        </button>
      </div>

      <div v-show="tab === 'link'" class="pane">
        <div class="field">
          <label>URL</label>
          <input v-model="linkUrl" type="url" placeholder="https://" />
        </div>
        <button class="btn btn-primary btn-block" type="button" :disabled="!linkUrl || busy" @click="doLink">
          <Icon name="link" :size="16" />
          提交链接
        </button>
      </div>

      <div class="t0-card">
        <div class="t0-head">
          <div class="t0-title">
            <Icon name="image-search" :size="17" />
            <h3>图问 T0</h3>
          </div>
          <span class="badge pending">图→文→Hybrid</span>
        </div>
        <p class="hint muted">查询侧转写后混合检索，不是向量以图搜图</p>
        <FileDrop
          v-model="t0File"
          icon="image-search"
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          title="拖入查询图片"
          subtitle="用于检索或对话"
          :disabled="busy"
        />
        <div class="row">
          <button class="btn btn-secondary" type="button" :disabled="!t0File || busy" @click="doT0Search">
            <Icon name="search" :size="15" />
            仅检索
          </button>
          <button class="btn btn-primary" type="button" :disabled="!t0File || busy" @click="doT0Chat">
            <Icon name="sparkles" :size="15" />
            图问对话
          </button>
        </div>
      </div>
    </aside>

    <section class="chat-main">
      <div class="toolbar glass-bar">
        <div class="seg mode-seg">
          <button type="button" :class="{ on: mode === 'rag' }" @click="mode = 'rag'">
            <Icon name="sparkles" :size="14" />
            综合解答
          </button>
          <button type="button" :class="{ on: mode === 'free' }" @click="mode = 'free'">
            <Icon name="chat" :size="14" />
            自由对话
          </button>
          <button type="button" :class="{ on: mode === 'refs' }" @click="mode = 'refs'">
            <Icon name="quote" :size="14" />
            仅引用
          </button>
        </div>
        <div class="toolbar-fields">
          <div class="field inline">
            <label>窗口</label>
            <input v-model.number="windowSize" type="number" min="1" max="50" />
          </div>
          <div class="field inline grow">
            <label>模型</label>
            <select v-model="model">
              <option value="">默认</option>
              <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>
      </div>

      <div ref="scrollEl" class="messages">
        <div v-if="!messages.length && !streaming" class="empty-state">
          <div class="empty-icon" aria-hidden="true">
            <Icon name="chat" :size="28" />
          </div>
          <h3>开始提问</h3>
          <p class="muted">先在左侧录入资料，或直接用图问 T0。回答会附带可核对的引用。</p>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="avatar" :class="m.role" aria-hidden="true">
            <Icon :name="m.role === 'user' ? 'user' : 'bot'" :size="16" />
          </div>
          <div class="bubble">
            <div class="content" v-html="renderMd(m.content)" />
            <img v-if="m.imageUrl" :src="m.imageUrl" class="msg-img" alt="" />
          </div>
        </div>

        <div v-if="streaming" class="msg assistant">
          <div class="avatar assistant" aria-hidden="true">
            <Icon name="bot" :size="16" />
          </div>
          <div class="bubble">
            <div class="content">{{ streamText }}<span class="caret" /></div>
          </div>
        </div>
      </div>

      <div v-if="citations.length" class="cites card" :class="{ collapsed: citesCollapsed }">
        <button type="button" class="cites-h" @click="citesCollapsed = !citesCollapsed">
          <span class="cites-left">
            <Icon name="quote" :size="15" />
            <span>引用</span>
            <span class="badge">{{ citations.length }}</span>
          </span>
          <Icon name="chevron-down" :size="14" class="cites-toggle" :class="{ open: !citesCollapsed }" />
        </button>
        <div v-show="!citesCollapsed" class="cites-body">
          <div v-for="(c, i) in citations" :key="i" class="cite">
            <div class="cite-top">
              <span class="score-pill">{{ scoreLabel(c.score) }}</span>
              <span class="src">{{ metaLabel(c) }}</span>
            </div>
            <p>{{ clip(c.page_content, 220) }}</p>
          </div>
        </div>
      </div>

      <form class="composer card" @submit.prevent="sendText">
        <textarea
          ref="promptEl"
          v-model="prompt"
          rows="1"
          placeholder="提出关于已录入知识的问题…"
          @keydown.enter.exact.prevent="sendText"
          @input="autoGrow"
        />
        <div class="composer-actions">
          <span class="muted kbd-hint">Enter 发送 · Shift+Enter 换行</span>
          <button
            class="btn btn-primary btn-icon send-btn"
            type="submit"
            :disabled="!prompt.trim() || busy"
            :title="busy ? '处理中…' : '发送'"
            aria-label="发送"
          >
            <span v-if="busy && streaming" class="spinner" />
            <Icon v-else name="arrow-up" :size="18" />
          </button>
        </div>
      </form>
</section>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import FileDrop from '../components/FileDrop.vue'
import Icon from '../components/Icon.vue'
import {
  uploadFile,
  createNote,
  submitLink,
  searchDocuments,
  searchByImage,
  streamChat,
  streamChatByImage,
  listChatModels,
} from '../api/client'

defineOptions({ name: 'ChatView' })

const auth = useAuthStore()
const chat = useChatStore()
const {
  messages,
  citations,
  citesCollapsed,
  mode,
  windowSize,
  model,
  models,
  prompt,
  tab,
  streaming,
  streamText,
  busy,
} = storeToRefs(chat)

const tabs = [
  { id: 'file', label: '文件', icon: 'file' },
  { id: 'image', label: '图片', icon: 'image' },
  { id: 'note', label: '笔记', icon: 'note' },
  { id: 'link', label: '链接', icon: 'link' },
]

// ingest UI stays local (not conversation context)
const uploading = ref('')
const ingestMsg = ref('')
const ingestErr = ref('')
const file = ref(null)
const imageIngestFile = ref(null)
const noteTitle = ref('')
const noteBody = ref('')
const linkUrl = ref('')
const t0File = ref(null)
const scrollEl = ref(null)
const promptEl = ref(null)
let abortCtrl = null

function autoGrow() {
  const el = promptEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

onMounted(async () => {
  if (!chat.modelsLoaded) {
    try {
      const r = await listChatModels(auth.token)
      let list = r.models || r || []
      if (Array.isArray(r)) list = r
      chat.setModels(list)
    } catch {
      chat.setModels([])
    }
  }
  await nextTick()
  autoGrow()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
})

watch([messages, streamText], async () => {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
})

function clearIngestFlash() {
  ingestMsg.value = ''
  ingestErr.value = ''
}

function onClearChat() {
  if (!messages.value.length && !citations.value.length) return
  if (!window.confirm('清空当前对话与引用？')) return
  chat.resetSession()
  nextTick(autoGrow)
}

function t0PreviewUrl() {
  if (!t0File.value) return ''
  return URL.createObjectURL(t0File.value)
}

async function doUpload() {
  clearIngestFlash()
  if (!file.value) return
  chat.busy = true
  uploading.value = 'file'
  try {
    const r = await uploadFile(auth.token, file.value)
    ingestMsg.value = `已提交：${r.filename || file.value.name}（${r.status || 'queued'}）`
    file.value = null
  } catch (e) {
    ingestErr.value = e.message
  } finally {
    chat.busy = false
    uploading.value = ''
  }
}

async function doImageIngest() {
  clearIngestFlash()
  if (!imageIngestFile.value) return
  chat.busy = true
  uploading.value = 'image'
  try {
    const r = await uploadFile(auth.token, imageIngestFile.value)
    ingestMsg.value = `图片已提交：${r.filename || imageIngestFile.value.name}`
    imageIngestFile.value = null
  } catch (e) {
    ingestErr.value = e.message
  } finally {
    chat.busy = false
    uploading.value = ''
  }
}

async function doNote() {
  clearIngestFlash()
  chat.busy = true
  try {
    const r = await createNote(auth.token, noteTitle.value, noteBody.value)
    ingestMsg.value = `笔记已创建：${r.title}`
    noteTitle.value = ''
    noteBody.value = ''
  } catch (e) {
    ingestErr.value = e.message
  } finally {
    chat.busy = false
  }
}

async function doLink() {
  clearIngestFlash()
  chat.busy = true
  try {
    await submitLink(auth.token, linkUrl.value)
    ingestMsg.value = '链接已提交抓取'
    linkUrl.value = ''
  } catch (e) {
    ingestErr.value = e.message
  } finally {
    chat.busy = false
  }
}

function clip(s, n) {
  s = s || ''
  return s.length > n ? s.slice(0, n) + '…' : s
}
function scoreLabel(s) {
  if (s == null) return '—'
  return Number(s).toFixed(3)
}
function metaLabel(c) {
  const m = c.metadata || {}
  return m.title || m.filename || m.source || m.source_type || 'chunk'
}
function renderMd(text) {
  const esc = String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return esc.replace(/\n/g, '<br>')
}

async function sendText() {
  const q = prompt.value.trim()
  if (!q || busy.value) return
  prompt.value = ''
  nextTick(autoGrow)
  chat.pushMessage({ role: 'user', content: q })
  chat.clearCitations()

  if (mode.value === 'refs') {
    chat.busy = true
    try {
      const r = await searchDocuments(auth.token, q, windowSize.value)
      chat.setCitations(r.documents || [])
      chat.pushMessage({
        role: 'assistant',
        content: citations.value.length
          ? `检索到 ${citations.value.length} 条引用（见下方）。`
          : '未检索到相关片段。',
      })
    } catch (e) {
      chat.pushMessage({ role: 'assistant', content: `检索失败：${e.message}` })
    } finally {
      chat.busy = false
    }
    return
  }

  // history excludes the user message we just pushed — rebuild like before
  const hist = messages.value
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .slice(0, -1)
    .slice(-8)
    .map((m) => ({ role: m.role, content: m.content }))

  await runStreamChat({
    question: q,
    model: model.value || null,
    window_size: windowSize.value,
    use_rag: mode.value === 'rag',
    history: hist,
  })
}

async function doT0Search() {
  if (!t0File.value || busy.value) return
  const name = t0File.value.name
  const imageUrl = t0PreviewUrl()
  chat.pushMessage({
    role: 'user',
    content: `[图问·检索] ${name}`,
    imageUrl,
  })
  chat.busy = true
  chat.clearCitations()
  try {
    const r = await searchByImage(auth.token, t0File.value, windowSize.value)
    chat.setCitations(r.documents || [])
    chat.pushMessage({
      role: 'assistant',
      content: citations.value.length
        ? `图问检索到 ${citations.value.length} 条（图→文→Hybrid）。`
        : '未检索到相关片段。',
    })
  } catch (e) {
    chat.pushMessage({ role: 'assistant', content: `图问检索失败：${e.message}` })
  } finally {
    chat.busy = false
  }
}

async function doT0Chat() {
  if (!t0File.value || busy.value) return
  const name = t0File.value.name
  const imageUrl = t0PreviewUrl()
  chat.pushMessage({
    role: 'user',
    content: `[图问·对话] ${name}`,
    imageUrl,
  })
  chat.clearCitations()
  chat.beginStream()
  abortCtrl = new AbortController()
  try {
    await streamChatByImage(
      auth.token,
      t0File.value,
      {
        window_size: windowSize.value,
        use_rag: mode.value !== 'free',
        model: model.value || undefined,
      },
      onSse,
      abortCtrl.signal,
    )
    chat.endStream(true)
  } catch (e) {
    if (e.name !== 'AbortError') {
      chat.endStream(false)
      chat.pushMessage({ role: 'assistant', content: `图问对话失败：${e.message}` })
    } else {
      chat.endStream(false)
    }
  }
}

async function runStreamChat(payload) {
  chat.beginStream()
  abortCtrl = new AbortController()
  try {
    await streamChat(auth.token, payload, onSse, abortCtrl.signal)
    chat.endStream(true)
  } catch (e) {
    if (e.name !== 'AbortError') {
      chat.endStream(false)
      chat.pushMessage({ role: 'assistant', content: `对话失败：${e.message}` })
    } else {
      chat.endStream(false)
    }
  }
}

function onSse(ev) {
  if (ev.type === 'token') chat.appendStream(ev.content || '')
  else if (ev.type === 'citations') {
    chat.setCitations(
      (ev.citations || []).map((c) => ({
        page_content: c.page_content || c.snippet || '',
        score: c.score,
        metadata: c.metadata || c,
      })),
    )
  } else if (ev.type === 'error') {
    chat.appendStream(`\n[错误] ${ev.message || 'chat error'}`)
  }
}
</script>

<style scoped>
.chat-layout {
  height: 100%;
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  gap: 0;
  min-height: 0;
  background: var(--bg);
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 14px 20px;
  overflow: auto;
  min-height: 0;
  background: linear-gradient(180deg, #fbfbfd 0%, var(--bg) 40%);
  border-right: 1px solid rgba(0, 0, 0, 0.06);
}
.side-head h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.03em;
}
.tip {
  margin: 0;
}
.tabs {
  margin-bottom: 2px;
}
.pane {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hint {
  margin: 0;
  font-size: 12px;
}
.row {
  display: flex;
  gap: 8px;
}
.row .btn {
  flex: 1;
}

.t0-card {
  margin-top: 4px;
  padding: 14px;
  border-radius: var(--radius);
  background: var(--surface);
  border: 1px solid rgba(0, 0, 0, 0.05);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.t0-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.t0-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  gap: 0;
  padding: 12px 16px 16px;
}

.glass-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: saturate(180%) blur(16px);
  -webkit-backdrop-filter: saturate(180%) blur(16px);
  border: 1px solid rgba(0, 0, 0, 0.05);
  margin-bottom: 12px;
}
.mode-seg {
  flex: 0 1 auto;
  min-width: 260px;
}
.toolbar-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: end;
  flex: 1;
  justify-content: flex-end;
}
.field.inline {
  margin: 0;
  min-width: 88px;
}
.field.inline.grow {
  min-width: 160px;
  flex: 1;
  max-width: 240px;
}
.field.inline input,
.field.inline select {
  padding: 8px 10px;
  font-size: 13px;
}

.messages {
  flex: 1;
  overflow: auto;
  padding: 8px 4px 16px;
  min-height: 200px;
  scroll-behavior: smooth;
}

.empty-state {
  max-width: 360px;
  margin: 12vh auto 0;
  text-align: center;
  animation: banner-in var(--dur-panel) var(--ease-out);
}
.empty-state h3 {
  margin: 12px 0 6px;
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.03em;
}
.empty-state p {
  margin: 0;
}
.empty-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto;
  border-radius: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  box-shadow: var(--shadow-sm);
}
.empty-icon svg {
  width: 28px;
  height: 28px;
}

.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  max-width: 860px;
  animation: banner-in var(--dur-panel) var(--ease-out);
}
.msg.user {
  margin-left: auto;
  flex-direction: row-reverse;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
  letter-spacing: -0.02em;
}
.avatar.user {
  background: #e8f1fc;
  color: var(--accent);
}
.avatar.assistant {
  background: var(--text);
  color: #fff;
}
.bubble {
  max-width: min(720px, 100%);
  background: var(--surface);
  border-radius: 18px;
  padding: 12px 14px;
  box-shadow: var(--shadow-sm);
  border: 1px solid rgba(0, 0, 0, 0.04);
}
.msg.user .bubble {
  background: #e8f1fc;
  border-color: transparent;
  border-bottom-right-radius: 6px;
}
.msg.assistant .bubble {
  border-bottom-left-radius: 6px;
}
.content {
  font-size: 15px;
  line-height: 1.55;
  letter-spacing: -0.011em;
  word-break: break-word;
}
.msg-img {
  margin-top: 10px;
  max-width: min(280px, 100%);
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}
.caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--accent);
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

.cites {
  overflow: hidden;
  padding: 0;
  margin-bottom: 10px;
}
.cites-h {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  font-weight: 650;
  letter-spacing: -0.01em;
  padding: 11px 14px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text);
  text-align: left;
}
.cites-h:hover {
  background: rgba(0, 0, 0, 0.02);
}
.cites-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.cites-toggle {
  color: var(--text-tertiary);
  opacity: 0.85;
  transition: transform var(--dur-ui) var(--ease-out);
}
.cites-toggle.open {
  transform: rotate(180deg);
}
.cites-body {
  max-height: 160px;
  overflow: auto;
  padding: 0 14px 12px;
  border-top: 1px solid var(--border);
}
.cite {
  font-size: 13px;
  padding: 10px 0;
  border-top: 1px solid var(--border);
}
.cite:first-child {
  border-top: none;
}
.cite-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.score-pill {
  font-size: 11px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  padding: 2px 7px;
  border-radius: var(--pill);
  background: var(--accent-soft);
  color: var(--accent);
}
.cite .src {
  color: var(--text-secondary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cite p {
  margin: 0;
  color: var(--text);
  line-height: 1.45;
}
.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px 10px 14px;
  border-radius: 22px;
}
.composer textarea {
  border: none;
  resize: none;
  outline: none;
  background: transparent;
  min-height: 28px;
  max-height: 140px;
  font-size: 15px;
  line-height: 1.45;
  letter-spacing: -0.011em;
  overflow-y: auto;
}
.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.kbd-hint {
  font-size: 12px;
}
.send-btn :deep(.ui-icon) {
  transform: translateY(0);
}
.empty-icon {
  color: var(--text-secondary);
}
.btn :deep(.ui-icon) {
  flex-shrink: 0;
}

@media (max-width: 900px) {
  .chat-layout {
    grid-template-columns: 1fr;
  }
  .sidebar {
    max-height: 42vh;
    border-right: none;
    border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  }
  .tabs.seg button span {
    display: none;
  }
  .tabs.seg button {
    padding: 8px 10px;
  }
  .mode-seg {
    min-width: 0;
    width: 100%;
  }
  .kbd-hint {
    display: none;
  }
}

.side-title-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.side-head-text {
  min-width: 0;
  flex: 1;
}
.side-head-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.side-head-top h2 {
  margin: 0;
}
.clear-chat {
  flex-shrink: 0;
  color: var(--text-secondary) !important;
  padding: 4px 8px !important;
  font-size: 12px !important;
  gap: 4px;
}
.clear-chat:hover {
  color: var(--danger) !important;
  background: rgba(255, 59, 48, 0.08) !important;
}
.side-icon-wrap {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  color: var(--accent);
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
}
.seg button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
}
.success-banner,
.error-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.t0-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
}
.t0-title :deep(.ui-icon) {
  color: var(--accent);
}
.avatar {
  font-size: 0;
}
.avatar.user {
  color: var(--accent);
}
.avatar.assistant {
  color: #fff;
}
.cites-h {
  display: flex;
  align-items: center;
  gap: 6px;
}
.empty-icon {
  color: var(--text-secondary);
}
.btn :deep(.ui-icon) {
  flex-shrink: 0;
}

</style>

