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
                        v-if="messages.length && !confirmingClear"
                        type="button"
                        class="btn btn-ghost btn-sm clear-chat"
                        title="清空当前对话"
                        @click="confirmingClear = true"
                      >
                        <Icon name="x" :size="14" />
                        清空对话
                      </button>
                      <div v-else-if="messages.length && confirmingClear" class="clear-confirm-inline">
                        <button type="button" class="btn btn-ghost btn-sm clear-chat is-confirm" @click="confirmClearChat">
                          确认清空
                        </button>
                        <button type="button" class="btn btn-ghost btn-sm clear-chat" @click="confirmingClear = false">
                          取消
                        </button>
                      </div>
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
        <div class="field tag-field">
          <input v-model="uploadTags" placeholder="初始标签 (选填，逗号/空格分隔)" />
        </div>
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
        <div class="field tag-field">
          <input v-model="uploadTags" placeholder="初始标签 (选填，逗号/空格分隔)" />
        </div>
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
        <div class="field">
          <label>标签 (选填)</label>
          <input v-model="noteTags" placeholder="标签，逗号/空格分隔" />
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
        <div class="field">
          <label>标签 (选填)</label>
          <input v-model="linkTags" placeholder="标签，逗号/空格分隔" />
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
            <h3>多模态图搜</h3>
          </div>
          <span class="badge" style="background: rgba(34, 197, 94, 0.15); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.3);">SigLIP 2 + Hybrid</span>
        </div>
        <p class="hint muted">真以图搜图（SigLIP 2 视觉向量）+ OCR 混合检索</p>
        <FileDrop
          v-model="t0File"
          icon="image-search"
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          title="拖入查询图片"
          subtitle="支持直接视觉比对与图文对话"
          :disabled="busy"
        />
        <div v-if="t0File" style="margin-top: 8px;">
          <input
            v-model="t0Prompt"
            class="input"
            type="text"
            placeholder="附加提示词/问题（可选，留空则纯图检索）"
            style="font-size: 12px; padding: 6px 10px; width: 100%; box-sizing: border-box;"
          />
        </div>
        <div class="row" style="margin-top: 10px;">
          <button class="btn btn-secondary" type="button" :disabled="!t0File || busy" @click="doT0Search">
            <Icon name="search" :size="15" />
            以图搜图
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
            <div v-if="m.role === 'assistant'" class="msg-actions">
              <button
                type="button"
                class="save-to-wiki-btn"
                @click="saveMsgToWiki(m.content)"
                title="将此回答沉淀为 Wiki 知识库页面"
              >
                📌 沉淀至 Wiki
              </button>
            </div>
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
              <span v-if="isWikiCite(c)" class="tag-status-badge matched wiki-badge" @click.stop="openWikiCite(c)">
                Wiki 页面
              </span>
              <span v-else-if="c.tag_matched || c.metadata?.tag_matched" class="tag-status-badge matched">标签命中</span>
              <span v-else-if="c.tag_fallback || c.metadata?.tag_fallback" class="tag-status-badge fallback">全库补充</span>
              <span class="src" :class="{ 'is-wiki-link': isWikiCite(c) }" @click="openWikiCite(c)">
                {{ metaLabel(c) }}
              </span>
            </div>
            <div
              v-if="getCitationImageUrl(c)"
              class="cite-img-wrap"
              title="点击查看原图"
              @click="previewImage(getCitationImageUrl(c))"
            >
              <img :src="getCitationImageUrl(c)" class="cite-img" alt="引用图表" loading="lazy" />
              <div class="cite-img-hint"><Icon name="image" :size="13" /> 点击查看大图</div>
            </div>
            <p>{{ clip(c.page_content, 220) }}</p>
          </div>
        </div>
      </div>

      <!-- Quick Tag Filter Pills for Chat -->
      <div v-if="availableTags.length" class="chat-tags-row">
        <span class="chat-tags-label"><Icon name="tag" :size="12" />限定标签:</span>
        <button
          v-for="t in availableTags"
          :key="t.name"
          type="button"
          class="chat-tag-chip"
          :class="{ selected: selectedTags.includes(t.name) }"
          @click="toggleSelectedTag(t.name)"
        >
          #{{ t.name }}
        </button>
        <button
          v-if="selectedTags.length"
          type="button"
          class="chat-tag-clear"
          @click="selectedTags = []"
        >
          清除
        </button>
      </div>

      <form class="composer card" @submit.prevent="sendText">
        <!-- Attached image thumbnail overlay in composer -->
        <div v-if="attachedImage" class="composer-attachment-preview">
          <div class="attachment-thumb-wrap">
            <img :src="attachedImage.preview_url" class="attachment-thumb" alt="待发送图片" />
            <button type="button" class="attachment-remove-btn" @click="removeAttachedImage" title="移除图片">
              <Icon name="x" :size="14" />
            </button>
          </div>
          <span class="attachment-name">{{ attachedImage.name }}</span>
        </div>

        <textarea
          ref="promptEl"
          v-model="prompt"
          rows="1"
          placeholder="提出问题，或粘贴/上传截图直接对话…"
          @keydown.enter.exact.prevent="sendText"
          @input="autoGrow"
          @paste="handlePaste"
        />
        <div class="composer-actions">
          <input
            ref="fileInputEl"
            type="file"
            accept="image/*"
            style="display: none"
            @change="onFileSelected"
          />
          <button
            class="btn btn-ghost btn-icon attach-btn"
            type="button"
            :disabled="busy || uploadingAttachment"
            title="上传图片"
            aria-label="上传图片"
            @click="fileInputEl && fileInputEl.click()"
          >
            <span v-if="uploadingAttachment" class="spinner" />
            <Icon v-else name="image" :size="18" />
          </button>
          <span class="muted kbd-hint">可直接粘贴截图 · Enter 发送</span>
          <button
            v-if="streaming"
            class="btn btn-secondary btn-sm stop-btn"
            type="button"
            title="停止生成"
            @click="stopStreaming"
          >
            停止生成
          </button>
          <button
            class="btn btn-primary btn-icon send-btn"
            type="submit"
            :disabled="(!prompt.trim() && !attachedImage) || busy || uploadingAttachment"
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

  <!-- Save Message to Wiki Modal (non-blocking replacement for window.prompt) -->
  <Teleport to="body">
    <div v-if="showWikiSaveModal" class="wiki-save-backdrop" @click.self="closeWikiSaveModal">
      <div class="wiki-save-dialog" role="dialog" aria-modal="true" aria-label="沉淀至 Wiki">
        <h4>沉淀至 Wiki 知识库</h4>
        <p class="wiki-save-sub">将该回答保存为结构化 Wiki 页面，后续可继续编辑与建立双向链接。</p>
        <div v-if="wikiSaveErr" class="error-banner" style="margin-bottom: 10px">{{ wikiSaveErr }}</div>
        <div v-if="wikiSavedPage" class="success-banner" style="margin-bottom: 12px">
          <Icon name="check" :size="15" />
          <span>已保存至「{{ wikiSavedPage.title }}」</span>
        </div>
        <div v-if="!wikiSavedPage" class="field">
          <label for="wiki-save-title">页面标题</label>
          <input
            id="wiki-save-title"
            v-model="wikiSaveTitle"
            placeholder="请输入 Wiki 页面标题"
            :disabled="wikiSaving"
            @keydown.enter.prevent="confirmSaveToWiki"
          />
        </div>
        <div class="wiki-save-actions">
          <button type="button" class="btn btn-secondary btn-sm" :disabled="wikiSaving" @click="closeWikiSaveModal">
            {{ wikiSavedPage ? '留在对话' : '取消' }}
          </button>
          <button
            v-if="wikiSavedPage"
            type="button"
            class="btn btn-primary btn-sm"
            @click="goToSavedWikiPage"
          >
            前往 Wiki 查看
          </button>
          <button
            v-else
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="!wikiSaveTitle.trim() || wikiSaving"
            @click="confirmSaveToWiki"
          >
            {{ wikiSaving ? '保存中…' : '确认保存' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Image Preview Modal -->
  <Teleport to="body">
    <div v-if="previewModalUrl" class="modal-backdrop" @click="previewModalUrl = null">
      <div class="modal-content" @click.stop>
        <button class="modal-close" type="button" @click="previewModalUrl = null" aria-label="关闭预览">
          <Icon name="x" :size="24" />
        </button>
        <img :src="previewModalUrl" class="modal-img" alt="原图大图预览" />
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onActivated, onBeforeUnmount, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
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
  uploadChatAttachment,
  listChatModels,
  getTags,
  wikiApi,
} from '../api/client'

defineOptions({ name: 'ChatView' })

const router = useRouter()
const route = useRoute()
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
  selectedTags,
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
const t0Prompt = ref('')
const scrollEl = ref(null)
const promptEl = ref(null)
const fileInputEl = ref(null)
let abortCtrl = null

// Composer attached image
const attachedImage = ref(null)
const uploadingAttachment = ref(false)

async function onFileSelected(e) {
  const f = e.target.files?.[0]
  if (!f) return
  await handleAttachFile(f)
  if (fileInputEl.value) fileInputEl.value.value = ''
}

async function handleAttachFile(f) {
  if (!f.type.startsWith('image/')) {
    alert('请选择图片文件')
    return
  }
  uploadingAttachment.value = true
  try {
    const res = await uploadChatAttachment(auth.token, f)
    attachedImage.value = {
      media_url: res.media_url,
      preview_url: URL.createObjectURL(f),
      name: f.name,
    }
  } catch (err) {
    alert(`图片上传失败: ${err.message}`)
  } finally {
    uploadingAttachment.value = false
  }
}

function removeAttachedImage() {
  if (attachedImage.value?.preview_url) {
    URL.revokeObjectURL(attachedImage.value.preview_url)
  }
  attachedImage.value = null
}

function handlePaste(e) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) {
        handleAttachFile(f)
        e.preventDefault()
        break
      }
    }
  }
}

