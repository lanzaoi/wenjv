<template>
  <main class="wiki-editor-panel">
    <!-- Empty State -->
    <div v-if="!page" class="editor-empty-state">
      <div class="empty-card">
        <div class="empty-badge">Wiki</div>
        <h2>选择或创建一个知识页面</h2>
        <p>支持树形目录组织、Markdown 实时分栏、双向链接（[[页面]]）、图片嵌入与版本回溯。</p>
        <div class="empty-quick-actions">
          <button type="button" class="primary-pill-btn" @click="$emit('create-first-page')">
            新建知识页面
          </button>
          <button type="button" class="secondary-pill-btn" @click="$emit('open-search')">
            快速搜索 (⌘K)
          </button>
        </div>
      </div>
    </div>

    <!-- Active Editor -->
    <template v-else>
      <!-- Top Bar -->
      <header class="editor-topbar">
        <div class="topbar-left">
          <button
            type="button"
            class="panel-toggle-btn"
            :class="{ 'is-active': !treeCollapsed }"
            title="切换左侧目录"
            @click="$emit('toggle-tree')"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>

          <nav class="breadcrumbs" aria-label="页面路径">
            <span class="crumb-root">知识库</span>
            <template v-for="crumb in breadcrumbs" :key="crumb.id">
              <span class="crumb-sep">/</span>
              <button
                type="button"
                class="crumb-link"
                @click="$emit('select-page', crumb.id)"
              >
                {{ crumb.title }}
              </button>
            </template>
            <span class="crumb-sep">/</span>
            <span class="crumb-current">{{ localTitle || '未命名页面' }}</span>
          </nav>
        </div>

        <div class="topbar-right">
          <!-- Save Status -->
          <span v-if="saving" class="save-badge is-saving">保存中...</span>
          <span v-else-if="saveError" class="save-badge is-error" :title="saveError">保存异常</span>
          <span v-else-if="dirty" class="save-badge is-dirty">未保存</span>
          <span v-else-if="lastSavedAt" class="save-badge is-saved">已保存 {{ lastSavedAt }}</span>

          <button
            type="button"
            class="save-now-btn"
            :disabled="saving || (!dirty && !conflictDetected)"
            title="立即保存 (⌘S / Ctrl+S)"
            @click="$emit('flush-save')"
          >
            保存
          </button>

          <div class="mode-segmented">
            <button
              type="button"
              :class="['mode-seg-btn', { 'is-active': viewMode === 'edit' }]"
              @click="viewMode = 'edit'"
            >
              编辑
            </button>
            <button
              type="button"
              :class="['mode-seg-btn', { 'is-active': viewMode === 'split' }]"
              @click="viewMode = 'split'"
            >
              分栏
            </button>
            <button
              type="button"
              :class="['mode-seg-btn', { 'is-active': viewMode === 'preview' }]"
              @click="viewMode = 'preview'"
            >
              预览
            </button>
          </div>

          <button
            type="button"
            class="panel-toggle-btn"
            :class="{ 'is-active': !sidebarCollapsed }"
            title="切换右侧大纲与助手栏"
            @click="$emit('toggle-sidebar')"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="15" y1="3" x2="15" y2="21" />
            </svg>
          </button>
        </div>
      </header>

      <!-- Conflict / Error Banner -->
      <div v-if="conflictDetected || saveError" class="editor-alert-banner" :class="{ 'is-conflict': conflictDetected }">
        <div class="alert-message">
          <strong>{{ conflictDetected ? '版本冲突' : '保存提示' }}：</strong>
          <span>{{ saveError }}</span>
        </div>
        <div class="alert-actions">
          <button
            v-if="conflictDetected"
            type="button"
            class="alert-btn"
            @click="$emit('reload-page')"
          >
            加载最新版本
          </button>
          <button
            v-if="conflictDetected"
            type="button"
            class="alert-btn is-primary"
            @click="$emit('force-save')"
          >
            强制覆盖保存
          </button>
          <button
            v-else
            type="button"
            class="alert-btn is-primary"
            @click="$emit('flush-save')"
          >
            重试保存
          </button>
        </div>
      </div>

      <!-- Inline Upload Error / Notice -->
      <div v-if="localNotice" class="editor-notice-banner">
        <span>{{ localNotice }}</span>
        <button type="button" class="notice-close" @click="localNotice = null">×</button>
      </div>

      <!-- Document Header: Icon + Title + Tags -->
      <div class="doc-meta-header">
        <div class="title-row">
          <div class="icon-picker-wrap">
            <button
              type="button"
              class="doc-icon-btn"
              title="更换页面图标"
              @click="showIconPicker = !showIconPicker"
            >
              <span v-if="localIcon">{{ localIcon }}</span>
              <svg
                v-else
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </button>
            <div v-if="showIconPicker" class="icon-popover" @click.stop>
              <button
                v-for="ico in ICON_PRESETS"
                :key="ico"
                type="button"
                class="ico-choice"
                @click="selectIcon(ico)"
              >
                {{ ico }}
              </button>
              <button type="button" class="ico-clear" @click="selectIcon('')">无图标</button>
            </div>
          </div>

          <input
            v-model="localTitle"
            type="text"
            class="doc-title-input"
            placeholder="输入页面标题..."
            @input="onTitleInput"
          />
        </div>

        <!-- Tags Bar -->
        <div class="tags-row">
          <span class="tags-label">标签</span>
          <span
            v-for="tag in localTags"
            :key="tag"
            class="tag-chip"
          >
            #{{ tag }}
            <button type="button" class="tag-remove" title="移除标签" @click="removeTag(tag)">×</button>
          </span>
          <input
            v-model="tagInput"
            type="text"
            class="tag-add-input"
            placeholder="+ 添加标签，回车确认"
            @keydown.enter.prevent="commitTagInput"
            @keydown.,.prevent="commitTagInput"
            @blur="commitTagInput"
          />
        </div>
      </div>

      <!-- Markdown Toolbar (shown in Edit & Split) -->
      <div v-if="viewMode !== 'preview'" class="md-toolbar">
        <button type="button" class="tb-btn" title="一级标题" @click="insertLinePrefix('# ')">H1</button>
        <button type="button" class="tb-btn" title="二级标题" @click="insertLinePrefix('## ')">H2</button>
        <button type="button" class="tb-btn" title="加粗" @click="wrapSelection('**', '**', '加粗文本')"><strong>B</strong></button>
        <button type="button" class="tb-btn" title="斜体" @click="wrapSelection('*', '*', '斜体文本')"><em>I</em></button>
        <button type="button" class="tb-btn" title="行内代码" @click="wrapSelection('`', '`', 'code')">&lt;/&gt;</button>
        <button type="button" class="tb-btn" title="待办清单" @click="insertLinePrefix('- [ ] ')">待办</button>
        <button type="button" class="tb-btn" title="引用块" @click="insertLinePrefix('> ')">引用</button>
        <button type="button" class="tb-btn" title="插入代码块" @click="insertCodeBlock">代码块</button>
        <span class="tb-divider" />
        <button type="button" class="tb-btn is-link-tool" title="插入双向链接 [[" @click="triggerWikilinkMenu">
          [[ 双链
        </button>
        <button type="button" class="tb-btn" title="上传并嵌入图片" :disabled="uploadingImg" @click="triggerImageUpload">
          {{ uploadingImg ? '上传中...' : '插入图片' }}
        </button>
        <input
          ref="imageInputRef"
          type="file"
          accept=".jpg,.jpeg,.png,.webp"
          hidden
          @change="handleImageInputChange"
        />
        <span class="tb-hint">输入 `/` 唤起命令，输入 `[[` 插入页面链接，支持粘贴截图</span>
      </div>

      <!-- Editor & Preview Workspace -->
      <div class="editor-workspace" :class="`mode-${viewMode}`">
        <!-- Left/Edit Pane -->
        <div
          v-show="viewMode === 'edit' || viewMode === 'split'"
          class="textarea-pane"
          :class="{ 'is-dragover': isDraggingOver }"
          @dragover.prevent="isDraggingOver = true"
          @dragleave.prevent="isDraggingOver = false"
          @drop.prevent="handleFileDrop"
        >
          <textarea
            ref="textareaRef"
            v-model="localContent"
            class="md-textarea"
            placeholder="开始撰写知识内容... 输入 / 唤起快捷命令，[[ 链接其他页面，或直接拖拽图片上传。"
            @input="onContentInput"
            @keydown="onTextareaKeydown"
            @paste="onTextareaPaste"
            @click="closeMenus"
          />

          <!-- Dynamic Popups anchored near caret -->
          <div
            v-if="showSlashMenu && filteredSlashCommands.length > 0"
            class="floating-menu"
            :style="{ top: `${menuPos.top}px`, left: `${menuPos.left}px` }"
          >
            <div class="floating-menu-head">快捷命令</div>
            <button
              v-for="(cmd, idx) in filteredSlashCommands"
              :key="cmd.key"
              type="button"
              :class="['floating-menu-item', { 'is-selected': idx === slashIndex }]"
              @mousedown.prevent="applySlashCommand(cmd)"
            >
              <span class="cmd-title">{{ cmd.label }}</span>
              <span class="cmd-desc">{{ cmd.desc }}</span>
            </button>
          </div>

          <div
            v-if="showLinkMenu"
            class="floating-menu"
            :style="{ top: `${menuPos.top}px`, left: `${menuPos.left}px` }"
          >
            <div class="floating-menu-head">链接到页面</div>
            <button
              v-for="(p, idx) in linkCandidates"
              :key="`${p.id}-${p.title}`"
              type="button"
              :class="['floating-menu-item', { 'is-selected': idx === linkIndex }]"
              @mousedown.prevent="applyWikilink(p.title)"
            >
              <span class="cmd-title">{{ p.title }}</span>
              <span class="cmd-desc">{{ p.isNew ? '新页面链接' : '已有页面' }}</span>
            </button>
            <div v-if="!linkCandidates.length" class="floating-empty">暂无可选页面，直接输入名称即可创建引用</div>
          </div>
        </div>

        <!-- Right/Preview Pane -->
        <div
          v-show="viewMode === 'preview' || viewMode === 'split'"
          ref="previewPaneRef"
          class="preview-pane"
          @click="onPreviewClick"
          @change="onPreviewChange"
        >
          <article v-if="renderedHtml" class="wiki-prose" v-html="renderedHtml" />
          <div v-else class="preview-empty">暂无正文内容，请在左侧编辑或插入内容。</div>
        </div>
      </div>

      <!-- Subtle Footer -->
      <footer class="editor-footer">
        <span>版本 v{{ page.revision_count }}</span>
        <span class="footer-dot">·</span>
        <span>{{ charCount }} 字符 / {{ lineCount }} 行</span>
        <span v-if="page.updated_at" class="footer-dot">·</span>
        <span v-if="page.updated_at">更新于 {{ formatTimestamp(page.updated_at) }}</span>
      </footer>
    </template>

    <!-- Lightbox Modal for Embedded Visuals -->
    <div v-if="lightboxSrc" class="lightbox-backdrop" @click="lightboxSrc = null">
      <div class="lightbox-card" @click.stop>
        <img :src="lightboxSrc" alt="图片预览" class="lightbox-img" />
        <button type="button" class="lightbox-close" @click="lightboxSrc = null">关闭</button>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { wikiApi } from '../../api/client';
import { useAuthStore } from '../../stores/auth';
import type { WikiPage } from '../../stores/wiki';
import { renderMarkdown, slugifyHeading } from '../../utils/markdown';

interface PageSummaryItem {
  id: number;
  title: string;
}

interface BreadcrumbItem {
  id: number;
  title: string;
}

interface SlashCommandItem {
  key: string;
  label: string;
  desc: string;
  keywords: string[];
}

const ICON_PRESETS = ['📄', '📘', '🧠', '💡', '⚙️', '🧪', '📊', '🗂️', '✅', '📌'];

const SLASH_COMMANDS: SlashCommandItem[] = [
  { key: 'h1', label: '一级标题', desc: '# 标题', keywords: ['h1', 'heading', '标题'] },
  { key: 'h2', label: '二级标题', desc: '## 副标题', keywords: ['h2', 'subheading', '标题'] },
  { key: 'h3', label: '三级标题', desc: '### 小节', keywords: ['h3', 'section', '小节'] },
  { key: 'task', label: '待办任务', desc: '- [ ] 任务项', keywords: ['task', '待办', 'checklist'] },
  { key: 'quote', label: '引用块', desc: '> 关键摘要', keywords: ['quote', 'blockquote', '引用'] },
  { key: 'code', label: '代码块', desc: '``` 语法高亮', keywords: ['code', 'snippet', '代码'] },
  { key: 'table', label: 'Markdown 表格', desc: '双列表格模板', keywords: ['table', '表格'] },
  { key: 'link', label: '双向链接', desc: '[[选择页面]]', keywords: ['link', 'wikilink', '双链'] },
  { key: 'img', label: '上传图片', desc: '从本地选择图像', keywords: ['image', 'img', 'upload', '图片'] },
];

const props = defineProps<{
  page: WikiPage | null;
  allPages: PageSummaryItem[];
  breadcrumbs: BreadcrumbItem[];
  saving: boolean;
  dirty: boolean;
  saveError?: string | null;
  conflictDetected?: boolean;
  lastSavedAt?: string | null;
  treeCollapsed?: boolean;
  sidebarCollapsed?: boolean;
}>();

const emit = defineEmits<{
  (e: 'update-content', patch: { title?: string; content?: string; icon?: string; tags?: string[] }): void;
  (e: 'navigate-wikilink', payload: { target: string; anchor?: string }): void;
  (e: 'select-page', pageId: number): void;
  (e: 'flush-save'): void;
  (e: 'reload-page'): void;
  (e: 'force-save'): void;
  (e: 'create-first-page'): void;
  (e: 'open-search'): void;
  (e: 'toggle-tree'): void;
  (e: 'toggle-sidebar'): void;
}>();

const auth = useAuthStore();

const viewMode = ref<'edit' | 'split' | 'preview'>('split');
const localTitle = ref('');
const localContent = ref('');
const localIcon = ref('');
const localTags = ref<string[]>([]);
const tagInput = ref('');
const showIconPicker = ref(false);
const localNotice = ref<string | null>(null);
const uploadingImg = ref(false);
const isDraggingOver = ref(false);
const lightboxSrc = ref<string | null>(null);

const textareaRef = ref<HTMLTextAreaElement | null>(null);
const previewPaneRef = ref<HTMLDivElement | null>(null);
const imageInputRef = ref<HTMLInputElement | null>(null);

// Slash & Wikilink menus
const showSlashMenu = ref(false);
const slashQuery = ref('');
const slashIndex = ref(0);

const showLinkMenu = ref(false);
const linkQuery = ref('');
const linkIndex = ref(0);
const menuPos = ref({ top: 44, left: 24 });

// Sync editor state ONLY when page id or revision changes from external load/rollback
watch(
  () => props.page,
  (newPage, oldPage) => {
    if (!newPage) {
      localTitle.value = '';
      localContent.value = '';
      localIcon.value = '';
      localTags.value = [];
      return;
    }
    const switchedPage = !oldPage || oldPage.id !== newPage.id;
    // Also resync when rollback / reload changes content outside current local buffer
    if (switchedPage) {
      localTitle.value = newPage.title || '';
      localContent.value = newPage.content || '';
      localIcon.value = newPage.icon || '';
      localTags.value = Array.isArray(newPage.tags) ? [...newPage.tags] : [];
      closeMenus();
      showIconPicker.value = false;
      localNotice.value = null;
    } else if (!props.dirty) {
      if (newPage.title !== localTitle.value) localTitle.value = newPage.title || '';
      if (newPage.content !== localContent.value) localContent.value = newPage.content || '';
      if ((newPage.icon || '') !== localIcon.value) localIcon.value = newPage.icon || '';
      const serverTags = Array.isArray(newPage.tags) ? newPage.tags : [];
      if (JSON.stringify(serverTags) !== JSON.stringify(localTags.value)) {
        localTags.value = [...serverTags];
      }
    }
  },
  { immediate: true }
);

const knownTitlesSet = computed(() => new Set((props.allPages || []).map((p) => p.title.trim())));

const renderedHtml = computed(() => {
  return renderMarkdown(localContent.value, {
    assetToken: auth.token,
    knownTitles: knownTitlesSet.value,
    interactiveTasks: true,
  });
});

const charCount = computed(() => localContent.value.length);
const lineCount = computed(() => (localContent.value ? localContent.value.split('\n').length : 0));

const filteredSlashCommands = computed(() => {
  const q = slashQuery.value.trim().toLowerCase();
  if (!q) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter(
    (c) => c.label.toLowerCase().includes(q) || c.keywords.some((k) => k.includes(q))
  );
});

const linkCandidates = computed(() => {
  const q = linkQuery.value.trim();
  const qLower = q.toLowerCase();
  const currentId = props.page?.id;
  const matches = (props.allPages || [])
    .filter((p) => p.id !== currentId && (!qLower || p.title.toLowerCase().includes(qLower)))
    .slice(0, 10)
    .map((p) => ({ id: p.id, title: p.title, isNew: false }));

  if (q && !matches.some((m) => m.title.toLowerCase() === qLower) && q !== props.page?.title) {
    matches.push({ id: -1, title: q, isNew: true });
  }
  return matches;
});

function formatTimestamp(ts: string): string {
  const d = new Date(ts.includes('T') || ts.endsWith('Z') ? ts : `${ts.replace(' ', 'T')}Z`);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function onTitleInput() {
  emit('update-content', { title: localTitle.value });
}

function selectIcon(ico: string) {
  localIcon.value = ico;
  showIconPicker.value = false;
  emit('update-content', { icon: ico });
}

function commitTagInput() {
  const raw = tagInput.value.replace(/,/g, '').trim();
  tagInput.value = '';
  if (!raw) return;
  if (!localTags.value.includes(raw)) {
    localTags.value = [...localTags.value, raw];
    emit('update-content', { tags: [...localTags.value] });
  }
}

function removeTag(tag: string) {
  localTags.value = localTags.value.filter((t) => t !== tag);
  emit('update-content', { tags: [...localTags.value] });
}

function closeMenus() {
  showSlashMenu.value = false;
  showLinkMenu.value = false;
}

/**
 * Compute floating menu position near textarea cursor using a hidden mirror div.
 */
function updateMenuPosition() {
  const el = textareaRef.value;
  if (!el) return;

  const mirror = document.createElement('div');
  const style = window.getComputedStyle(el);
  const propsToCopy = [
    'boxSizing',
    'width',
    'fontFamily',
    'fontSize',
    'fontWeight',
    'lineHeight',
    'letterSpacing',
    'paddingTop',
    'paddingRight',
    'paddingBottom',
    'paddingLeft',
    'borderTopWidth',
    'borderLeftWidth',
  ] as const;

  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.wordWrap = 'break-word';
  mirror.style.overflow = 'hidden';
  mirror.style.top = '0';
  mirror.style.left = '0';

  for (const p of propsToCopy) {
    mirror.style[p] = style[p];
  }

  const pos = el.selectionStart || 0;
  const textBefore = el.value.slice(0, pos);
  mirror.textContent = textBefore;

  const marker = document.createElement('span');
  marker.textContent = '\u200b';
  mirror.appendChild(marker);

  document.body.appendChild(mirror);
  const topInEditor = marker.offsetTop - el.scrollTop + 26;
  const leftInEditor = marker.offsetLeft - el.scrollLeft;
  document.body.removeChild(mirror);

  const maxLeft = Math.max(16, el.clientWidth - 260);
  const maxTop = Math.max(24, el.clientHeight - 220);
  menuPos.value = {
    top: Math.min(Math.max(16, topInEditor), maxTop),
    left: Math.min(Math.max(16, leftInEditor), maxLeft),
  };
}

function onContentInput() {
  emit('update-content', { content: localContent.value });
  detectTriggers();
}

function detectTriggers() {
  const el = textareaRef.value;
  if (!el) return;
  const pos = el.selectionStart || 0;
  const before = localContent.value.slice(0, pos);

  // Detect active [[query (no closing ]] yet on same line)
  const linkMatch = before.match(/\[\[([^\[\]\n]*)$/);
  if (linkMatch) {
    showSlashMenu.value = false;
    showLinkMenu.value = true;
    linkQuery.value = linkMatch[1] || '';
    linkIndex.value = 0;
    updateMenuPosition();
    return;
  }

  // Detect active /query at line start or after whitespace
  const slashMatch = before.match(/(?:^|\s)\/([a-zA-Z0-9]*)$/);
  if (slashMatch) {
    showLinkMenu.value = false;
    showSlashMenu.value = true;
    slashQuery.value = slashMatch[1] || '';
    slashIndex.value = 0;
    updateMenuPosition();
    return;
  }

  closeMenus();
}

function insertAtCaret(text: string, caretOffset?: number) {
  const el = textareaRef.value;
  if (!el) {
    localContent.value += text;
    emit('update-content', { content: localContent.value });
    return;
  }
  const start = el.selectionStart;
  const end = el.selectionEnd;
  localContent.value = localContent.value.slice(0, start) + text + localContent.value.slice(end);
  emit('update-content', { content: localContent.value });

  const nextPos = caretOffset !== undefined ? start + caretOffset : start + text.length;
  nextTick(() => {
    el.focus();
    el.setSelectionRange(nextPos, nextPos);
  });
}

function wrapSelection(before: string, after: string, fallbackText: string) {
  const el = textareaRef.value;
  if (!el) return;
  const start = el.selectionStart;
  const end = el.selectionEnd;
  const selected = localContent.value.slice(start, end) || fallbackText;
  const replacement = `${before}${selected}${after}`;
  localContent.value = localContent.value.slice(0, start) + replacement + localContent.value.slice(end);
  emit('update-content', { content: localContent.value });

  nextTick(() => {
    el.focus();
    el.setSelectionRange(start + before.length, start + before.length + selected.length);
  });
}

function insertLinePrefix(prefix: string) {
  const el = textareaRef.value;
  if (!el) return;
  const start = el.selectionStart;
  const lineStart = localContent.value.lastIndexOf('\n', start - 1) + 1;
  localContent.value =
    localContent.value.slice(0, lineStart) + prefix + localContent.value.slice(lineStart);
  emit('update-content', { content: localContent.value });

  nextTick(() => {
    el.focus();
    const nextPos = start + prefix.length;
    el.setSelectionRange(nextPos, nextPos);
  });
}

function insertCodeBlock() {
  insertAtCaret('\n```ts\n// 在此输入代码\n```\n', 7);
}

function triggerWikilinkMenu() {
  if (viewMode.value === 'preview') viewMode.value = 'split';
  nextTick(() => {
    const el = textareaRef.value;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    localContent.value = localContent.value.slice(0, start) + '[[' + localContent.value.slice(end);
    emit('update-content', { content: localContent.value });

    nextTick(() => {
      el.focus();
      el.setSelectionRange(start + 2, start + 2);
      linkQuery.value = '';
      linkIndex.value = 0;
      showSlashMenu.value = false;
      showLinkMenu.value = true;
      updateMenuPosition();
    });
  });
}

function applySlashCommand(cmd: SlashCommandItem) {
  const el = textareaRef.value;
  if (!el) return;
  const pos = el.selectionStart || 0;
  const before = localContent.value.slice(0, pos);
  const slashMatch = before.match(/(\/[a-zA-Z0-9]*)$/);
  const cutStart = slashMatch ? pos - slashMatch[1]!.length : pos;
  localContent.value = localContent.value.slice(0, cutStart) + localContent.value.slice(pos);
  showSlashMenu.value = false;

  nextTick(() => {
    el.setSelectionRange(cutStart, cutStart);
    if (cmd.key === 'h1') insertAtCaret('# ');
    else if (cmd.key === 'h2') insertAtCaret('## ');
    else if (cmd.key === 'h3') insertAtCaret('### ');
    else if (cmd.key === 'task') insertAtCaret('- [ ] ');
    else if (cmd.key === 'quote') insertAtCaret('> ');
    else if (cmd.key === 'code') insertAtCaret('```\n\n```', 4);
    else if (cmd.key === 'table') insertAtCaret('\n| 项目 | 说明 |\n| --- | --- |\n| 内容 | 描述 |\n');
    else if (cmd.key === 'link') triggerWikilinkMenu();
    else if (cmd.key === 'img') triggerImageUpload();
  });
}

function applyWikilink(targetTitle: string) {
  const el = textareaRef.value;
  if (!el) return;
  const pos = el.selectionStart || 0;
  const before = localContent.value.slice(0, pos);
  const linkMatch = before.match(/\[\[([^\[\]\n]*)$/);
  const cutStart = linkMatch ? pos - linkMatch[0]!.length : pos;

  // Consume optional trailing ]] right after cursor if user typed it
  const after = localContent.value.slice(pos);
  const trailingClosed = after.startsWith(']]') ? 2 : 0;

  const inserted = `[[${targetTitle}]]`;
  localContent.value =
    localContent.value.slice(0, cutStart) + inserted + localContent.value.slice(pos + trailingClosed);

  showLinkMenu.value = false;
  emit('update-content', { content: localContent.value });

  const finalCaret = cutStart + inserted.length;
  nextTick(() => {
    el.focus();
    el.setSelectionRange(finalCaret, finalCaret);
  });
}

function onTextareaKeydown(e: KeyboardEvent) {
  if (e.isComposing) return;

  if (showSlashMenu.value && filteredSlashCommands.value.length > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      slashIndex.value = (slashIndex.value + 1) % filteredSlashCommands.value.length;
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      slashIndex.value =
        (slashIndex.value - 1 + filteredSlashCommands.value.length) % filteredSlashCommands.value.length;
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      const cmd = filteredSlashCommands.value[slashIndex.value];
      if (cmd) applySlashCommand(cmd);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      showSlashMenu.value = false;
      return;
    }
  }

  if (showLinkMenu.value && linkCandidates.value.length > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      linkIndex.value = (linkIndex.value + 1) % linkCandidates.value.length;
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      linkIndex.value = (linkIndex.value - 1 + linkCandidates.value.length) % linkCandidates.value.length;
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      const item = linkCandidates.value[linkIndex.value];
      if (item) applyWikilink(item.title);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      showLinkMenu.value = false;
      return;
    }
  }

  if (e.key === 'Tab') {
    e.preventDefault();
    insertAtCaret('  ');
  }
}

function triggerImageUpload() {
  imageInputRef.value?.click();
}

async function uploadAndInsertImage(file: File) {
  if (!props.page) return;
  localNotice.value = null;
  uploadingImg.value = true;
  try {
    const res = await wikiApi.uploadAsset(props.page.id, file, auth.token);
    if (res?.markdown_tag) {
      insertAtCaret(`\n${res.markdown_tag}\n`);
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    localNotice.value = `图片上传失败：${msg}`;
  } finally {
    uploadingImg.value = false;
  }
}

async function handleImageInputChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (file) await uploadAndInsertImage(file);
}

async function handleFileDrop(e: DragEvent) {
  isDraggingOver.value = false;
  const files = Array.from(e.dataTransfer?.files || []);
  for (const file of files) {
    if (file.type.startsWith('image/')) {
      await uploadAndInsertImage(file);
    }
  }
}

async function onTextareaPaste(e: ClipboardEvent) {
  const items = Array.from(e.clipboardData?.items || []);
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const blob = item.getAsFile();
      if (blob) {
        const ext = item.type.split('/')[1] || 'png';
        const named = new File([blob], `pasted-${Date.now()}.${ext}`, { type: item.type });
        await uploadAndInsertImage(named);
      }
      break;
    }
  }
}

function onPreviewClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null;
  if (!target) return;

  const linkBtn = target.closest('.wiki-link-btn') as HTMLElement | null;
  if (linkBtn) {
    const pageTitle = linkBtn.getAttribute('data-wiki-target') || '';
    const anchor = linkBtn.getAttribute('data-wiki-anchor') || '';
    if (pageTitle) {
      emit('navigate-wikilink', { target: pageTitle, anchor });
    }
    return;
  }

  if (target.tagName === 'IMG' && target.classList.contains('wiki-embed-img')) {
    lightboxSrc.value = (target as HTMLImageElement).src;
  }
}

function onPreviewChange(e: Event) {
  const target = e.target as HTMLInputElement | null;
  if (!target || target.type !== 'checkbox') return;
  const lineIdx = Number(target.getAttribute('data-task-line'));
  if (!Number.isInteger(lineIdx) || lineIdx < 0) return;

  const lines = localContent.value.split('\n');
  const current = lines[lineIdx];
  if (current === undefined) return;

  const updatedLine = target.checked
    ? current.replace(/^([-*]\s+\[) ([])/, '$1x$2')
    : current.replace(/^([-*]\s+\[)[xX](])/, '$1 $2');

  if (updatedLine !== current) {
    lines[lineIdx] = updatedLine;
    localContent.value = lines.join('\n');
    emit('update-content', { content: localContent.value });
  }
}

function scrollToHeading(text: string) {
  if (viewMode.value === 'edit') viewMode.value = 'split';
  nextTick(() => {
    const pane = previewPaneRef.value;
    if (!pane) return;
    const slug = slugifyHeading(text);
    const heading = pane.querySelector(`#${CSS.escape(slug)}`);
    if (heading) {
      heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
}

function insertAtCursor(snippet: string) {
  if (viewMode.value === 'preview') viewMode.value = 'split';
  nextTick(() => {
    const prefix = localContent.value && !localContent.value.endsWith('\n') ? '\n\n' : '';
    insertAtCaret(`${prefix}${snippet}\n`);
  });
}

function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
    if (props.page) {
      e.preventDefault();
      emit('flush-save');
    }
  } else if (e.key === 'Escape') {
    showIconPicker.value = false;
    lightboxSrc.value = null;
  }
}

function handleDocClick() {
  if (showIconPicker.value) showIconPicker.value = false;
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown);
  window.addEventListener('click', handleDocClick);
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleGlobalKeydown);
  window.removeEventListener('click', handleDocClick);
});

defineExpose({
  scrollToHeading,
  insertAtCursor,
});
</script>

<style scoped>
.wiki-editor-panel {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--surface, #ffffff);
  position: relative;
}

.editor-empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: #fbfbfd;
}

