<template>
  <aside class="wiki-sidebar-panel">
    <!-- Tabs Header -->
    <div class="sidebar-tabs" role="tablist">
      <button
        type="button"
        role="tab"
        :class="['tab-btn', { 'is-active': activeTab === 'toc' }]"
        @click="activeTab = 'toc'"
      >
        大纲
      </button>
      <button
        type="button"
        role="tab"
        :class="['tab-btn', { 'is-active': activeTab === 'backlinks' }]"
        @click="openBacklinksTab"
      >
        反链 ({{ backlinks.length }})
      </button>
      <button
        type="button"
        role="tab"
        :class="['tab-btn', { 'is-active': activeTab === 'diff' }]"
        @click="openDiffTab"
      >
        历史
      </button>
      <button
        type="button"
        role="tab"
        :class="['tab-btn', { 'is-active': activeTab === 'copilot' }]"
        @click="activeTab = 'copilot'"
      >
        助手
      </button>
    </div>

    <!-- 1. TOC Tab -->
    <div v-if="activeTab === 'toc'" class="tab-content">
      <div v-if="!toc.length" class="empty-state">当前文档暂无标题层级（使用 # / ## 添加）</div>
      <div v-else class="toc-list">
        <button
          v-for="(item, idx) in toc"
          :key="`${idx}-${item.text}`"
          type="button"
          :class="['toc-item', `level-${item.level}`]"
          @click="$emit('scroll-to-heading', item.text)"
        >
          {{ item.text }}
        </button>
      </div>
    </div>

    <!-- 2. Backlinks & Unlinked Mentions Tab -->
    <div v-else-if="activeTab === 'backlinks'" class="tab-content">
      <div v-if="sidebarError" class="sidebar-error">{{ sidebarError }}</div>

      <section class="sidebar-section">
        <div class="section-heading">
          <span>反向链接</span>
          <span class="section-count">{{ backlinks.length }}</span>
        </div>
        <div v-if="!backlinks.length" class="empty-state-compact">暂无其他页面引用当前页</div>
        <div v-else class="card-stack">
          <button
            v-for="link in backlinks"
            :key="`${link.source_page_id}-${link.section_anchor || ''}`"
            type="button"
            class="link-card"
            @click="$emit('open-page', link.source_page_id)"
          >
            <div class="link-card-title">{{ link.source_title || `页面 #${link.source_page_id}` }}</div>
            <div v-if="link.section_anchor" class="link-card-sub">#{{ link.section_anchor }}</div>
          </button>
        </div>
      </section>

      <section class="sidebar-section">
        <div class="section-heading">
          <span>潜在未链接提及</span>
          <button
            type="button"
            class="refresh-mini-btn"
            :disabled="loadingMentions"
            @click="fetchUnlinkedMentions"
          >
            {{ loadingMentions ? '扫描中...' : '刷新' }}
          </button>
        </div>

        <div v-if="!unlinkedMentions.length && !loadingMentions" class="empty-state-compact">
          未发现尚未链接的标题提及
        </div>
        <div v-else class="card-stack">
          <div
            v-for="item in unlinkedMentions"
            :key="item.page_id"
            class="mention-card"
          >
            <div class="mention-head">
              <button type="button" class="mention-source-link" @click="$emit('open-page', item.page_id)">
                {{ item.title }}
              </button>
              <button
                type="button"
                class="convert-link-btn"
                :disabled="linkingMentionId === item.page_id"
                @click="convertMention(item.page_id)"
              >
                {{ linkingMentionId === item.page_id ? '处理中' : '+ 建立双链' }}
              </button>
            </div>
            <div v-if="item.mentions && item.mentions.length" class="mention-excerpt">
              L{{ item.mentions[0]!.line_no }}: {{ item.mentions[0]!.excerpt }}
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 3. History & Diff Tab -->
    <div v-else-if="activeTab === 'diff'" class="tab-content">
      <div v-if="sidebarError" class="sidebar-error">{{ sidebarError }}</div>

      <div v-if="loadingRevs" class="empty-state">加载版本记录...</div>
      <div v-else-if="revisions.length < 2" class="empty-state">
        当前共 {{ revisions.length }} 个版本，编辑并保存两次后可对比差异与回滚。
      </div>
      <template v-else>
        <div class="diff-controls">
          <div class="diff-select-row">
            <label>基线版本</label>
            <select v-model.number="fromRev" class="rev-select" @change="fetchDiff">
              <option v-for="r in revisions" :key="r.rev_no" :value="r.rev_no">
                v{{ r.rev_no }} ({{ r.char_count }} 字)
              </option>
            </select>
          </div>
          <div class="diff-select-row">
            <label>目标版本</label>
            <select v-model.number="toRev" class="rev-select" @change="fetchDiff">
              <option v-for="r in revisions" :key="r.rev_no" :value="r.rev_no">
                v{{ r.rev_no }} ({{ r.char_count }} 字)
              </option>
            </select>
          </div>

          <div class="rollback-bar">
            <template v-if="!confirmingRollback">
              <button
                type="button"
                class="rollback-btn"
                @click="confirmingRollback = true"
              >
                回滚到基线 v{{ fromRev }}
              </button>
            </template>
            <div v-else class="rollback-confirm">
              <span>确认恢复 v{{ fromRev }}？</span>
              <button type="button" class="mini-btn" @click="confirmingRollback = false">取消</button>
              <button type="button" class="mini-btn is-danger" @click="executeRollback">确认回滚</button>
            </div>
          </div>
        </div>

        <div class="diff-stats">
          <span class="stat-add">+{{ diffStats.added }} 行</span>
          <span class="stat-del">-{{ diffStats.removed }} 行</span>
        </div>

        <div v-if="loadingDiff" class="empty-state-compact">正在计算行级差异...</div>
        <div v-else class="diff-lines">
          <div
            v-for="(line, i) in diffLines"
            :key="i"
            :class="['diff-line', `diff-${line.type}`]"
          >
            <span class="diff-gutter">{{ line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' ' }}</span>
            <span class="diff-text">{{ line.content || ' ' }}</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 4. AI Copilot Tab -->
    <div v-else-if="activeTab === 'copilot'" class="tab-content copilot-pane">
      <div class="copilot-toolbar">
        <span class="copilot-subtitle">基于当前页面上下文协作</span>
        <button
          v-if="copilotMessages.length > 0"
          type="button"
          class="clear-chat-btn"
          @click="clearCopilot"
        >
          清空对话
        </button>
      </div>

      <div ref="copilotListRef" class="copilot-messages">
        <div v-if="!copilotMessages.length" class="copilot-empty">
          <p>可以针对当前 Wiki 页面提问、提炼结构或补充内容：</p>
          <div class="quick-prompt-list">
            <button
              v-for="q in QUICK_PROMPTS"
              :key="q"
              type="button"
              class="quick-prompt-btn"
              @click="sendQuickPrompt(q)"
            >
              {{ q }}
            </button>
          </div>
        </div>

        <div
          v-for="(msg, idx) in copilotMessages"
          :key="idx"
          :class="['copilot-msg', `role-${msg.role}`]"
        >
          <div class="msg-bubble">
            <div v-if="msg.role === 'assistant'" class="msg-prose" v-html="renderCopilotHtml(msg.content)" />
            <div v-else>{{ msg.content }}</div>
          </div>
          <div v-if="msg.role === 'assistant' && msg.content && !copilotStreaming" class="msg-actions">
            <button
              type="button"
              class="msg-action-btn"
              @click="$emit('insert-into-editor', msg.content)"
            >
              插入到编辑器
            </button>
          </div>
        </div>
      </div>

      <div class="copilot-composer">
        <textarea
          v-model="copilotInput"
          rows="2"
          class="copilot-textarea"
          placeholder="输入指令（Enter 发送，Shift+Enter 换行）..."
          @keydown="onCopilotKeydown"
        />
        <div class="composer-footer">
          <button
            v-if="copilotStreaming"
            type="button"
            class="stop-btn"
            @click="stopCopilot"
          >
            停止生成
          </button>
          <button
            v-else
            type="button"
            class="send-btn"
            :disabled="!copilotInput.trim()"
            @click="sendCopilot"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { wikiApi } from '../../api/client';