// Tagging state
const availableTags = ref([])
const uploadTags = ref('')
const noteTags = ref('')
const linkTags = ref('')
const confirmingClear = ref(false)
const createdBlobUrls = []

// Wiki Save Modal state
const showWikiSaveModal = ref(false)
const wikiSaveTitle = ref('')
const wikiSaveContent = ref('')
const wikiSaving = ref(false)
const wikiSaveErr = ref('')
const wikiSavedPage = ref(null)

function toggleSelectedTag(tagName) {
  const idx = selectedTags.value.indexOf(tagName)
  if (idx >= 0) {
    selectedTags.value.splice(idx, 1)
  } else {
    selectedTags.value.push(tagName)
  }
}

async function loadChatTags() {
  try {
    const res = await getTags(auth.token, 25)
    availableTags.value = res.tags || []
  } catch (e) {
    // ignore
  }
}

function parseInputTags(str) {
  if (!str) return undefined
  const arr = str.split(/[,，\s]+/).map(s => s.trim().replace(/^#+/, '')).filter(Boolean)
  return arr.length ? arr : undefined
}

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
  await loadChatTags()
  await nextTick()
  autoGrow()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
})

watch([messages, streamText], async () => {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}, { deep: true })

onActivated(async () => {
  void loadChatTags()
  await nextTick()
  autoGrow()
  if (scrollEl.value && (streaming.value || messages.value.length > 0)) {
    scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  }
})

