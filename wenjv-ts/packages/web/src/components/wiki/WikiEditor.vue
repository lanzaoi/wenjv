<template>
  <main class="wiki-editor-panel">
    <!-- Breadcrumbs & Status Bar -->
    <header class="editor-header">
      <div class="breadcrumb-trail">
        <span class="path-seg">Wiki</span>
        <span class="path-sep">/</span>
        <span class="path-current">{{ page?.title || '未选择页面' }}</span>
      </div>

      <div class="header-right-actions">
        <!-- View Mode Switcher -->
        <div v-if="page" class="view-mode-pills">
          <button
            type="button"
            :class="['mode-btn', viewMode === 'edit' ? 'active' : '']"
            @click="viewMode = 'edit'"
            title="纯编辑模式"
          >
            编辑
          </button>
          <button
            type="button"
            :class="['mode-btn', viewMode === 'split' ? 'active' : '']"
            @click="viewMode = 'split'"
            title="双栏分屏实时预览"
          >
            分栏
          </button>
          <button
            type="button"
            :class="['mode-btn', viewMode === 'preview' ? 'active' : '']"
            @click="viewMode = 'preview'"
            title="纯净阅读预览"
          >
            阅读
          </button>
        </div>

        <div class="save-status">
          <span v-if="saving" class="status-indicator saving">
            <span class="pulse-dot"></span> 保存中...
          </span>
          <span v-else-if="dirty" class="status-indicator dirty">有未保存更改</span>
          <span v-else class="status-indicator saved">已同步至 SQLite & FTS5</span>
        </div>
      </div>
    </header>

    <!-- Editor Canvas -->
    <div v-if="page" class="editor-main-layout">
      <!-- Title Bar -->
      <div class="editor-title-container">
        <input
          ref="titleInputRef"
          type="text"
          class="title-input"
          v-model="titleModel"
          placeholder="无标题页面"
          @input="onTitleInput"
        />

        <!-- Format Toolbar (Visible in edit or split mode) -->
        <div v-if="viewMode !== 'preview'" class="format-toolbar">
          <button type="button" class="tool-btn" @click="insertSnippet('**', '**', '粗体')" title="粗体 (Ctrl+B)"><b>B</b></button>
          <button type="button" class="tool-btn" @click="insertSnippet('*', '*', '斜体')" title="斜体 (Ctrl+I)"><i>I</i></button>
          <span class="tool-sep"></span>
          <button type="button" class="tool-btn" @click="insertLinePrefix('# ')" title="一级标题">H1</button>
          <button type="button" class="tool-btn" @click="insertLinePrefix('## ')" title="二级标题">H2</button>
          <button type="button" class="tool-btn" @click="insertLinePrefix('### ')" title="三级标题">H3</button>
          <span class="tool-sep"></span>
          <button type="button" class="tool-btn" @click="insertLinePrefix('- ')" title="无序列表">• 列表</button>
          <button type="button" class="tool-btn" @click="insertLinePrefix('- [ ] ')" title="待办清单">☑ 待办</button>
          <button type="button" class="tool-btn" @click="insertLinePrefix('> ')" title="引用块">“ 引用</button>
          <button type="button" class="tool-btn" @click="insertSnippet('```\n', '\n```', '代码')" title="代码块">&lt;/&gt;</button>
          <button type="button" class="tool-btn" @click="insertTable" title="插入表格">表格</button>
          <button type="button" class="tool-btn" @click="triggerAssetUpload" title="上传插入图片">🖼️ 图片</button>
          <button type="button" class="tool-btn" @click="exportMarkdown" title="导出本地 .md 文件">💾 导出</button>
          <span class="tool-sep"></span>
          <button type="button" class="tool-btn highlight" @click="triggerWikilinkMenu" title="插入双链 [[">[[ 双向链接</button>
          <input
            ref="fileInputRef"
            type="file"
            accept="image/*"
            style="display: none"
            @change="onAssetFileSelected"
          />
        </div>
      </div>

      <!-- Split / Single View Body -->
      <div class="editor-panes" :class="`mode-${viewMode}`">
        <!-- Left / Edit Pane -->
        <div v-show="viewMode !== 'preview'" class="pane edit-pane">
          <div class="textarea-container">
            <textarea
              ref="textareaRef"
              class="content-textarea"
              v-model="contentModel"
              placeholder="输入 Markdown 内容... 输入 / 呼出快捷指令，输入 [[ 快速关联其他页面"
              @input="onContentInput"
              @keydown="onKeydown"
              @paste="onPaste"
              @scroll="onEditorScroll"
            ></textarea>

            <!-- Slash Command Popup -->
            <div v-if="showSlashMenu" class="slash-popup">
              <div class="popup-title">基础格式块</div>
              <div
                v-for="(item, idx) in slashCommands"
                :key="item.label"
                :class="['popup-item', slashIndex === idx ? 'active' : '']"
                @click="applySlash(item)"
              >
                <span class="item-icon">{{ item.icon }}</span>
                <div class="item-info">
                  <div class="item-label">{{ item.label }}</div>
                  <div class="item-desc">{{ item.desc }}</div>
                </div>
              </div>
            </div>

            <!-- Wikilink Autocomplete Popup -->
            <div v-if="showLinkMenu" class="slash-popup">
              <div class="popup-title">选择关联 Wiki 页面</div>
              <div v-if="!linkCandidates.length" class="popup-empty">无匹配页面</div>
              <div
                v-for="(cand, idx) in linkCandidates"
                :key="cand.id"
                :class="['popup-item', linkIndex === idx ? 'active' : '']"
                @click="applyWikilink(cand)"
              >
                <span class="item-icon">📄</span>
                <div class="item-label">{{ cand.title }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Right / Preview Pane -->
        <div
          v-show="viewMode !== 'edit'"
          ref="previewPaneRef"
          class="pane preview-pane markdown-body"
          @click="onPreviewClick"
          v-html="renderedHtml"
        ></div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="editor-empty">
      <div class="empty-icon">📖</div>
      <div class="empty-text">在左侧目录选择或新建一个页面开始写作</div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { wikiApi } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

const props = defineProps({
  page: { type: Object, default: null },
  saving: { type: Boolean, default: false },
  dirty: { type: Boolean, default: false },
  allPages: { type: Array, default: () => [] },
})

const emit = defineEmits(['update', 'toc-change', 'navigate-page', 'create-page'])

const isSyncingScroll = ref(false)

function onEditorScroll() {
  if (viewMode.value !== 'split' || !textareaRef.value || !previewPaneRef.value) return
  if (isSyncingScroll.value) return

  const ta = textareaRef.value
  const pv = previewPaneRef.value
  const taScrollable = ta.scrollHeight - ta.clientHeight
  const pvScrollable = pv.scrollHeight - pv.clientHeight

  if (taScrollable > 0 && pvScrollable > 0) {
    const ratio = ta.scrollTop / taScrollable
    isSyncingScroll.value = true
    pv.scrollTop = ratio * pvScrollable
    requestAnimationFrame(() => {
      isSyncingScroll.value = false
    })
  }
}

async function onPaste(e) {
  const clipboardData = e.clipboardData
  if (!clipboardData || !props.page) return

  const items = clipboardData.items
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.indexOf('image') !== -1) {
      e.preventDefault()
      const file = items[i].getAsFile()
      if (file) {
        uploadingAsset.value = true
        try {
          const auth = useAuthStore()
          const res = await wikiApi.uploadAsset(props.page.id, file, auth.token)
          if (res && res.markdown_tag) {
            insertSnippet(`\n${res.markdown_tag}\n`)
          }
        } catch (err) {
          alert(`粘贴图片上传失败: ${err.message || err}`)
        } finally {
          uploadingAsset.value = false
        }
      }
      break
    }
  }
}

function exportMarkdown() {
  if (!props.page) return
  const blob = new Blob([contentModel.value || ''], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.page.title || 'untitled'}.md`
  a.click()
  URL.revokeObjectURL(url)
}

const viewMode = ref('split') // 'edit' | 'split' | 'preview'
const titleModel = ref('')
const contentModel = ref('')
const textareaRef = ref(null)
const titleInputRef = ref(null)
const previewPaneRef = ref(null)
const fileInputRef = ref(null)
const uploadingAsset = ref(false)

// Popups state
const showSlashMenu = ref(false)
const slashIndex = ref(0)
const showLinkMenu = ref(false)
const linkIndex = ref(0)
const linkQuery = ref('')
const lastCursorPos = ref(0)

const slashCommands = [
  { icon: 'H1', label: '一级标题', desc: '大章节标题', snippet: '# ' },
  { icon: 'H2', label: '二级标题', desc: '中章节标题', snippet: '## ' },
  { icon: 'H3', label: '三级标题', desc: '小章节标题', snippet: '### ' },
  { icon: '•', label: '无序列表', desc: '项目符号列表', snippet: '- ' },
  { icon: '☑', label: '待办清单', desc: '交互式任务选框', snippet: '- [ ] ' },
  { icon: '“', label: '引用块', desc: '标注引用内容', snippet: '> ' },
  { icon: '<>', label: '代码块', desc: '语法高亮代码', snippet: '```\n\n```' },
  { icon: '田', label: '表格', desc: '标准 Markdown 表格', snippet: '| 列 1 | 列 2 |\n|---|---|\n| 单元格 1 | 单元格 2 |' },
  { icon: '📄', label: '关联双链', desc: '双向引用 Wiki 页面', snippet: '[[' },
]

const linkCandidates = computed(() => {
  if (!linkQuery.value) return props.allPages.slice(0, 8)
  const q = linkQuery.value.toLowerCase()
  return props.allPages.filter((p) => p.title.toLowerCase().includes(q)).slice(0, 8)
})

const renderedHtml = computed(() => {
  return renderMarkdown(contentModel.value)
})

function extractTOC(text) {
  if (!text) return []
  const lines = text.split('\n')
  const toc = []
  for (const ln of lines) {
    const m = ln.match(/^(#{1,3})\s+(.+)$/)
    if (m) {
      toc.push({ level: m[1].length, text: m[2].trim() })
    }
  }
  return toc
}

watch(
  () => props.page,
  (newPage) => {
    if (newPage) {
      titleModel.value = newPage.title || ''
      contentModel.value = newPage.content || ''
      emit('toc-change', extractTOC(newPage.content))

      // Focus title if it's default untitled
      if (newPage.title === '未命名页面' || newPage.title === '未命名子页面') {
        nextTick(() => {
          titleInputRef.value?.focus()
          titleInputRef.value?.select()
        })
      }
    } else {
      titleModel.value = ''
      contentModel.value = ''
      emit('toc-change', [])
    }
    showSlashMenu.value = false
    showLinkMenu.value = false
  },
  { immediate: true }
)

function onTitleInput() {
  emit('update', { title: titleModel.value })
}

function onContentInput() {
  const val = contentModel.value
  const pos = textareaRef.value?.selectionStart || 0
  lastCursorPos.value = pos

  emit('update', { content: val })
  emit('toc-change', extractTOC(val))

  // Trigger [[ detection
  const textBefore = val.slice(0, pos)
  const linkMatch = textBefore.match(/\[\[([^\[\]]*)$/)
  if (linkMatch) {
    showLinkMenu.value = true
    showSlashMenu.value = false
    linkQuery.value = linkMatch[1]
    linkIndex.value = 0
    return
  } else {
    showLinkMenu.value = false
  }

  // Trigger / detection (start of line or after space)
  const lastChar = val[pos - 1]
  const prevChar = val[pos - 2]
  if (lastChar === '/' && (!prevChar || prevChar === '\n' || prevChar === ' ')) {
    showSlashMenu.value = true
    slashIndex.value = 0
  } else if (showSlashMenu.value && (lastChar === ' ' || lastChar === '\n')) {
    showSlashMenu.value = false
  }
}

function onKeydown(e) {
  // Shortcut: Ctrl+B or Cmd+B for bold
  if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
    e.preventDefault()
    insertSnippet('**', '**', '粗体')
    return
  }
  // Shortcut: Ctrl+I or Cmd+I for italic
  if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
    e.preventDefault()
    insertSnippet('*', '*', '斜体')
    return
  }

  if (showSlashMenu.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      slashIndex.value = (slashIndex.value + 1) % slashCommands.length
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      slashIndex.value = (slashIndex.value - 1 + slashCommands.length) % slashCommands.length
    } else if (e.key === 'Enter') {
      e.preventDefault()
      applySlash(slashCommands[slashIndex.value])
    } else if (e.key === 'Escape') {
      showSlashMenu.value = false
    }
  } else if (showLinkMenu.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      linkIndex.value = (linkIndex.value + 1) % (linkCandidates.value.length || 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      linkIndex.value =
        (linkIndex.value - 1 + (linkCandidates.value.length || 1)) %
        (linkCandidates.value.length || 1)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (linkCandidates.value[linkIndex.value]) {
        applyWikilink(linkCandidates.value[linkIndex.value])
      }
    } else if (e.key === 'Escape') {
      showLinkMenu.value = false
    }
  }
}

function insertSnippet(prefix, suffix = '', defaultText = '') {
  const el = textareaRef.value
  if (!el) return
  const start = el.selectionStart
  const end = el.selectionEnd
  const selected = contentModel.value.slice(start, end) || defaultText
  const replacement = prefix + selected + suffix
  const before = contentModel.value.slice(0, start)
  const after = contentModel.value.slice(end)

  contentModel.value = before + replacement + after
  emit('update', { content: contentModel.value })
  emit('toc-change', extractTOC(contentModel.value))

  nextTick(() => {
    el.focus()
    const cursorPos = start + prefix.length + selected.length
    el.setSelectionRange(cursorPos, cursorPos)
  })
}

function insertLinePrefix(prefix) {
  const el = textareaRef.value
  if (!el) return
  const start = el.selectionStart
  const val = contentModel.value
  const lineStart = val.lastIndexOf('\n', start - 1) + 1
  const before = val.slice(0, lineStart)
  const after = val.slice(lineStart)

  contentModel.value = before + prefix + after
  emit('update', { content: contentModel.value })
  emit('toc-change', extractTOC(contentModel.value))

  nextTick(() => {
    el.focus()
    const pos = start + prefix.length
    el.setSelectionRange(pos, pos)
  })
}

function insertTable() {
  insertSnippet(
    '\n| 标题 1 | 标题 2 | 标题 3 |\n|---|---|---|\n| 内容 A | 内容 B | 内容 C |\n'
  )
}

function triggerAssetUpload() {
  if (fileInputRef.value) {
    fileInputRef.value.click()
  }
}

async function onAssetFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file || !props.page) return
  const auth = useAuthStore()
  uploadingAsset.value = true
  try {
    const res = await wikiApi.uploadAsset(props.page.id, file, auth.token)
    if (res && res.markdown_tag) {
      insertSnippet(`\n${res.markdown_tag}\n`)
    }
  } catch (err) {
    alert(`图片上传失败: ${err.message || err}`)
  } finally {
    uploadingAsset.value = false
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

function triggerWikilinkMenu() {
  insertSnippet('[[', ']]', '')
  showLinkMenu.value = true
  linkQuery.value = ''
  linkIndex.value = 0
}

function applySlash(cmd) {
  const el = textareaRef.value
  if (!el) return
  const pos = (el.selectionStart > 0) ? el.selectionStart : (lastCursorPos.value || 0)
  const textBefore = contentModel.value.slice(0, pos)
  // Ensure we actually replace the '/' right before cursor
  let dropCount = 0
  if (textBefore.endsWith('/')) {
    dropCount = 1
  }
  const before = contentModel.value.slice(0, pos - dropCount)
  const after = contentModel.value.slice(pos)
  contentModel.value = before + cmd.snippet + after
  showSlashMenu.value = false
  emit('update', { content: contentModel.value })
  emit('toc-change', extractTOC(contentModel.value))
  setTimeout(() => {
    el.focus()
    el.setSelectionRange(before.length + cmd.snippet.length, before.length + cmd.snippet.length)
  }, 10)
}

function applyWikilink(cand) {
  const el = textareaRef.value
  if (!el) return
  const pos = (el.selectionStart > 0) ? el.selectionStart : (lastCursorPos.value || 0)
  const textBefore = contentModel.value.slice(0, pos)
  const match = textBefore.match(/\[\[([^\[\]]*)$/)
  if (match) {
    const replaceStart = pos - match[0].length
    const before = contentModel.value.slice(0, replaceStart)
    const after = contentModel.value.slice(pos)
    const tag = `[[${cand.title}]]`
    contentModel.value = before + tag + after
    showLinkMenu.value = false
    emit('update', { content: contentModel.value })
    emit('toc-change', extractTOC(contentModel.value))
    setTimeout(() => {
      el.focus()
      el.setSelectionRange(before.length + tag.length, before.length + tag.length)
    }, 10)
  }
}

function onPreviewClick(e) {
  const btn = e.target.closest('.wiki-link-btn')
  if (btn) {
    e.preventDefault()
    const targetTitle = btn.getAttribute('data-wiki-target')
    const anchor = btn.getAttribute('data-wiki-anchor')
    if (targetTitle) {
      const found = props.allPages.find(
        (p) => p.title.toLowerCase() === targetTitle.toLowerCase() || p.slug === targetTitle
      )
      if (found) {
        emit('navigate-page', found.id)
      } else {
        // Red Link: prompt to create immediately!
        if (confirm(`页面 "${targetTitle}" 尚未创建，是否立即创建并打开？`)) {
          emit('create-page', targetTitle)
        }
      }
    }
  }
}

function scrollToHeading(headingText) {
  // If in preview or split mode, scroll preview element
  if (viewMode.value !== 'edit' && previewPaneRef.value) {
    const headings = previewPaneRef.value.querySelectorAll('h1, h2, h3, h4, h5, h6')
    for (const h of headings) {
      if (h.textContent.trim().includes(headingText.trim())) {
        h.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
    }
  }

  // Otherwise scroll textarea
  const el = textareaRef.value
  if (!el) return
  const text = contentModel.value
  const idx = text.indexOf(headingText)
  if (idx !== -1) {
    el.focus()
    el.setSelectionRange(idx, idx + headingText.length)
    const linesBefore = text.slice(0, idx).split('\n').length
    const approxLineHeight = 24
    el.scrollTop = Math.max(0, (linesBefore - 2) * approxLineHeight)
  }
}

defineExpose({
  scrollToHeading,
})
</script>

<style scoped>
.wiki-editor-panel {
  flex: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  position: relative;
  overflow: hidden;
}

.editor-header {
  height: 48px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fafafa;
}

.breadcrumb-trail {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #6b7280;
}

.path-sep {
  color: #d1d5db;
}

.path-current {
  color: #111827;
  font-weight: 500;
}

.header-right-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.view-mode-pills {
  display: flex;
  background: #f3f4f6;
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}

.mode-btn {
  border: none;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.mode-btn:hover {
  color: #111827;
}

.mode-btn.active {
  background: #ffffff;
  color: #0071e3;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.save-status {
  font-size: 12px;
}

.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.status-indicator.saved {
  color: #10b981;
}

.status-indicator.dirty {
  color: #f59e0b;
}

.status-indicator.saving {
  color: #0071e3;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0071e3;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.editor-main-layout {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: calc(100% - 48px);
  overflow: hidden;
}

.editor-title-container {
  padding: 20px 28px 12px 28px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.title-input {
  font-size: 26px;
  font-weight: 700;
  color: #111827;
  border: none;
  outline: none;
  background: transparent;
  width: 100%;
  margin-bottom: 10px;
}

.title-input::placeholder {
  color: #d1d5db;
}

.format-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.tool-btn {
  border: 1px solid transparent;
  background: transparent;
  padding: 3px 7px;
  border-radius: 4px;
  font-size: 12px;
  color: #4b5563;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover {
  background: #f3f4f6;
  color: #111827;
}

.tool-btn.highlight {
  color: #4f46e5;
  font-weight: 500;
  background: #eef2ff;
}

.tool-btn.highlight:hover {
  background: #e0e7ff;
}

.tool-sep {
  width: 1px;
  height: 14px;
  background: #e5e7eb;
  margin: 0 4px;
}

.editor-panes {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.editor-panes.mode-split .pane {
  flex: 1;
  width: 50%;
}

.editor-panes.mode-edit .edit-pane {
  flex: 1;
  width: 100%;
}

.editor-panes.mode-preview .preview-pane {
  flex: 1;
  width: 100%;
}

.pane {
  height: 100%;
  overflow-y: auto;
  padding: 24px 28px;
}

.edit-pane {
  border-right: 1px solid rgba(0, 0, 0, 0.06);
}

.textarea-container {
  height: 100%;
  position: relative;
  display: flex;
  flex-direction: column;
}

.content-textarea {
  flex: 1;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.8;
  color: #374151;
  background: transparent;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.content-textarea::placeholder {
  color: #9ca3af;
}

/* Preview Pane Styling */
.preview-pane {
  font-size: 14.5px;
  line-height: 1.75;
  color: #1f2937;
}

:deep(.preview-pane h1) {
  font-size: 22px;
  font-weight: 700;
  margin: 20px 0 10px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid #f3f4f6;
}

:deep(.preview-pane h2) {
  font-size: 18px;
  font-weight: 600;
  margin: 18px 0 8px 0;
  padding-bottom: 4px;
  border-bottom: 1px solid #f3f4f6;
}

:deep(.preview-pane h3) {
  font-size: 15px;
  font-weight: 600;
  margin: 14px 0 6px 0;
}

:deep(.preview-pane p) {
  margin: 8px 0;
}

:deep(.preview-pane blockquote) {
  margin: 10px 0;
  padding: 8px 16px;
  border-left: 3px solid #6366f1;
  background: #f8fafc;
  color: #4b5563;
  border-radius: 0 4px 4px 0;
}

:deep(.preview-pane ul),
:deep(.preview-pane ol) {
  padding-left: 20px;
  margin: 8px 0;
}

:deep(.preview-pane li) {
  margin: 4px 0;
}

:deep(.preview-pane code) {
  background: #f3f4f6;
  padding: 2px 5px;
  border-radius: 4px;
  font-size: 13px;
  font-family: monospace;
  color: #e11d48;
}

:deep(.preview-pane pre.code-block) {
  background: #1e293b;
  color: #f8fafc;
  padding: 12px 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 12px 0;
}

:deep(.preview-pane pre.code-block code) {
  background: transparent;
  color: inherit;
  padding: 0;
  font-size: 13px;
}

:deep(.table-wrap) {
  overflow-x: auto;
  margin: 14px 0;
}

:deep(.markdown-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

:deep(.markdown-table th),
:deep(.markdown-table td) {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  text-align: left;
}

:deep(.markdown-table th) {
  background: #f9fafb;
  font-weight: 600;
}

:deep(.task-item) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
}

:deep(.wiki-link-btn) {
  border: none;
  background: #eef2ff;
  color: #4f46e5;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
  vertical-align: middle;
}

:deep(.wiki-link-btn:hover) {
  background: #e0e7ff;
  color: #3730a3;
  text-decoration: underline;
}

/* Popups */
.slash-popup {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 260px;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.1);
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.12);
  border-radius: 8px;
  padding: 6px;
  z-index: 50;
}

.popup-title {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  padding: 6px 8px 4px 8px;
}

.popup-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.popup-item:hover,
.popup-item.active {
  background: rgba(79, 70, 229, 0.08);
}

.item-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #4b5563;
}

.item-label {
  font-size: 13px;
  font-weight: 500;
  color: #111827;
}

.item-desc {
  font-size: 11px;
  color: #9ca3af;
}

.popup-empty {
  padding: 12px;
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
}

.editor-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  gap: 12px;
}

.empty-icon {
  font-size: 36px;
}

.empty-text {
  font-size: 14px;
}
</style>
