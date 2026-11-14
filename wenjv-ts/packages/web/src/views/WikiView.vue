<template>
  <div class="wiki-view-layout">
    <!-- Toast Notification -->
    <transition name="toast-fade">
      <div v-if="toast.message" :class="['wiki-toast', `is-${toast.type}`]" role="status">
        <span class="toast-dot" />
        <span class="toast-text">{{ toast.message }}</span>
        <button type="button" class="toast-close" @click="clearToast">×</button>
      </div>
    </transition>

    <!-- Left Tree Directory -->
    <wiki-tree
      v-show="!treeCollapsed"
      :tree="wikiStore.tree"
      :current-id="selectedInboxNote ? null : wikiStore.currentPage?.id"
      :loading="wikiStore.loadingTree"
      :inbox-notes="inboxNotes"
      :selected-inbox-id="selectedInboxNote?.id ?? null"
      @select="handleSelectPage"
      @select-inbox="handleSelectInboxNote"
      @create-page="handleCreatePage"
      @rename-page="handleRenamePage"
      @move-page="handleMovePage"
      @delete-page="handleDeletePage"
      @open-search="showCommandModal = true"
      @open-graph="showGraphModal = true"
    />

    <!-- Center Inbox Preview & Promote Workbench -->
    <section v-if="selectedInboxNote" class="inbox-workbench">
      <header class="inbox-wb-header">
        <div class="inbox-wb-badge-row">
          <span class="inbox-wb-badge">
            <Icon name="note" :size="13" />
            <span>笔记收件箱</span>
          </span>
          <span v-if="loadingInboxDetail" class="muted" style="font-size: 12px">读取完整正文中…</span>
        </div>
        <button
          v-if="wikiStore.currentPage"
          type="button"
          class="dlg-cancel"
          @click="selectedInboxNote = null"
        >
          返回 Wiki 编辑
        </button>
      </header>

      <div class="inbox-wb-form">
        <div class="inbox-wb-field">
          <label for="inbox-promote-title">转正 Wiki 页面标题</label>
          <input
            id="inbox-promote-title"
            v-model="inboxPromoteTitle"
            type="text"
            placeholder="请输入 Wiki 页面标题"
            :disabled="promotingInbox"
          />
        </div>
        <div class="inbox-wb-row">
          <div class="inbox-wb-field" style="flex: 1">
            <label for="inbox-promote-parent">存放位置（父目录）</label>
            <select id="inbox-promote-parent" v-model="inboxPromoteParentId" :disabled="promotingInbox">
              <option :value="null">根目录</option>
              <option v-for="opt in wikiParentOptions" :key="opt.id" :value="opt.id">
                {{ opt.prefix }}{{ opt.title }}
              </option>
            </select>
          </div>
          <label class="inbox-wb-check">
            <input v-model="inboxArchiveOriginal" type="checkbox" :disabled="promotingInbox" />
            <span>转正后移出收件箱</span>
          </label>
          <button
            type="button"
            class="dlg-confirm inbox-wb-submit"
            :disabled="!inboxPromoteTitle.trim() || promotingInbox"
            @click="confirmPromoteInboxNote"
          >
            {{ promotingInbox ? '正在转正…' : '一键转正为 Wiki 页面' }}
          </button>
        </div>
      </div>

      <div class="inbox-wb-body">
        <div v-if="selectedInboxNote.tags && selectedInboxNote.tags.length > 0" class="inbox-wb-tags">
          <span v-for="t in selectedInboxNote.tags" :key="t" class="inbox-wb-tag">#{{ t }}</span>
        </div>
        <div class="inbox-wb-content" v-html="renderMd(inboxNoteContent || '（此笔记暂无正文内容）')" />
      </div>
    </section>

    <!-- Center Markdown Editor -->
    <wiki-editor
      v-else
      ref="editorRef"
      :page="wikiStore.currentPage"
      :all-pages="allPagesFlattened"
      :breadcrumbs="currentBreadcrumbs"
      :saving="wikiStore.saving"
      :dirty="wikiStore.dirty"
      :save-error="wikiStore.saveError"
      :conflict-detected="wikiStore.conflictDetected"
      :last-saved-at="wikiStore.lastSavedAt"
      :tree-collapsed="treeCollapsed"
      :sidebar-collapsed="sidebarCollapsed"
      @update-content="handleUpdateContent"
      @navigate-wikilink="handleNavigateWikilink"
      @select-page="handleSelectPage"
      @flush-save="handleManualSave"
      @reload-page="handleReloadPage"
      @force-save="handleForceSave"
      @create-first-page="handleQuickCreatePage('新知识页面')"
      @open-search="showCommandModal = true"
      @toggle-tree="treeCollapsed = !treeCollapsed"
      @toggle-sidebar="sidebarCollapsed = !sidebarCollapsed"
    />

    <!-- Right Context Sidebar -->
    <wiki-sidebar
      v-if="wikiStore.currentPage && !selectedInboxNote && !sidebarCollapsed"
      :page-id="wikiStore.currentPage.id"
      :content="wikiStore.currentPage.content"
      :revision-count="wikiStore.currentPage.revision_count"
      :backlinks="wikiStore.currentPage.backlinks || []"
      @open-page="handleSelectPage"
      @scroll-to-heading="handleScrollToHeading"
      @rollback-rev="handleRollback"
      @mention-linked="handleMentionLinked"
      @insert-into-editor="handleInsertIntoEditor"
    />

    <!-- Graph Modal -->
    <wiki-graph-modal
      :show="showGraphModal"
      :current-page-id="wikiStore.currentPage?.id"
      @close="showGraphModal = false"
      @select-page="handleSelectPage"
    />

    <!-- Quick Search & Jump Command Modal (Cmd/Ctrl+K) -->
    <wiki-command-modal
      :is-open="showCommandModal"
      @close="showCommandModal = false"
      @select-page="handleSelectPage"
      @create-page="handleQuickCreatePage"
    />

    <!-- Non-blocking Create Missing Wikilink Confirmation -->
    <div v-if="pendingCreateTarget" class="confirm-backdrop" @click.self="pendingCreateTarget = null">
      <div class="confirm-dialog" role="dialog" aria-modal="true">
        <h4>新建引用页面</h4>
        <p>
          页面 <strong>“{{ pendingCreateTarget }}”</strong> 尚未创建。是否立即新建并跳转编辑？
        </p>
        <div class="confirm-dialog-actions">
          <button type="button" class="dlg-cancel" @click="pendingCreateTarget = null">取消</button>
          <button type="button" class="dlg-confirm" @click="confirmCreateMissingPage">创建并打开</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getResourceDetail,
  listResources,
  promoteNoteToWiki,
  type ResourceItem,
} from '../api/client';
import { useAuthStore } from '../stores/auth';
import { useWikiStore, type WikiTreeNode } from '../stores/wiki';
import { renderMd } from '../utils/chat-format';
import { flattenWikiTreeOptions } from '../utils/wiki-tree';
import Icon from '../components/Icon.vue';
import WikiTree from '../components/wiki/WikiTree.vue';
import WikiEditor from '../components/wiki/WikiEditor.vue';
import WikiSidebar from '../components/wiki/WikiSidebar.vue';
import WikiGraphModal from '../components/wiki/WikiGraphModal.vue';
import WikiCommandModal from '../components/wiki/WikiCommandModal.vue';