onBeforeUnmount(() => {
  if (abortCtrl) {
    abortCtrl.abort()
    abortCtrl = null
  }
  for (const url of createdBlobUrls) {
    URL.revokeObjectURL(url)
  }
  createdBlobUrls.length = 0
})

function clearIngestFlash() {
  ingestMsg.value = ''
  ingestErr.value = ''
}

function confirmClearChat() {
  confirmingClear.value = false
  if (!messages.value.length && !citations.value.length) return
  chat.resetSession()
  nextTick(autoGrow)
}

function stopStreaming() {
  if (abortCtrl) {
    abortCtrl.abort()
    abortCtrl = null
  }
}

function t0PreviewUrl() {
  if (!t0File.value) return ''
  const url = URL.createObjectURL(t0File.value)
  createdBlobUrls.push(url)
  return url
}

async function doUpload() {
  clearIngestFlash()
  if (!file.value) return
  chat.busy = true
  uploading.value = 'file'
  try {
    const r = await uploadFile(auth.token, file.value, parseInputTags(uploadTags.value))
    ingestMsg.value = `已提交：${r.filename || file.value.name}（${r.status || 'queued'}）`
    file.value = null
    uploadTags.value = ''
    loadChatTags()
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
    const r = await uploadFile(auth.token, imageIngestFile.value, parseInputTags(uploadTags.value))
    ingestMsg.value = `图片已提交：${r.filename || imageIngestFile.value.name}`
    imageIngestFile.value = null
    uploadTags.value = ''
    loadChatTags()
  } catch (e) {
    ingestErr.value = e.message
  } finally {
    chat.busy = false
    uploading.value = ''
  }
}

