import { defineStore } from 'pinia'

/**
 * Session chat context — survives route changes (chat ↔ library).
 * Cleared on logout. Not persisted to localStorage (blob image URLs + privacy).
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [],
    citations: [],
    citesCollapsed: false,
    mode: 'rag',
    windowSize: 5,
    model: '',
    models: [],
    modelsLoaded: false,
    prompt: '',
    // sidebar tab preference
    tab: 'file',
    // transient stream UI (kept so mid-stream nav is less destructive)
    streaming: false,
    streamText: '',
    busy: false,
  }),
  getters: {
    historyForApi(state) {
      return state.messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .slice(-8)
        .map((m) => ({ role: m.role, content: m.content }))
    },
  },
  actions: {
    setModels(list) {
      this.models = Array.isArray(list) ? list : []
      this.modelsLoaded = true
    },
    pushMessage(msg) {
      this.messages.push(msg)
    },
    setCitations(list) {
      this.citations = Array.isArray(list) ? list : []
    },
    clearCitations() {
      this.citations = []
      this.citesCollapsed = false
    },
    appendStream(token) {
      this.streamText += token || ''
    },
    beginStream() {
      this.streaming = true
      this.streamText = ''
      this.busy = true
    },
    endStream(commit = true) {
      if (commit) {
        const text = this.streamText || '（无输出）'
        this.messages.push({ role: 'assistant', content: text })
      }
      this.streaming = false
      this.streamText = ''
      this.busy = false
    },
    resetSession() {
      this.messages = []
      this.citations = []
      this.citesCollapsed = false
      this.prompt = ''
      this.streaming = false
      this.streamText = ''
      this.busy = false
      // keep mode / windowSize / model preference
    },
    /** Full wipe (logout). */
    clearAll() {
      this.resetSession()
      this.models = []
      this.modelsLoaded = false
      this.model = ''
      this.tab = 'file'
      this.mode = 'rag'
      this.windowSize = 5
    },
  },
})