.empty-card {
  max-width: 440px;
  text-align: center;
  padding: 36px 28px;
  background: #ffffff;
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 14px;
}

.empty-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #0058b0;
  background: rgba(0, 113, 227, 0.1);
  padding: 3px 10px;
  border-radius: 999px;
  margin-bottom: 12px;
}

.empty-card h2 {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 650;
  color: var(--text, #1d1d1f);
}

.empty-card p {
  margin: 0 0 20px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #6e6e73);
}

.empty-quick-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
}

.primary-pill-btn {
  border: none;
  border-radius: 8px;
  background: var(--accent, #0071e3);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
  cursor: pointer;
}

.secondary-pill-btn {
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 8px;
  background: #fff;
  color: var(--text, #1d1d1f);
  font-size: 13px;
  font-weight: 500;
  padding: 8px 16px;
  cursor: pointer;
}

.editor-topbar {
  height: 46px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border, #e5e5ea);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: rgba(255, 255, 255, 0.92);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.panel-toggle-btn {
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary, #6e6e73);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}

.panel-toggle-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text, #1d1d1f);
}

.panel-toggle-btn.is-active {
  background: rgba(0, 113, 227, 0.08);
  color: #0058b0;
}

.breadcrumbs {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
  min-width: 0;
  overflow: hidden;
}

.crumb-root,
.crumb-sep {
  flex-shrink: 0;
}

.crumb-link {
  border: none;
  background: transparent;
  padding: 2px 4px;
  border-radius: 4px;
  font-size: 12px;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
  white-space: nowrap;
}

.crumb-link:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text, #1d1d1f);
}

.crumb-current {
  color: var(--text, #1d1d1f);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.save-badge {
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.save-badge.is-saving {
  background: #eff6ff;
  color: #1d4ed8;
}

.save-badge.is-saved {
  background: #f2f2f7;
  color: var(--text-secondary, #6e6e73);
}

.save-badge.is-dirty {
  background: #fffbeb;
  color: #b45309;
}

.save-badge.is-error {
  background: #fff1f2;
  color: #be123c;
}

.save-now-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text, #1d1d1f);
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 7px;
  cursor: pointer;
}

.save-now-btn:hover:not(:disabled) {
  border-color: var(--accent, #0071e3);
  color: var(--accent, #0071e3);
}

.save-now-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.mode-segmented {
  display: inline-flex;
  background: #f2f2f7;
  padding: 2px;
  border-radius: 8px;
}

.mode-seg-btn {
  border: none;
  background: transparent;
  font-size: 12px;
  padding: 4px 9px;
  border-radius: 6px;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
}

.mode-seg-btn.is-active {
  background: #fff;
  color: var(--text, #1d1d1f);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.editor-alert-banner {
  padding: 8px 18px;
  background: #fff5f5;
  border-bottom: 1px solid rgba(255, 59, 48, 0.25);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
  color: #9e1c1c;
  flex-shrink: 0;
}

.editor-alert-banner.is-conflict {
  background: #fffbeb;
  border-bottom-color: rgba(245, 158, 11, 0.35);
  color: #92400e;
}

.alert-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.alert-btn {
  border: 1px solid rgba(0, 0, 0, 0.16);
  background: #fff;
  color: var(--text, #1d1d1f);
  border-radius: 6px;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
}

.alert-btn.is-primary {
  background: var(--accent, #0071e3);
  border-color: transparent;
  color: #fff;
}

.editor-notice-banner {
  padding: 7px 18px;
  background: #fff5f5;
  border-bottom: 1px solid rgba(255, 59, 48, 0.2);
  color: #b42318;
  font-size: 12.5px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.notice-close {
  border: none;
  background: transparent;
  font-size: 16px;
  color: inherit;
  cursor: pointer;
}

.doc-meta-header {
  padding: 18px 24px 10px;
  flex-shrink: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon-picker-wrap {
  position: relative;
}

.doc-icon-btn {
  width: 36px;
  height: 36px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: #f5f5f7;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
}

.doc-icon-btn:hover {
  border-color: var(--border, #d1d1d6);
  background: #ececf0;
}

.icon-popover {
  position: absolute;
  top: 42px;
  left: 0;
  z-index: 40;
  width: 224px;
  padding: 8px;
  background: #fff;
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 10px;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ico-choice {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 18px;
  cursor: pointer;
}

.ico-choice:hover {
  background: #f2f2f7;
}

.ico-clear {
  width: 100%;
  margin-top: 4px;
  border: 1px solid var(--border, #e5e5ea);
  background: #fbfbfd;
  border-radius: 6px;
  padding: 4px;
  font-size: 11.5px;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
}

.doc-title-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  font-size: 24px;
  font-weight: 700;
  color: var(--text, #1d1d1f);
  letter-spacing: -0.02em;
  background: transparent;
}

.tags-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.tags-label {
  font-size: 11.5px;
  color: var(--text-tertiary, #86868b);
  margin-right: 2px;
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f2f2f7;
  color: #3a3a3c;
  font-size: 11.5px;
}

.tag-remove {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  line-height: 1;
  color: #86868b;
  cursor: pointer;
}

.tag-remove:hover {
  color: #1d1d1f;
}

.tag-add-input {
  border: 1px dashed transparent;
  background: transparent;
  font-size: 12px;
  color: var(--text, #1d1d1f);
  padding: 2px 6px;
  border-radius: 6px;
  min-width: 120px;
  outline: none;
}

.tag-add-input:focus {
  border-color: var(--border, #d1d1d6);
  background: #fbfbfd;
}

.md-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 20px;
  border-top: 1px solid var(--border, #e5e5ea);
  border-bottom: 1px solid var(--border, #e5e5ea);
  background: #fbfbfd;
  flex-shrink: 0;
}

.tb-btn {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary, #515154);
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
}

.tb-btn:hover:not(:disabled) {
  background: #e5e5ea;
  color: var(--text, #1d1d1f);
}

.tb-btn.is-link-tool {
  color: #0058b0;
  font-weight: 500;
}

.tb-divider {
  width: 1px;
  height: 14px;
  background: var(--border, #d1d1d6);
  margin: 0 4px;
}

.tb-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-tertiary, #86868b);
}

.editor-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
}

.textarea-pane {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border, #e5e5ea);
}

.mode-edit .textarea-pane {
  border-right: none;
}

.textarea-pane.is-dragover {
  background: rgba(0, 113, 227, 0.04);
}

.md-textarea {
  flex: 1;
  width: 100%;
  box-sizing: border-box;
  border: none;
  outline: none;
  resize: none;
  padding: 20px 24px 36px;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  font-size: 14px;
  line-height: 1.72;
  color: var(--text, #1d1d1f);
  background: transparent;
}

.floating-menu {
  position: absolute;
  z-index: 50;
  width: 248px;
  max-height: 260px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 10px;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.14);
  padding: 5px;
}

.floating-menu-head {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary, #86868b);
  padding: 4px 8px 5px;
}

.floating-menu-item {
  width: 100%;
  border: none;
  background: transparent;
  border-radius: 7px;
  padding: 7px 9px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text, #1d1d1f);
  cursor: pointer;
  text-align: left;
}

.floating-menu-item:hover,
.floating-menu-item.is-selected {
  background: rgba(0, 113, 227, 0.1);
  color: #0058b0;
}

.cmd-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.cmd-desc {
  font-size: 11px;
  color: var(--text-tertiary, #86868b);
  flex-shrink: 0;
}

.floating-empty {
  padding: 10px 8px;
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
}

.preview-pane {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 22px 28px 40px;
  background: #ffffff;
}

.preview-empty {
  color: var(--text-tertiary, #86868b);
  font-size: 13.5px;
  padding-top: 24px;
}

.wiki-prose {
  max-width: 780px;
  color: var(--text, #1d1d1f);
  font-size: 15px;
  line-height: 1.75;
}

.wiki-prose :deep(h1),
.wiki-prose :deep(h2),
.wiki-prose :deep(h3),
.wiki-prose :deep(h4) {
  margin-top: 1.3em;
  margin-bottom: 0.45em;
  font-weight: 650;
  line-height: 1.35;
  color: var(--text, #1d1d1f);
}

.wiki-prose :deep(h1) {
  font-size: 1.55em;
  border-bottom: 1px solid #f0f0f3;
  padding-bottom: 0.25em;
}

.wiki-prose :deep(h2) {
  font-size: 1.28em;
}

.wiki-prose :deep(h3) {
  font-size: 1.1em;
}

.wiki-prose :deep(p) {
  margin: 0.65em 0;
}

.wiki-prose :deep(ul),
.wiki-prose :deep(ol) {
  padding-left: 1.5em;
  margin: 0.6em 0;
}

.wiki-prose :deep(blockquote) {
  margin: 0.9em 0;
  padding: 8px 14px;
  border-left: 3px solid var(--accent, #0071e3);
  background: #f5f5f7;
  color: #3a3a3c;
  border-radius: 0 7px 7px 0;
}

.wiki-prose :deep(code) {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 0.88em;
  background: #f2f2f7;
  padding: 1px 5px;
  border-radius: 4px;
  color: #1d1d1f;
}

.wiki-prose :deep(pre.code-block) {
  background: #1d1d1f;
  color: #f5f5f7;
  padding: 12px 14px;
  border-radius: 9px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.55;
}

.wiki-prose :deep(pre.code-block code) {
  background: transparent;
  color: inherit;
  padding: 0;
}

.wiki-prose :deep(.table-wrap) {
  overflow-x: auto;
  margin: 1em 0;
}

.wiki-prose :deep(.markdown-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}

.wiki-prose :deep(.markdown-table th),
.wiki-prose :deep(.markdown-table td) {
  border: 1px solid var(--border, #e5e5ea);
  padding: 7px 11px;
  text-align: left;
}

.wiki-prose :deep(.markdown-table th) {
  background: #f5f5f7;
  font-weight: 600;
}

.wiki-prose :deep(.task-item) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 5px 0;
  cursor: pointer;
}

.wiki-prose :deep(.task-item.is-done span) {
  text-decoration: line-through;
  color: var(--text-tertiary, #86868b);
}

.wiki-prose :deep(.wiki-link-btn) {
  border: none;
  background: rgba(0, 113, 227, 0.09);
  color: #0058b0;
  font-size: 0.94em;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s ease;
}

.wiki-prose :deep(.wiki-link-btn:hover) {
  background: rgba(0, 113, 227, 0.16);
}

.wiki-prose :deep(.wiki-link-btn.is-missing) {
  background: rgba(201, 74, 56, 0.08);
  color: #b43b2a;
  border-bottom: 1px dashed #c94a38;
}

.wiki-prose :deep(.wiki-visual-embed) {
  margin: 12px 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.wiki-prose :deep(.wiki-embed-img) {
  max-width: 100%;
  max-height: 440px;
  border-radius: 9px;
  border: 1px solid var(--border, #e5e5ea);
  cursor: zoom-in;
}

.wiki-prose :deep(.wiki-embed-caption) {
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
}

.editor-footer {
  height: 28px;
  padding: 0 20px;
  border-top: 1px solid var(--border, #e5e5ea);
  background: #fbfbfd;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-tertiary, #86868b);
  flex-shrink: 0;
}

.lightbox-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.lightbox-card {
  position: relative;
  background: #fff;
  padding: 10px;
  border-radius: 12px;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.lightbox-img {
  max-width: 85vw;
  max-height: 78vh;
  border-radius: 8px;
  display: block;
}

.lightbox-close {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text, #1d1d1f);
  border-radius: 7px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
}
</style>