import { useAuthStore } from '../../stores/auth';
import type { WikiBacklink } from '../../stores/wiki';
import { renderMarkdown } from '../../utils/markdown';

interface RevisionSummary {
  rev_no: number;
  title: string;
  char_count: number;
  created_at: string;
}

interface UnlinkedMentionItem {
  page_id: number;
  title: string;
  slug: string;
  mentions: Array<{ line_no: number; excerpt: string }>;
}

interface DiffLineItem {
  type: 'add' | 'del' | 'same';
  content: string;
}

const QUICK_PROMPTS = [
  '提炼当前页面的核心要点列表',
  '检查内容结构并给出补充建议',
  '生成一段简洁的页面导读摘要',
];

const props = defineProps<{
  pageId: number;
  content: string;
  revisionCount: number;
  backlinks: WikiBacklink[];
}>();

const emit = defineEmits<{
  (e: 'open-page', pageId: number): void;
  (e: 'scroll-to-heading', text: string): void;
  (e: 'rollback-rev', revNo: number): void;
  (e: 'mention-linked'): void;
  (e: 'insert-into-editor', text: string): void;
}>();

const auth = useAuthStore();

const activeTab = ref<'toc' | 'backlinks' | 'diff' | 'copilot'>('toc');
const sidebarError = ref<string | null>(null);