defineOptions({ name: 'WikiView' });

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const wikiStore = useWikiStore();

const editorRef = ref<InstanceType<typeof WikiEditor> | null>(null);
const showGraphModal = ref(false);
const showCommandModal = ref(false);
const treeCollapsed = ref(false);
const sidebarCollapsed = ref(false);
const pendingCreateTarget = ref<string | null>(null);

interface InboxDetailItem {
  id: number;
  title: string;
  tags?: string[];
  content?: string;
}

const inboxNotes = ref<ResourceItem[]>([]);
const selectedInboxNote = ref<InboxDetailItem | null>(null);
const loadingInboxDetail = ref(false);
const inboxPromoteTitle = ref('');
const inboxPromoteParentId = ref<number | null>(null);
const inboxArchiveOriginal = ref(true);
const promotingInbox = ref(false);

const toast = ref<{ message: string; type: 'info' | 'success' | 'error' }>({
  message: '',
  type: 'info',
});
let toastTimer: ReturnType<typeof setTimeout> | null = null;

function showToast(message: string, type: 'info' | 'success' | 'error' = 'info') {
  toast.value = { message, type };
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.value.message = '';
  }, 3500);
}

function clearToast() {
  if (toastTimer) clearTimeout(toastTimer);
  toast.value.message = '';
}

