import { defineStore } from 'pinia';
import {
  listResources,
  deleteResource,
  getTags,
  updateResourceTags,
  type ResourceItem,
  type ResourceType,
  type TagSummary,
} from '../api/client.js';
import { useAuthStore } from './auth.js';

export type LibraryTypeFilter = 'all' | ResourceType;

export interface LibraryState {
  resources: ResourceItem[];
  totalCount: number;
  tagSummary: TagSummary[];
  activeTag: string | null;
  activeType: LibraryTypeFilter;
  searchQuery: string;
  loading: boolean;
  loaded: boolean;
  error: string;
  selectedResourceId: number | null;
}

export const useLibraryStore = defineStore('library', {
  state: (): LibraryState => ({
    resources: [],
    totalCount: 0,
    tagSummary: [],
    activeTag: null,
    activeType: 'all',
    searchQuery: '',
    loading: false,
    loaded: false,
    error: '',
    selectedResourceId: null,
  }),
  getters: {
    selectedResource(state): ResourceItem | null {
      if (state.selectedResourceId == null) return null;
      return state.resources.find((r) => r.id === state.selectedResourceId) ?? null;
    },
    hasActiveJobs(state): boolean {
      return state.resources.some(
        (r) => r.status === 'pending' || r.status === 'in_progress' || r.status === 'processing'
      );
    },
  },
  actions: {
    async refreshTags(): Promise<void> {
      const auth = useAuthStore();
      if (!auth.token) return;
      try {
        const res = await getTags(auth.token);
        this.tagSummary = res.tags || [];
      } catch {
        // Ignore transient tag summary refresh errors
      }
    },

    async reload(opts: { silent?: boolean } = {}): Promise<void> {
      const auth = useAuthStore();
      if (!auth.token) return;

      const silent = Boolean(opts.silent) && this.loaded;
      if (!silent) this.loading = true;
      this.error = '';

      try {
        const [res, tagsRes] = await Promise.all([
          listResources(auth.token, { limit: 200 }),
          getTags(auth.token).catch(() => null),
        ]);
        this.resources = res?.resources || [];
        this.totalCount = res?.total ?? this.resources.length;
        if (tagsRes) {
          this.tagSummary = tagsRes.tags || [];
        }
        this.loaded = true;
      } catch (err: unknown) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        if (!silent) this.loading = false;
      }
    },

    async saveItemTags(itemId: number, tags: string[]): Promise<string[]> {
      const auth = useAuthStore();
      const res = await updateResourceTags(auth.token, 'resource', itemId, tags);
      const nextTags = res.tags || [];
      const target = this.resources.find((r) => r.id === itemId);
      if (target) {
        target.tags = nextTags;
      }
      await this.refreshTags();
      return nextTags;
    },

    async removeItem(itemId: number): Promise<void> {
      const auth = useAuthStore();
      await deleteResource(auth.token, itemId);
      this.resources = this.resources.filter((r) => r.id !== itemId);
      this.totalCount = this.resources.length;
      if (this.selectedResourceId === itemId) {
        this.selectedResourceId = null;
      }
      await this.refreshTags();
    },

    clearAll() {
      this.resources = [];
      this.totalCount = 0;
      this.tagSummary = [];
      this.activeTag = null;
      this.activeType = 'all';
      this.searchQuery = '';
      this.loading = false;
      this.loaded = false;
      this.error = '';
      this.selectedResourceId = null;
    },
  },
});