// Backlinks & unlinked mentions
const unlinkedMentions = ref<UnlinkedMentionItem[]>([]);
const loadingMentions = ref(false);
const linkingMentionId = ref<number | null>(null);

// Revisions & diff
const revisions = ref<RevisionSummary[]>([]);
const fromRev = ref(1);
const toRev = ref(1);
const diffLines = ref<DiffLineItem[]>([]);
const loadingRevs = ref(false);
const loadingDiff = ref(false);
const confirmingRollback = ref(false);

// Copilot
const copilotMessages = ref<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
const copilotInput = ref('');
const copilotStreaming = ref(false);
const copilotListRef = ref<HTMLDivElement | null>(null);
let copilotController: AbortController | null = null;

// Parse headings from markdown content while ignoring fenced code blocks
const toc = computed(() => {
  const lines = (props.content || '').split('\n');
  const headings: Array<{ level: number; text: string }> = [];
  let inFence = false;
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = line.match(/^(#{1,4})\s+(.+)$/);
    if (m && m[1] && m[2]) {
      headings.push({
        level: m[1].length,
        text: m[2].trim(),
      });
    }
  }
  return headings;
});

const diffStats = computed(() => {
  let added = 0;
  let removed = 0;
  for (const l of diffLines.value) {
    if (l.type === 'add') added += 1;
    else if (l.type === 'del') removed += 1;
  }
  return { added, removed };
});

watch(
  () => props.pageId,
  () => {
    sidebarError.value = null;
    confirmingRollback.value = false;
    unlinkedMentions.value = [];
    revisions.value = [];
    diffLines.value = [];
    if (copilotController) {
      copilotController.abort();
      copilotController = null;
    }
    copilotStreaming.value = false;
    copilotMessages.value = [];

    if (activeTab.value === 'backlinks') {
      void fetchUnlinkedMentions();
    } else if (activeTab.value === 'diff') {
      void fetchRevisionsAndDiff();
    }
  }
);

watch(
  () => props.revisionCount,
  () => {
    if (activeTab.value === 'diff') {
      void fetchRevisionsAndDiff();
    } else if (activeTab.value === 'backlinks') {
      void fetchUnlinkedMentions();
    }
  }
);

function openBacklinksTab() {
  activeTab.value = 'backlinks';
  void fetchUnlinkedMentions();
}

function openDiffTab() {
  activeTab.value = 'diff';
  void fetchRevisionsAndDiff();
}

async function fetchUnlinkedMentions() {
  if (!props.pageId) return;
  loadingMentions.value = true;
  sidebarError.value = null;
  try {
    const res = await wikiApi.getUnlinkedMentions(props.pageId, auth.token);
    unlinkedMentions.value = Array.isArray(res) ? res : [];
  } catch (err: unknown) {
    sidebarError.value = err instanceof Error ? err.message : '扫描未链接提及失败';
  } finally {
    loadingMentions.value = false;
  }
}

async function convertMention(sourcePageId: number) {
  linkingMentionId.value = sourcePageId;
  sidebarError.value = null;
  try {
    await wikiApi.linkMention(props.pageId, sourcePageId, auth.token);
    unlinkedMentions.value = unlinkedMentions.value.filter((m) => m.page_id !== sourcePageId);
    emit('mention-linked');
  } catch (err: unknown) {
    sidebarError.value = err instanceof Error ? err.message : '转换双链失败';
  } finally {
    linkingMentionId.value = null;
  }
}

async function fetchRevisionsAndDiff() {
  if (!props.pageId) return;
  loadingRevs.value = true;
  sidebarError.value = null;
  confirmingRollback.value = false;
  try {
    const res = await wikiApi.getRevisions(props.pageId, auth.token);
    revisions.value = Array.isArray(res) ? res : [];
    if (revisions.value.length >= 2) {
      toRev.value = revisions.value[0]!.rev_no;
      fromRev.value = revisions.value[1]!.rev_no;
      await fetchDiff();
    } else {
      diffLines.value = [];
    }
  } catch (err: unknown) {
    sidebarError.value = err instanceof Error ? err.message : '加载版本记录失败';
  } finally {
    loadingRevs.value = false;
  }
}

async function fetchDiff() {
  if (!props.pageId || revisions.value.length < 2) return;
  loadingDiff.value = true;
  sidebarError.value = null;
  try {
    const res = await wikiApi.getDiff(props.pageId, fromRev.value, toRev.value, auth.token);
    diffLines.value = res?.diff_lines || [];
  } catch (err: unknown) {
    sidebarError.value = err instanceof Error ? err.message : '对比版本差异失败';
  } finally {
    loadingDiff.value = false;
  }
}

function executeRollback() {
  confirmingRollback.value = false;
  emit('rollback-rev', fromRev.value);
}

function renderCopilotHtml(md: string): string {
  return renderMarkdown(md || '', { assetToken: auth.token });
}

function scrollCopilotBottom() {
  nextTick(() => {
    const el = copilotListRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function sendQuickPrompt(text: string) {
  copilotInput.value = text;
  void sendCopilot();
}

function onCopilotKeydown(e: KeyboardEvent) {
  if (e.isComposing) return;
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    void sendCopilot();
  }
}

function stopCopilot() {
  copilotController?.abort();
  copilotController = null;
  copilotStreaming.value = false;
}

function clearCopilot() {
  stopCopilot();
  copilotMessages.value = [];
}

async function sendCopilot() {
  const q = copilotInput.value.trim();
  if (!q || copilotStreaming.value) return;

  copilotMessages.value.push({ role: 'user', content: q });
  copilotInput.value = '';
  const assistantIndex = copilotMessages.value.push({ role: 'assistant', content: '' }) - 1;
  copilotStreaming.value = true;
  scrollCopilotBottom();

  copilotController = new AbortController();
  try {
    await wikiApi.streamCopilot(
      props.pageId,
      { question: q },
      auth.token,
      (ev) => {
        const msg = copilotMessages.value[assistantIndex];
        if (!msg) return;
        if (ev?.type === 'token' && typeof ev.content === 'string') {
          msg.content += ev.content;
          scrollCopilotBottom();
        } else if (ev?.type === 'error') {
          msg.content += `\n\n[助手提示：${ev.error || '生成中断'}]`;
        }
      },
      copilotController.signal
    );
  } catch (err: unknown) {
    const isAbort = err instanceof DOMException && err.name === 'AbortError';
    if (!isAbort) {
      const msg = copilotMessages.value[assistantIndex];
      if (msg && !msg.content) {
        msg.content = `请求失败：${err instanceof Error ? err.message : String(err)}`;
      }
    }
  } finally {
    copilotStreaming.value = false;
    copilotController = null;
  }
}
</script>

<style scoped>
.wiki-sidebar-panel {
  width: 296px;
  min-width: 264px;
  max-width: 320px;
  flex-shrink: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fbfbfd;
  border-left: 1px solid var(--border, #e5e5ea);
}

.sidebar-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 2px;
  padding: 8px;
  border-bottom: 1px solid var(--border, #e5e5ea);
  background: #f5f5f7;
  flex-shrink: 0;
}

.tab-btn {
  border: none;
  background: transparent;
  border-radius: 7px;
  padding: 6px 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s ease, color 0.12s ease;
}

.tab-btn:hover {
  color: var(--text, #1d1d1f);
}

.tab-btn.is-active {
  background: #ffffff;
  color: #0058b0;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.tab-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
}

.empty-state {
  padding: 28px 12px;
  text-align: center;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-tertiary, #86868b);
}

.empty-state-compact {
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
  padding: 6px 0 10px;
}

.sidebar-error {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff5f5;
  border: 1px solid rgba(255, 59, 48, 0.25);
  color: #b42318;
  font-size: 12px;
}

.toc-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.toc-item {
  width: 100%;
  border: none;
  background: transparent;
  text-align: left;
  padding: 5px 8px;
  border-radius: 6px;
  font-size: 12.5px;
  color: var(--text, #1d1d1f);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toc-item:hover {
  background: rgba(0, 113, 227, 0.08);
  color: #0058b0;
}

.toc-item.level-1 {
  font-weight: 600;
}

.toc-item.level-2 {
  padding-left: 18px;
}

.toc-item.level-3 {
  padding-left: 28px;
  font-size: 12px;
  color: var(--text-secondary, #6e6e73);
}

.toc-item.level-4 {
  padding-left: 38px;
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
}

.sidebar-section {
  margin-bottom: 18px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #515154);
  margin-bottom: 8px;
}

.section-count {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
}

.refresh-mini-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text-secondary, #6e6e73);
  border-radius: 6px;
  font-size: 11px;
  padding: 2px 8px;
  cursor: pointer;
}

.card-stack {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.link-card,
.mention-card {
  width: 100%;
  text-align: left;
  background: #ffffff;
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 9px;
  padding: 9px 10px;
}

.link-card {
  cursor: pointer;
  transition: border-color 0.12s ease;
}

.link-card:hover {
  border-color: var(--accent, #0071e3);
}

.link-card-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #0058b0;
}

.link-card-sub {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-tertiary, #86868b);
}

.mention-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.mention-source-link {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text, #1d1d1f);
  cursor: pointer;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mention-source-link:hover {
  color: #0058b0;
}

.convert-link-btn {
  border: 1px solid rgba(0, 113, 227, 0.3);
  background: rgba(0, 113, 227, 0.08);
  color: #0058b0;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  cursor: pointer;
  flex-shrink: 0;
}

.mention-excerpt {
  margin-top: 5px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-secondary, #6e6e73);
  word-break: break-word;
}

.diff-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.diff-select-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary, #6e6e73);
}

.rev-select {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 7px;
  background: #fff;
  padding: 4px 7px;
  font-size: 12px;
}

.rollback-bar {
  padding-top: 2px;
}

.rollback-btn {
  width: 100%;
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text, #1d1d1f);
  border-radius: 7px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.rollback-btn:hover {
  border-color: var(--accent, #0071e3);
  color: #0058b0;
}

.rollback-confirm {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  background: #fff5f5;
  border: 1px solid rgba(255, 59, 48, 0.28);
  border-radius: 7px;
  padding: 6px 8px;
  font-size: 11.5px;
  color: #9e1c1c;
}

.mini-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  border-radius: 5px;
  font-size: 11px;
  padding: 3px 7px;
  cursor: pointer;
}

.mini-btn.is-danger {
  background: #ff3b30;
  border-color: transparent;
  color: #fff;
}

.diff-stats {
  display: flex;
  gap: 10px;
  font-size: 11.5px;
  margin-bottom: 8px;
}

.stat-add {
  color: #15803d;
  font-weight: 600;
}

.stat-del {
  color: #b91c1c;
  font-weight: 600;
}

.diff-lines {
  background: #ffffff;
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 8px;
  overflow-x: auto;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.5;
}

.diff-line {
  display: flex;
  gap: 6px;
  padding: 1px 8px;
  white-space: pre-wrap;
  word-break: break-all;
}

.diff-add {
  background: #ecfdf3;
  color: #166534;
}

.diff-del {
  background: #fef2f2;
  color: #991b1b;
}

.diff-same {
  color: #6e6e73;
}

.diff-gutter {
  width: 10px;
  flex-shrink: 0;
  user-select: none;
}

.copilot-pane {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

.copilot-toolbar {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border, #e5e5ea);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.copilot-subtitle {
  font-size: 11.5px;
  color: var(--text-tertiary, #86868b);
}

.clear-chat-btn {
  border: none;
  background: transparent;
  font-size: 11.5px;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
}

.copilot-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.copilot-empty {
  font-size: 12.5px;
  color: var(--text-secondary, #6e6e73);
  line-height: 1.55;
}

.copilot-empty p {
  margin: 0 0 10px;
}

.quick-prompt-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quick-prompt-btn {
  text-align: left;
  border: 1px solid var(--border, #e5e5ea);
  background: #ffffff;
  color: var(--text, #1d1d1f);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  cursor: pointer;
}

.quick-prompt-btn:hover {
  border-color: var(--accent, #0071e3);
  color: #0058b0;
}

.copilot-msg {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.copilot-msg.role-user {
  align-items: flex-end;
}

.msg-bubble {
  max-width: 94%;
  border-radius: 10px;
  padding: 8px 11px;
  font-size: 12.5px;
  line-height: 1.55;
  word-break: break-word;
}

.role-user .msg-bubble {
  background: var(--accent, #0071e3);
  color: #ffffff;
}

.role-assistant .msg-bubble {
  background: #ffffff;
  border: 1px solid var(--border, #e5e5ea);
  color: var(--text, #1d1d1f);
}

.msg-prose :deep(p) {
  margin: 0.35em 0;
}

.msg-actions {
  display: flex;
  gap: 6px;
}

.msg-action-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #ffffff;
  color: #0058b0;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  cursor: pointer;
}

.copilot-composer {
  padding: 10px 12px;
  border-top: 1px solid var(--border, #e5e5ea);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.copilot-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 8px;
  padding: 7px 9px;
  font-size: 12.5px;
  resize: none;
  outline: none;
  font-family: inherit;
}

.copilot-textarea:focus {
  border-color: var(--accent, #0071e3);
}

.composer-footer {
  display: flex;
  justify-content: flex-end;
}

.send-btn,
.stop-btn {
  border: none;
  border-radius: 7px;
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.send-btn {
  background: var(--accent, #0071e3);
  color: #ffffff;
}

.send-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.stop-btn {
  background: #f2f2f7;
  color: #b91c1c;
}
</style>