interface FlattenedPage {
  id: number;
  title: string;
  slug: string;
  path: string;
  parent_id: number | null;
}

const allPagesFlattened = computed<FlattenedPage[]>(() => {
  const list: FlattenedPage[] = [];
  const walk = (nodes: WikiTreeNode[]) => {
    for (const n of nodes) {
      list.push({
        id: n.id,
        title: n.title,
        slug: n.slug,
        path: n.path,
        parent_id: n.parent_id ?? null,
      });
      if (n.children && n.children.length > 0) {
        walk(n.children);
      }
    }
  };
  walk(wikiStore.tree);
  return list;
});

const wikiParentOptions = computed(() => flattenWikiTreeOptions(wikiStore.tree));

const inboxNoteContent = computed(() => selectedInboxNote.value?.content ?? '');

async function loadInboxNotes() {
  try {
    const res = await listResources(auth.token, { type: 'note', limit: 100 });
    inboxNotes.value = Array.isArray(res?.resources) ? res.resources : [];
  } catch {
    inboxNotes.value = [];
  }
}

const pageById = computed(() => {
  const m = new Map<number, FlattenedPage>();
  for (const p of allPagesFlattened.value) m.set(p.id, p);
  return m;
});

const currentBreadcrumbs = computed(() => {
  const cur = wikiStore.currentPage;
  if (!cur) return [];
  const crumbs: Array<{ id: number; title: string }> = [];
  let pid = cur.parent_id ?? null;
  const visited = new Set<number>([cur.id]);
  while (pid && !visited.has(pid)) {
    visited.add(pid);
    const parent = pageById.value.get(pid);
    if (!parent) break;
    crumbs.unshift({ id: parent.id, title: parent.title });
    pid = parent.parent_id ?? null;
  }
  return crumbs;
});

function handleGlobalKeys(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    showCommandModal.value = !showCommandModal.value;
  }
}

function handleBeforeUnload(e: BeforeUnloadEvent) {
  if (wikiStore.dirty || wikiStore.saving) {
    e.preventDefault();
    e.returnValue = '';
  }
}

