import { defineStore } from 'pinia';

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  thinking?: string;
  mediaUrl?: string;
  imageUrl?: string;
  images?: string[];
  pending?: boolean;
}

export interface CitationItem {
  id?: string | number;
  filename?: string;
  title?: string;
  source?: string;
  page?: string | number;
  page_content?: string;
  score?: number;
  image_url?: string;
  has_image?: boolean;
  tag_matched?: boolean;
  tag_fallback?: boolean;
  metadata?: Record<string, unknown>;
}

export interface ChatState {
  messages: ChatMessage[];
  citations: CitationItem[];
  citesCollapsed: boolean;
  mode: string;
  windowSize: number;
  model: string;
  models: string[];
  modelsLoaded: boolean;
  prompt: string;
  tab: string;
  selectedTags: string[];
  streaming: boolean;
  streamText: string;
  streamThinking: string;
  busy: boolean;
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    messages: [],
    citations: [],
    citesCollapsed: false,
    mode: 'rag',
    windowSize: 5,
    model: '',
    models: [],
    modelsLoaded: false,
    prompt: '',
    tab: 'file',
    selectedTags: [],
    streaming: false,
    streamText: '',
    streamThinking: '',
    busy: false,
  }),
  getters: {
    historyForApi(state) {
      return state.messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .slice(-8)
        .map((m) => {
          const entry: { role: string; content: string; images?: string[] } = {
            role: m.role,
            content: m.content,
          };
          if (m.mediaUrl) {
            entry.images = [m.mediaUrl];
          } else if (m.imageUrl) {
            entry.images = [m.imageUrl];
          } else if (m.images && Array.isArray(m.images) && m.images.length > 0) {
            entry.images = m.images;
          }
          return entry;
        });
    },
  },
  actions: {
    setModels(list: string[]) {
      this.models = Array.isArray(list) ? list : [];
      this.modelsLoaded = true;
    },
    pushMessage(msg: ChatMessage) {
      this.messages.push(msg);
    },
    setCitations(list: CitationItem[]) {
      this.citations = Array.isArray(list) ? list : [];
    },
    clearCitations() {
      this.citations = [];
      this.citesCollapsed = false;
    },
    appendStream(token: string) {
      this.streamText += token || '';
    },
    appendThinking(token: string) {
      this.streamThinking += token || '';
    },
    beginStream() {
      this.streaming = true;
      this.streamText = '';
      this.streamThinking = '';
      this.busy = true;
    },
    endStream(commit = true) {
      if (commit) {
        const text = this.streamText || '（无输出）';
        const thinking = this.streamThinking.trim();
        this.messages.push({
          role: 'assistant',
          content: text,
          ...(thinking ? { thinking } : {}),
        });
      }
      this.streaming = false;
      this.streamText = '';
      this.streamThinking = '';
      this.busy = false;
    },
    resetSession() {
      this.messages = [];
      this.citations = [];
      this.citesCollapsed = false;
      this.prompt = '';
      this.streaming = false;
      this.streamText = '';
      this.streamThinking = '';
      this.busy = false;
    },
    clearAll() {
      this.resetSession();
      this.models = [];
      this.modelsLoaded = false;
      this.model = '';
      this.tab = 'file';
      this.selectedTags = [];
      this.mode = 'rag';
      this.windowSize = 5;
    },
  },
});