function saveMsgToWiki(content) {
  if (!content) return
  const firstLine = content.trim().split('\n')[0].replace(/^[#\s*>-]+/, '').trim()
  wikiSaveContent.value = content
  wikiSaveTitle.value = firstLine.slice(0, 40) || '知识总结'
  wikiSaveErr.value = ''
  wikiSavedPage.value = null
  showWikiSaveModal.value = true
}

function closeWikiSaveModal() {
  if (wikiSaving.value) return
  showWikiSaveModal.value = false
}

async function confirmSaveToWiki() {
  const title = wikiSaveTitle.value.trim()
  if (!title || wikiSaving.value) return
  wikiSaving.value = true
  wikiSaveErr.value = ''
  try {
    const page = await wikiApi.createPage({ title, content: wikiSaveContent.value }, auth.token)
    wikiSavedPage.value = page
  } catch (err) {
    wikiSaveErr.value = err?.message || String(err)
  } finally {
    wikiSaving.value = false
  }
}

function goToSavedWikiPage() {
  const pageId = wikiSavedPage.value?.id
  showWikiSaveModal.value = false
  if (pageId) {
    router.push({ name: 'wiki', params: { id: String(pageId) } })
  } else {
    router.push({ name: 'wiki' })
  }
}

async function doNote() {
  clearIngestFlash()
  chat.busy = true
  try {
    const r = await createNote(auth.token, noteTitle.value, noteBody.value, parseInputTags(noteTags.value))
    ingestMsg.value = `笔记已创建：${r.title}`
    noteTitle.value = ''
    noteBody.value = ''
    noteTags.value = ''
    loadChatTags()
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
    await submitLink(auth.token, linkUrl.value, {}, parseInputTags(linkTags.value))
    ingestMsg.value = '链接已提交抓取'
    linkUrl.value = ''
    linkTags.value = ''
    loadChatTags()
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
  if (s == null) return '-'
  return Number(s).toFixed(3)
}
function metaLabel(c) {
  const m = c.metadata || {}
  return m.title || m.filename || m.source || m.source_type || 'chunk'
}
function isWikiCite(c) {
  const m = c.metadata || {}
  const fn = m.filename || c.filename || ''
  const st = m.source_type || c.source_type || ''
  return st === 'wiki' || fn.startsWith('wiki://')
}

function openWikiCite(c) {
  if (!isWikiCite(c)) return
  const m = c.metadata || {}
  const resId = m.resource_id || c.resource_id
  if (resId) {
    router.push({ name: 'wiki', params: { id: resId } })
  } else {
    router.push({ name: 'wiki' })
  }
}

function safeWindowSize() {
  const n = Number(windowSize.value)
  if (isNaN(n) || n < 1) return 5
  return Math.min(50, Math.floor(n))
}

function renderMd(text) {
  if (!text) return ''
  const codeBlocks = []
  let processed = String(text).replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
    const id = `__CODE_BLOCK_${codeBlocks.length}__`
    const escCode = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    codeBlocks.push(`<pre class="code-block"><code class="language-${lang || 'text'}">${escCode}</code></pre>`)
    return id
  })

  processed = processed
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  processed = processed.replace(/^### (.+)$/gm, '<h4 class="md-h">$1</h4>')
  processed = processed.replace(/^## (.+)$/gm, '<h3 class="md-h">$1</h3>')
  processed = processed.replace(/^# (.+)$/gm, '<h2 class="md-h">$1</h2>')
  processed = processed.replace(/^&gt; (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  processed = processed.replace(/^[-*] (.+)$/gm, '<div class="md-li">• $1</div>')
  processed = processed.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>')
  processed = processed.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  processed = processed.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  processed = processed.replace(
    /\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="chat-link">$1</a>'
  )
  processed = processed.replace(/\n/g, '<br>')
  processed = processed.replace(/(<\/(?:h[234]|blockquote|div)>)<br>/g, '$1')

  codeBlocks.forEach((block, idx) => {
    processed = processed.replace(`__CODE_BLOCK_${idx}__`, block)
  })

  return processed
}

async function sendText() {
  const q = prompt.value.trim()
  const img = attachedImage.value
  if ((!q && !img) || busy.value) return

  prompt.value = ''
  nextTick(autoGrow)

  const effectiveText = q || '请详细分析这张图片。'
  chat.pushMessage({
    role: 'user',
    content: effectiveText,
    imageUrl: img ? getCitationImageUrl({ image_url: img.media_url }) : undefined,
    mediaUrl: img ? img.media_url : undefined,
  })
  chat.clearCitations()

  const attachedMediaUrl = img ? img.media_url : undefined
  removeAttachedImage()

  if (mode.value === 'refs') {
    chat.busy = true
    try {
      const r = await searchDocuments(
        auth.token,
        effectiveText,
        safeWindowSize(),
        null,
        selectedTags.value.length ? selectedTags.value : null,
      )
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

  // history excludes the user message we just pushed
  const hist = chat.historyForApi.slice(0, -1)

  await runStreamChat({
    question: effectiveText,
    model: model.value || null,
    window_size: safeWindowSize(),
    use_rag: mode.value === 'rag',
    tags: selectedTags.value.length ? selectedTags.value : undefined,
    history: hist,
    images: attachedMediaUrl ? [attachedMediaUrl] : undefined,
  })
}

async function doT0Search() {
  if (!t0File.value || busy.value) return
  const name = t0File.value.name
  const imageUrl = t0PreviewUrl()
  const customPrompt = t0Prompt.value.trim()
  chat.pushMessage({
    role: 'user',
    content: customPrompt ? `[以图搜图] ${name}\n提示：${customPrompt}` : `[以图搜图] ${name}`,
    imageUrl,
  })
  chat.busy = true
  chat.clearCitations()
  try {
    const r = await searchByImage(auth.token, t0File.value, safeWindowSize(), customPrompt)
    chat.setCitations(r.documents || [])
    chat.pushMessage({
      role: 'assistant',
      content: citations.value.length
        ? `检索到 ${citations.value.length} 条关联依据（含 SigLIP 2 视觉向量匹配与图文混合结果，见下方卡片）。`
        : '未检索到视觉或文本相关片段。',
    })
  } catch (e) {
    chat.pushMessage({ role: 'assistant', content: `以图搜图失败：${e.message}` })
  } finally {
    chat.busy = false
  }
}

async function doT0Chat() {
  if (!t0File.value || busy.value) return
  const name = t0File.value.name
  const imageUrl = t0PreviewUrl()
  const customPrompt = t0Prompt.value.trim()
  chat.pushMessage({
    role: 'user',
    content: customPrompt ? `[图问对话] ${name}\n${customPrompt}` : `[图问对话] ${name}`,
    imageUrl,
  })
  chat.clearCitations()
  chat.beginStream()
  abortCtrl = new AbortController()
  try {
    const hist = chat.historyForApi
    await streamChatByImage(
      auth.token,
      t0File.value,
      {
        prompt: customPrompt || undefined,
        window_size: safeWindowSize(),
        use_rag: mode.value !== 'free',
        model: model.value || undefined,
        history: hist && hist.length > 0 ? JSON.stringify(hist) : undefined,
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

const previewModalUrl = ref(null)

function previewImage(url) {
  previewModalUrl.value = url
}

function getCitationImageUrl(c) {
  if (!c) return null
  const url = typeof c === 'string' ? c : (c.image_url || c.metadata?.image_url)
  if (!url) return null
  if (url.startsWith('blob:') || url.startsWith('data:')) return url
  if (url.includes('token=')) return url
  if (!auth.token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(auth.token)}`
}

function onSse(ev) {
  if (ev.type === 'token') chat.appendStream(ev.content || '')
  else if (ev.type === 'citations') {
    chat.setCitations(
      (ev.citations || []).map((c) => ({
        page_content: c.page_content || c.snippet || '',
        score: c.score,
        tag_matched: c.tag_matched ?? c.metadata?.tag_matched,
        tag_fallback: c.tag_fallback ?? c.metadata?.tag_fallback,
        has_image: c.has_image ?? c.metadata?.has_image,
        image_url: c.image_url ?? c.metadata?.image_url,
        image_path: c.image_path ?? c.metadata?.image_path,
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
  font-size: 0;
  flex-shrink: 0;
}
.avatar.user {
  background: #e8f1fc;
  color: var(--accent);
}
.avatar.assistant {
  background: var(--text);
  color: #fff;
}

.tag-field {
  margin-top: 10px;
  margin-bottom: 12px;
}

.inline-code {
  background: var(--bg-hover, #f0f0f4);
  color: var(--text, #1d1d1f);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.code-block {
  background: #1c1c1e;
  color: #f2f2f7;
  padding: 12px 14px;
  border-radius: var(--radius-xs, 8px);
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  margin: 8px 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.chat-link {
  color: var(--link, #0066cc);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.chat-link:hover {
  color: var(--accent-hover, #0077ed);
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
.tag-status-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
}
.tag-status-badge.matched {
  background: rgba(46, 125, 50, 0.1);
  color: #2e7d32;
  border: 1px solid rgba(46, 125, 50, 0.25);
}
.tag-status-badge.fallback {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}
.chat-tags-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.chat-tags-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-right: 2px;
}
.chat-tag-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 9999px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--dur-ui) var(--ease-out);
}
.chat-tag-chip:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text);
}
.chat-tag-chip.selected {
  background: var(--text);
  color: #fff;
  border-color: var(--text);
}
.chat-tag-clear {
  font-size: 11px;
  color: var(--text-tertiary);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
}
.chat-tag-clear:hover {
  color: var(--text);
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
.btn :deep(.ui-icon) {
  flex-shrink: 0;
}

/* Citation Image Thumbnail & Zoom */
.cite-img-wrap {
  margin: 8px 0;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--bg-hover);
  cursor: pointer;
  position: relative;
  display: inline-block;
  max-width: 100%;
}
.cite-img {
  display: block;
  max-height: 180px;
  max-width: 100%;
  object-fit: contain;
  background: #fff;
  transition: transform 0.2s ease;
}
.cite-img-wrap:hover .cite-img {
  transform: scale(1.02);
}
.cite-img-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 8px;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.cite-img-wrap:hover .cite-img-hint {
  opacity: 1;
}

/* High-res Image Modal Backdrop */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 24px;
  backdrop-filter: blur(4px);
}
.modal-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.modal-img {
  max-width: 100%;
  max-height: 85vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  background: #fff;
}
.modal-close {
  position: absolute;
  top: -38px;
  right: -10px;
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.modal-close:hover {
  opacity: 0.8;
}

/* Composer Attachment Preview */
.composer-attachment-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--surface-secondary, rgba(0, 0, 0, 0.03));
  border-bottom: 1px solid var(--border);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
}
.attachment-thumb-wrap {
  position: relative;
  width: 48px;
  height: 48px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: #fff;
  flex-shrink: 0;
}
.attachment-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.attachment-remove-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  border: none;
  cursor: pointer;
  display: grid;
  place-items: center;
  padding: 0;
}
.attachment-remove-btn:hover {
  background: rgba(255, 59, 48, 0.9);
}
.attachment-name {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}
.attach-btn {
  color: var(--text-secondary);
  margin-right: auto;
}
.attach-btn:hover {
  color: var(--accent);
  background: rgba(0, 113, 227, 0.08);
}

.clear-confirm-inline {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.clear-chat.is-confirm {
  color: var(--danger) !important;
  font-weight: 600;
}
.wiki-badge {
  cursor: pointer;
}
.src.is-wiki-link {
  color: var(--accent);
  cursor: pointer;
}
.src.is-wiki-link:hover {
  text-decoration: underline;
}
.md-h {
  margin: 8px 0 4px;
  font-weight: 650;
  line-height: 1.35;
}
.md-quote {
  margin: 6px 0;
  padding: 4px 10px;
  border-left: 3px solid var(--border-strong);
  color: var(--text-secondary);
}
.md-li {
  padding-left: 6px;
  margin: 2px 0;
}
.wiki-save-backdrop {
  position: fixed;
  inset: 0;
  z-index: 260;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.wiki-save-dialog {
  width: min(420px, 94vw);
  background: var(--surface, #ffffff);
  border-radius: 14px;
  border: 1px solid var(--border, #e5e5ea);
  box-shadow: var(--shadow-lg);
  padding: 20px;
}
.wiki-save-dialog h4 {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 650;
}
.wiki-save-sub {
  margin: 0 0 14px;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.wiki-save-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>