async function syncWikiViewOnEnter() {
  try {
    const [tree] = await Promise.all([wikiStore.loadTree(), loadInboxNotes()]);
    const rawId = route.params.id;
    const paramId = rawId ? Number(Array.isArray(rawId) ? rawId[0] : rawId) : NaN;
    if (Number.isFinite(paramId) && paramId > 0) {
      if (wikiStore.currentPage?.id !== paramId) {
        await handleSelectPage(paramId);
      }
    } else if (wikiStore.currentPage) {
      await router.replace({ name: 'wiki', params: { id: String(wikiStore.currentPage.id) } });
    } else if (tree.length > 0) {
      await handleSelectPage(tree[0]!.id);
    }
  } catch (err: unknown) {
    showToast(`加载知识库目录失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleGlobalKeys);
  window.addEventListener('beforeunload', handleBeforeUnload);
  await syncWikiViewOnEnter();
});

onActivated(() => {
  void syncWikiViewOnEnter();
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleGlobalKeys);
  window.removeEventListener('beforeunload', handleBeforeUnload);
  if (toastTimer) clearTimeout(toastTimer);
  if (wikiStore.dirty) {
    void wikiStore.flushSave().catch(() => undefined);
  }
});

watch(
  () => route.params.id,
  async (newId) => {
    if (!newId) return;
    const numId = Number(Array.isArray(newId) ? newId[0] : newId);
    if (Number.isFinite(numId) && numId > 0 && wikiStore.currentPage?.id !== numId) {
      try {
        await wikiStore.openPage(numId);
      } catch (err: unknown) {
        showToast(`打开页面失败：${err instanceof Error ? err.message : String(err)}`, 'error');
      }
    }
  }
);

async function handleSelectPage(pageId: number) {
  selectedInboxNote.value = null;
  try {
    await wikiStore.openPage(pageId);
    if (Number(route.params.id) !== pageId) {
      await router.replace({ name: 'wiki', params: { id: String(pageId) } });
    }
  } catch (err: unknown) {
    showToast(`打开页面失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleSelectInboxNote(noteId: number) {
  const summary = inboxNotes.value.find((n) => n.id === noteId);
  selectedInboxNote.value = summary
    ? { id: summary.id, title: summary.title, tags: summary.tags }
    : { id: noteId, title: '未命名笔记' };
  inboxPromoteTitle.value = summary?.title || '未命名笔记';
  inboxPromoteParentId.value = null;
  inboxArchiveOriginal.value = true;
  loadingInboxDetail.value = true;
  try {
    const detail = await getResourceDetail(auth.token, noteId);
    if (selectedInboxNote.value?.id === noteId) {
      selectedInboxNote.value = detail;
      inboxPromoteTitle.value = detail.title || '未命名笔记';
    }
  } catch (err: unknown) {
    showToast(`读取笔记失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  } finally {
    loadingInboxDetail.value = false;
  }
}

async function confirmPromoteInboxNote() {
  const note = selectedInboxNote.value;
  if (!note || promotingInbox.value || !inboxPromoteTitle.value.trim()) return;
  promotingInbox.value = true;
  try {
    const res = await promoteNoteToWiki(auth.token, note.id, {
      title: inboxPromoteTitle.value.trim(),
      parent_id: inboxPromoteParentId.value,
      archive_original: inboxArchiveOriginal.value,
    });
    selectedInboxNote.value = null;
    await Promise.all([wikiStore.loadTree(), loadInboxNotes()]);
    await handleSelectPage(res.page.id);
    showToast(`已将“${res.page.title}”转正为 Wiki 页面`, 'success');
  } catch (err: unknown) {
    showToast(`转正失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  } finally {
    promotingInbox.value = false;
  }
}

async function handleCreatePage(payload: { title: string; parentId: number | null }) {
  try {
    const created = await wikiStore.createPage({
      title: payload.title,
      parentId: payload.parentId,
    });
    await router.replace({ name: 'wiki', params: { id: String(created.id) } });
    showToast(`已创建“${created.title}”`, 'success');
  } catch (err: unknown) {
    showToast(`新建页面失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleQuickCreatePage(title: string) {
  const clean = (title || '').trim() || '未命名页面';
  await handleCreatePage({ title: clean, parentId: null });
}

async function handleRenamePage(payload: { id: number; title: string }) {
  try {
    await wikiStore.renamePage(payload.id, payload.title);
    showToast('页面名称已更新', 'success');
  } catch (err: unknown) {
    showToast(`重命名失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleMovePage(payload: { id: number; targetParentId: number | null; sortOrder: number }) {
  try {
    await wikiStore.movePage(payload.id, payload.targetParentId, payload.sortOrder);
    showToast('页面位置已更新', 'success');
  } catch (err: unknown) {
    showToast(`移动失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleDeletePage(pageId: number) {
  try {
    await wikiStore.deletePage(pageId);
    if (!wikiStore.currentPage) {
      if (wikiStore.tree.length > 0) {
        await handleSelectPage(wikiStore.tree[0]!.id);
      } else {
        await router.replace({ name: 'wiki' });
      }
    }
    showToast('页面已删除', 'info');
  } catch (err: unknown) {
    showToast(`删除失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

function handleUpdateContent(patch: { title?: string; content?: string; icon?: string; tags?: string[] }) {
  wikiStore.scheduleAutoSave(patch);
}

async function handleManualSave() {
  try {
    await wikiStore.flushSave();
    showToast('已保存当前修改', 'success');
  } catch {
    showToast(wikiStore.saveError || '保存失败', 'error');
  }
}

async function handleReloadPage() {
  try {
    await wikiStore.reloadCurrentPage();
    showToast('已加载服务端最新版本', 'info');
  } catch (err: unknown) {
    showToast(`重载失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleForceSave() {
  try {
    await wikiStore.forceOverwriteSave();
    showToast('已覆盖保存最新版本', 'success');
  } catch (err: unknown) {
    showToast(`覆盖保存失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleNavigateWikilink(payload: { target: string; anchor?: string }) {
  const target = payload.target.trim();
  if (!target) return;
  const matched = allPagesFlattened.value.find(
    (p) => p.title.toLowerCase() === target.toLowerCase() || p.slug.toLowerCase() === target.toLowerCase()
  );
  if (matched) {
    await handleSelectPage(matched.id);
    if (payload.anchor) {
      nextTick(() => editorRef.value?.scrollToHeading(payload.anchor!));
    }
    return;
  }
  pendingCreateTarget.value = target;
}

async function confirmCreateMissingPage() {
  const title = pendingCreateTarget.value;
  pendingCreateTarget.value = null;
  if (!title) return;
  await handleCreatePage({ title, parentId: null });
}

async function handleRollback(revNo: number) {
  if (!wikiStore.currentPage) return;
  try {
    await wikiStore.rollbackRevision(wikiStore.currentPage.id, revNo);
    showToast(`已回滚至版本 v${revNo}`, 'success');
  } catch (err: unknown) {
    showToast(`回滚失败：${err instanceof Error ? err.message : String(err)}`, 'error');
  }
}

async function handleMentionLinked() {
  try {
    await wikiStore.reloadCurrentPage();
    showToast('已将该提及转换为双向链接', 'success');
  } catch {
    showToast('已转换链接，请刷新查看最新反向引用', 'info');
  }
}

function handleScrollToHeading(text: string) {
  editorRef.value?.scrollToHeading(text);
}

function handleInsertIntoEditor(text: string) {
  editorRef.value?.insertAtCursor(text);
  showToast('已插入到当前文档光标处', 'success');
}
</script>

<style scoped>
.wiki-view-layout {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--surface, #ffffff);
  position: relative;
}

.wiki-toast {
  position: fixed;
  top: 16px;
  right: 20px;
  z-index: 200;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--border, #d1d1d6);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.12);
  font-size: 13px;
  color: var(--text, #1d1d1f);
}

.toast-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent, #0071e3);
  flex-shrink: 0;
}

.wiki-toast.is-success .toast-dot {
  background: #34c759;
}

.wiki-toast.is-error .toast-dot {
  background: #ff3b30;
}

.toast-close {
  border: none;
  background: transparent;
  color: var(--text-tertiary, #86868b);
  font-size: 15px;
  cursor: pointer;
  padding: 0 2px;
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 150;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.confirm-dialog {
  width: min(400px, 92vw);
  background: #ffffff;
  border-radius: 12px;
  border: 1px solid var(--border, #e5e5ea);
  box-shadow: 0 20px 44px rgba(0, 0, 0, 0.18);
  padding: 20px;
}

.confirm-dialog h4 {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 650;
  color: var(--text, #1d1d1f);
}

.confirm-dialog p {
  margin: 0 0 18px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-secondary, #515154);
}

.confirm-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.dlg-cancel {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text, #1d1d1f);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12.5px;
  cursor: pointer;
}

.dlg-confirm {
  border: none;
  background: var(--accent, #0071e3);
  color: #fff;
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.inbox-workbench {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface, #ffffff);
  overflow-y: auto;
  padding: 20px 28px 40px;
  gap: 16px;
}

.inbox-wb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.inbox-wb-badge-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.inbox-wb-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: #0058b0;
  background: rgba(0, 113, 227, 0.08);
  border: 1px solid rgba(0, 113, 227, 0.2);
}

.inbox-wb-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  border-radius: 12px;
  border: 1px solid var(--border, #e5e5ea);
  background: var(--bg, #fbfbfd);
}

.inbox-wb-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.inbox-wb-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.inbox-wb-field label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary, #6e6e73);
}

.inbox-wb-field input,
.inbox-wb-field select {
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13.5px;
  background: var(--surface, #ffffff);
  color: var(--text, #1d1d1f);
}

.inbox-wb-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-secondary, #6e6e73);
  padding-bottom: 7px;
  cursor: pointer;
}

.inbox-wb-submit {
  padding: 8px 16px;
  font-size: 13px;
}

.inbox-wb-body {
  padding: 18px 20px;
  border-radius: 12px;
  border: 1px solid var(--border, #e5e5ea);
  background: var(--surface, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inbox-wb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.inbox-wb-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-secondary, rgba(120, 120, 128, 0.1));
  color: var(--text-secondary, #6e6e73);
}

.inbox-wb-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text, #1d1d1f);
  word-break: break-word;
}
</style>
