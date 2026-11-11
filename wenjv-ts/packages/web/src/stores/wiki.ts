import { defineStore } from 'pinia';
import { wikiApi } from '../api/client.js';
import { useAuthStore } from './auth.js';

export interface WikiTreeNode {
  id: number;
  title: string;
  slug?: string;
  parent_id?: number | null;
  path?: string;
  icon?: string;
  sort_order?: number;
  index_status?: string;
  children: WikiTreeNode[];
}

export interface WikiPageDetail {
  id: number;
  user_id: number;
  parent_id?: number | null;
  path: string;
  slug: string;
  title: string;
  content: string;
  summary?: string;
  sort_order?: number;
  icon?: string;
  tags?: string[];
  index_status?: string;
  revision_count?: number;
  created_at?: string;
  updated_at?: string;
  backlinks?: Array<{ source_page_id: number; title: string }>;
}

export interface WikiState {
  tree: WikiTreeNode[];
  treeLoaded: boolean;
  currentPage: WikiPageDetail | null;
  loadingPage: boolean;
  saving: boolean;
  dirty: boolean;
  saveTimer: ReturnType<typeof setTimeout> | null;
  pageReqSeq: number;
  lastError: string | null;
}

export const useWikiStore = defineStore('wiki', {
  state: (): WikiState => ({
    tree: [],
    treeLoaded: false,
    currentPage: null,
    loadingPage: false,
    saving: false,
    dirty: false,
    saveTimer: null,
    pageReqSeq: 0,
    lastError: null,
  }),

  actions: {
    getToken(): string | null {
      const auth = useAuthStore();
      return auth.token;
    },

    async loadTree(): Promise<WikiTreeNode[]> {
      this.lastError = null;
      try {
        const token = this.getToken();
        const res = (await wikiApi.getTree(token)) as WikiTreeNode[];
        this.tree = res || [];
        this.treeLoaded = true;
        return this.tree;
      } catch (err: any) {
        this.lastError = err.message || '加载 Wiki 目录失败';
        console.error('Failed to load wiki tree', err);
        throw err;
      }
    },

    async openPage(pageId: number): Promise<WikiPageDetail | undefined> {
      if (this.currentPage && this.currentPage.id === pageId) return;

      if (this.dirty && this.currentPage) {
        if (this.saveTimer) {
          clearTimeout(this.saveTimer);
          this.saveTimer = null;
        }
        try {
          await this.flushSave();
        } catch (e) {
          console.warn('Failed to flush unsaved page before switching', e);
        }
      }

      if (this.saveTimer) {
        clearTimeout(this.saveTimer);
        this.saveTimer = null;
      }

      const seq = ++this.pageReqSeq;
      this.loadingPage = true;
      this.lastError = null;

      try {
        const token = this.getToken();
        const data = (await wikiApi.getPage(pageId, token)) as WikiPageDetail;
        if (seq === this.pageReqSeq) {
          this.currentPage = data;
          this.dirty = false;
        }
        return data;
      } catch (err: any) {
        if (seq === this.pageReqSeq) {
          this.lastError = err.message || '打开 Wiki 页面失败';
          console.error('Failed to open wiki page', err);
        }
        throw err;
      } finally {
        if (seq === this.pageReqSeq) {
          this.loadingPage = false;
        }
      }
    },

    async createPage({ title, parentId = null }: { title: string; parentId?: number | null }): Promise<WikiPageDetail> {
      this.lastError = null;
      try {
        const token = this.getToken();
        const newPage = (await wikiApi.createPage({ title, parent_id: parentId }, token)) as WikiPageDetail;
        await this.loadTree();
        await this.openPage(newPage.id);
        return newPage;
      } catch (err: any) {
        this.lastError = err.message || '创建 Wiki 页面失败';
        console.error('Failed to create wiki page', err);
        throw err;
      }
    },

    scheduleAutoSave(patch: Partial<WikiPageDetail>) {
      if (!this.currentPage) return;
      Object.assign(this.currentPage, patch);
      this.dirty = true;

      if (this.saveTimer) clearTimeout(this.saveTimer);
      this.saveTimer = setTimeout(async () => {
        await this.flushSave();
      }, 600);
    },

    async flushSave(): Promise<WikiPageDetail | undefined> {
      if (!this.currentPage || !this.dirty) return;
      if (this.saveTimer) {
        clearTimeout(this.saveTimer);
        this.saveTimer = null;
      }

      const targetId = this.currentPage.id;
      const payload = {
        title: this.currentPage.title,
        content: this.currentPage.content,
        icon: this.currentPage.icon,
      };

      this.saving = true;
      try {
        const token = this.getToken();
        const updated = (await wikiApi.updatePage(targetId, payload, token)) as WikiPageDetail;

        if (this.currentPage && this.currentPage.id === targetId) {
          this.currentPage.updated_at = updated.updated_at;
          this.currentPage.revision_count = updated.revision_count;
          this.currentPage.backlinks = updated.backlinks;
          this.dirty = false;
        }
        this.updateTreeTitle(this.tree, updated.id, updated.title);
        return updated;
      } catch (err: any) {
        this.lastError = err.message || '自动保存失败';
        console.error('Auto save failed', err);
        throw err;
      } finally {
        this.saving = false;
      }
    },

    updateTreeTitle(nodes: WikiTreeNode[], id: number, newTitle: string): boolean {
      for (const node of nodes) {
        if (node.id === id) {
          node.title = newTitle;
          return true;
        }
        if (node.children && node.children.length) {
          if (this.updateTreeTitle(node.children, id, newTitle)) return true;
        }
      }
      return false;
    },

    async movePage(pageId: number, targetParentId: number | null, sortOrder: number | null = null): Promise<void> {
      this.lastError = null;
      try {
        const token = this.getToken();
        await wikiApi.movePage(pageId, { target_parent_id: targetParentId, sort_order: sortOrder }, token);
        await this.loadTree();
      } catch (err: any) {
        this.lastError = err.message || '移动页面失败';
        console.error('Move page failed', err);
        throw err;
      }
    },

    async deletePage(pageId: number): Promise<void> {
      this.lastError = null;
      try {
        const token = this.getToken();
        await wikiApi.deletePage(pageId, token);
        if (this.currentPage && this.currentPage.id === pageId) {
          this.currentPage = null;
          this.dirty = false;
        }
        await this.loadTree();
      } catch (err: any) {
        this.lastError = err.message || '删除页面失败';
        console.error('Delete page failed', err);
        throw err;
      }
    },

    async rollbackRevision(pageId: number, revNo: number): Promise<WikiPageDetail> {
      this.lastError = null;
      try {
        const token = this.getToken();
        const rolled = (await wikiApi.rollbackRevision(pageId, revNo, token)) as WikiPageDetail;
        this.currentPage = rolled;
        this.dirty = false;
        this.updateTreeTitle(this.tree, rolled.id, rolled.title);
        return rolled;
      } catch (err: any) {
        this.lastError = err.message || '版本回滚失败';
        console.error('Rollback failed', err);
        throw err;
      }
    },
  },
});
