import { defineStore } from 'pinia';
import { login as apiLogin, register as apiRegister, validateToken, type ApiError } from '../api/client.js';
import { useChatStore } from './chat.js';
import { useLibraryStore } from './library.js';
import { useWikiStore } from './wiki.js';

const STORAGE_KEY = 'wenjv_auth_token';
const LEGACY_STORAGE_KEYS = ['wenjv_auth', 'kb_auth'];
const VALIDATION_CACHE_TTL_MS = 5 * 60 * 1000;

export interface AuthState {
  token: string | null;
  email: string | null;
  ready: boolean;
  lastValidatedAt: number;
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: null,
    email: null,
    ready: false,
    lastValidatedAt: 0,
  }),
  getters: {
    isAuthed: (s): boolean => Boolean(s.token),
  },
  actions: {
    hydrate() {
      try {
        let raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) {
          for (const k of LEGACY_STORAGE_KEYS) {
            raw = localStorage.getItem(k);
            if (raw) break;
          }
        }
        if (!raw) {
          this.ready = true;
          return;
        }
        const data = JSON.parse(raw);
        this.token = data.token || null;
        this.email = data.email || null;
      } catch {
        this.token = null;
        this.email = null;
      }
      this.ready = true;
    },
    persist() {
      if (this.token) {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ token: this.token, email: this.email })
        );
      } else {
        localStorage.removeItem(STORAGE_KEY);
        for (const k of LEGACY_STORAGE_KEYS) {
          localStorage.removeItem(k);
        }
      }
    },
    async ensureValid(force = false): Promise<boolean> {
      if (!this.token) return false;
      const now = Date.now();
      if (!force && this.lastValidatedAt && now - this.lastValidatedAt < VALIDATION_CACHE_TTL_MS) {
        return true;
      }
      try {
        const r = await validateToken(this.token);
        if (r && r.valid) {
          this.lastValidatedAt = now;
          return true;
        }
        if (r && r.valid === false) {
          this.logout();
          return false;
        }
      } catch (err: unknown) {
        const apiErr = err as ApiError;
        if (apiErr?.status === 401 || apiErr?.status === 403) {
          this.logout();
          return false;
        }
        // Keep hydrated session on transient network/5xx glitches instead of wiping tabs
        return true;
      }
      this.logout();
      return false;
    },
    async login(email: string, password: string): Promise<void> {
      const data = await apiLogin(email, password);
      this.token = data.access_token;
      this.email = email;
      this.lastValidatedAt = Date.now();
      this.persist();
    },
    async register(email: string, password: string): Promise<void> {
      await apiRegister(email, password);
      try {
        await this.login(email, password);
      } catch {
        const err = new Error('账号已注册成功，但自动登录失败，请前往登录页手动登录。');
        (err as any).code = 'AUTO_LOGIN_FAILED';
        throw err;
      }
    },
    logout() {
      this.token = null;
      this.email = null;
      this.lastValidatedAt = 0;
      this.persist();
      try {
        useChatStore().clearAll();
        useLibraryStore().clearAll();
        useWikiStore().clearAll();
      } catch {
        /* pinia not ready */
      }
    },
  },
});
