import { defineStore } from 'pinia'
import { login as apiLogin, register as apiRegister, validateToken } from '../api/client'
import { useChatStore } from './chat'

const STORAGE_KEY = 'wenjv_auth_token'
const LEGACY_STORAGE_KEYS = ['wenjv_auth', 'kb_auth']

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: null,
    email: null,
    ready: false,
  }),
  getters: {
    isAuthed: (s) => Boolean(s.token),
  },
  actions: {
    hydrate() {
      try {
        let raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) {
          for (const k of LEGACY_STORAGE_KEYS) {
            raw = localStorage.getItem(k)
            if (raw) break
          }
        }
        if (!raw) {
          this.ready = true
          return
        }
        const data = JSON.parse(raw)
        this.token = data.token || null
        this.email = data.email || null
      } catch {
        this.token = null
        this.email = null
      }
      this.ready = true
    },
    persist() {
      if (this.token) {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ token: this.token, email: this.email }),
        )
      } else {
        localStorage.removeItem(STORAGE_KEY)
        for (const k of LEGACY_STORAGE_KEYS) {
          localStorage.removeItem(k)
        }
      }
    },
    async ensureValid() {
      if (!this.token) return false
      try {
        const r = await validateToken(this.token)
        if (r && r.valid) return true
      } catch {
        /* fallthrough */
      }
      this.logout()
      return false
    },
    async login(email, password) {
      const data = await apiLogin(email, password)
      this.token = data.access_token
      this.email = email
      this.persist()
    },
    async register(email, password) {
      await apiRegister(email, password)
      await this.login(email, password)
    },
    logout() {
      this.token = null
      this.email = null
      this.persist()
      try {
        useChatStore().clearAll()
      } catch {
        /* pinia not ready */
      }
    },
  },
})
