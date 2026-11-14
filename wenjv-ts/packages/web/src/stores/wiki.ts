import { defineStore } from 'pinia';
import { wikiApi, type ApiError } from '../api/client';
import { useAuthStore } from './auth';

export interface WikiTreeNode {
  id: number;
  title: string;
  slug: string;
  parent_id: number | null;
  path: string;
  icon?: string;
  sort_order: number;
  index_status?: string;
  children?: WikiTreeNode[];
}

export interface WikiBacklink {
  source_page_id: number;
  source_title: string;
  target_title?: string;
  alias?: string;
  section_anchor?: string;
}

export interface WikiPage {
  id: number;
  title: string;
  slug: string;
  parent_id: number | null;
  path: string;
  icon?: string;
  content: string;
  summary?: string;
  tags?: string[];
  backlinks?: WikiBacklink[];
  revision_count: number;
  updated_at: string;
  created_at?: string;
}

export interface WikiPatchPayload {
  title?: string;
  content?: string;
  icon?: string;
  tags?: string[];
}

interface PendingSave {
  pageId: number;
  patch: WikiPatchPayload;
}

export const useWikiStore = defineStore('wiki', {
  state: () => ({
    tree: [] as WikiTreeNode[],
    currentPage: null as WikiPage | null,
    loadingTree: false,
    loadingPage: false,
    saving: false,
    dirty: false,
    saveError: null as string | null,
    conflictDetected: false,
    lastSavedAt: null as string | null,
    autoSaveTimer: null as ReturnType<typeof setTimeout> | null,
    pendingSave: null as PendingSave | null,
  }),

  actions: {
    getToken(): string {
      const auth = useAuthStore();
      return auth.token || '';
    },

    clearTimer() {
      if (this.autoSaveTimer) {
        clearTimeout(this.autoSaveTimer);
        this.autoSaveTimer = null;
      }
    },

    async loadTree(): Promise<WikiTreeNode[]> {
      this.loadingTree = true;
      try {
        const res = await wikiApi.getTree(this.getToken());
        this.tree = Array.isArray(res) ? res : res?.tree || [];
        return this.tree;
      } finally {
        this.loadingTree = false;
      }
    },

    async openPage(pageId: number): Promise<WikiPage> {
      if (this.pendingSave && this.currentPage && this.currentPage.id !== pageId) {
        try {
          await this.flushSave();
        } catch {
          // Proceed even if flush fails; conflict/saveError remains visible
        }
      }
      this.clearTimer();
      this.pendingSave = null;
      this.dirty = false;
      this.saveError = null;
      this.conflictDetected = false;
      this.loadingPage = true;
      try {
        const page = (await wikiApi.getPage(pageId, this.getToken())) as WikiPage;
        this.currentPage = page;
        return page;
      } finally {
        this.loadingPage = false;
      }
    },

    async reloadCurrentPage(): Promise<WikiPage | null> {
      if (!this.currentPage) return null;
      this.clearTimer();
      this.pendingSave = null;
      this.dirty = false;
      this.saveError = null;
      this.conflictDetected = false;
      const page = (await wikiApi.getPage(this.currentPage.id, this.getToken())) as WikiPage;
      this.currentPage = page;
      await this.loadTree();
      return page;
    },

    async createPage(payload: {
      title?: string;
      parentId?: number | null;
      content?: string;
      icon?: string;
      tags?: string[];
    }): Promise<WikiPage> {
      if (this.pendingSave) {
        await this.flushSave().catch(() => undefined);
      }
      const res = (await wikiApi.createPage(
        {
          title: payload.title || '未命名页面',
          parent_id: payload.parentId ?? null,
          content: payload.content ?? '',
          ...(payload.icon !== undefined ? { icon: payload.icon } : {}),
          ...(payload.tags !== undefined ? { tags: payload.tags } : {}),
        },
        this.getToken()
      )) as WikiPage;
      await this.loadTree();
      this.currentPage = res;
      this.dirty = false;
      this.saveError = null;
      this.conflictDetected = false;
      return res;
    },

    scheduleAutoSave(patch: WikiPatchPayload) {
      if (!this.currentPage) return;
      const targetPageId = this.currentPage.id;

      // Update local state optimistically for snappy UX
      this.currentPage = {
        ...this.currentPage,
        ...patch,
      };
      this.dirty = true;
      this.saveError = null;

      if (this.pendingSave && this.pendingSave.pageId === targetPageId) {
        this.pendingSave = {
          pageId: targetPageId,
          patch: { ...this.pendingSave.patch, ...patch },
        };
      } else {
        this.pendingSave = {
          pageId: targetPageId,
          patch: { ...patch },
        };
      }

      this.clearTimer();
      this.autoSaveTimer = setTimeout(() => {
        void this.flushSave().catch(() => undefined);
      }, 1000);
    },

    async flushSave(options: { ignoreConflict?: boolean } = {}): Promise<boolean> {
      this.clearTimer();
      if (!this.pendingSave || !this.currentPage) {
        this.dirty = false;
        return true;
      }

      const snapshot = this.pendingSave;
      const expectedRev =
        !options.ignoreConflict && this.currentPage.id === snapshot.pageId
          ? this.currentPage.revision_count
          : undefined;

      this.pendingSave = null;
      this.saving = true;
      this.saveError = null;

      try {
        const body: Record<string, unknown> = { ...snapshot.patch };
        if (expectedRev !== undefined) {
          body.expected_rev_no = expectedRev;
        }
        const updated = (await wikiApi.updatePage(snapshot.pageId, body, this.getToken())) as WikiPage;

        if (this.currentPage && this.currentPage.id === updated.id) {
          // Re-apply any edits typed while the PUT request was in flight
          const extra = this.pendingSave as PendingSave | null;
          if (extra && extra.pageId === updated.id) {
            this.currentPage = { ...updated, ...extra.patch };
            this.dirty = true;
            this.clearTimer();
            this.autoSaveTimer = setTimeout(() => {
              void this.flushSave().catch(() => undefined);
            }, 1000);
          } else {
            this.currentPage = updated;
            this.dirty = false;
          }
        }
        this.conflictDetected = false;
        this.lastSavedAt = new Date().toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });

        if (snapshot.patch.title !== undefined || snapshot.patch.icon !== undefined) {
          await this.loadTree();
        }
        return true;
      } catch (err: unknown) {
        const apiErr = err as ApiError;
        // Restore unsaved patch so user never loses typed text
        const newer = this.pendingSave as PendingSave | null;
        this.pendingSave =
          newer && newer.pageId === snapshot.pageId
            ? { pageId: snapshot.pageId, patch: { ...snapshot.patch, ...newer.patch } }
            : snapshot;
        this.dirty = true;

        if (apiErr?.status === 409) {
          this.conflictDetected = true;
          this.saveError = '检测到版本冲突（可能被其他操作更新），请选择覆盖保存或重载最新内容。';
        } else {
          this.saveError = apiErr?.message || '自动保存失败，请检查网络后重试。';
        }
        throw err;
      } finally {
        this.saving = false;
      }
    },

    async forceOverwriteSave(): Promise<boolean> {
      return this.flushSave({ ignoreConflict: true });
    },

    async renamePage(pageId: number, newTitle: string): Promise<WikiPage> {
      const clean = newTitle.trim();
      if (!clean) throw new Error('标题不能为空');
      if (this.currentPage?.id === pageId && this.pendingSave) {
        this.pendingSave.patch.title = clean;
        await this.flushSave();
        await this.loadTree();
        return this.currentPage;
      }
      const updated = (await wikiApi.updatePage(pageId, { title: clean }, this.getToken())) as WikiPage;
      await this.loadTree();
      if (this.currentPage?.id === pageId) {
        this.currentPage = updated;
      }
      return updated;
    },

    async deletePage(pageId: number): Promise<void> {
      if (this.pendingSave?.pageId === pageId) {
        this.clearTimer();
        this.pendingSave = null;
        this.dirty = false;
      }
      await wikiApi.deletePage(pageId, this.getToken());
      if (this.currentPage?.id === pageId) {
        this.currentPage = null;
      }
      await this.loadTree();
    },

    async movePage(pageId: number, targetParentId: number | null, sortOrder = 0): Promise<void> {
      await wikiApi.movePage(
        pageId,
        {
          target_parent_id: targetParentId,
          sort_order: sortOrder,
        },
        this.getToken()
      );
      await this.loadTree();
      if (this.currentPage?.id === pageId) {
        this.currentPage = (await wikiApi.getPage(pageId, this.getToken())) as WikiPage;
      }
    },

    async rollbackRevision(pageId: number, revNo: number): Promise<WikiPage> {
      this.clearTimer();
      this.pendingSave = null;
      const res = (await wikiApi.rollbackRevision(pageId, revNo, this.getToken())) as WikiPage;
      if (this.currentPage?.id === pageId) {
        this.currentPage = res;
        this.dirty = false;
        this.saveError = null;
        this.conflictDetected = false;
      }
      await this.loadTree();
      return res;
    },

    clearAll() {
      this.clearTimer();
      this.tree = [];
      this.currentPage = null;
      this.loadingTree = false;
      this.loadingPage = false;
      this.saving = false;
      this.dirty = false;
      this.saveError = null;
      this.conflictDetected = false;
      this.lastSavedAt = null;
      this.pendingSave = null;
    },
  },
});
