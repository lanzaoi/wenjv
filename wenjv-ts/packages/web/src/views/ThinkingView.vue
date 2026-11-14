<template>
  <div class="thinking-page">
    <header class="thinking-header">
      <div class="header-left">
        <button type="button" class="btn btn-ghost btn-sm back-btn" @click="goBack">
          <Icon name="arrow-left" :size="16" />
          <span>返回对话</span>
        </button>
        <div class="header-title-wrap">
          <h1 class="header-title">深度思考过程</h1>
          <span v-if="isLiveStreaming" class="status-badge is-live">
            <span class="pulse-dot" />
            思考中 · {{ formatThinkingLength(thinkingText) }}
          </span>
          <span v-else-if="thinkingText" class="status-badge">
            已完成 · {{ formatThinkingLength(thinkingText) }}
          </span>
        </div>
      </div>
      <div class="header-actions">
        <button
          v-if="thinkingText"
          type="button"
          class="btn btn-secondary btn-sm copy-btn"
          @click="copyThinking"
        >
          <Icon :name="copied ? 'check' : 'copy'" :size="14" />
          <span>{{ copied ? '已复制' : '复制推理内容' }}</span>
        </button>
      </div>
    </header>

    <main class="thinking-body">
      <div v-if="!thinkingText && !isLiveStreaming" class="empty-card">
        <Icon name="thought" :size="28" class="empty-icon" />
        <h2>未找到对应的思考记录</h2>
        <p class="muted">当前会话已重置或该条回答未返回思考过程。</p>
        <button type="button" class="btn btn-primary btn-sm" @click="goBack">
          返回对话页
        </button>
      </div>

      <template v-else>
        <section v-if="questionPrompt" class="context-card">
          <div class="context-label">对应提问</div>
          <div class="context-text">{{ questionPrompt }}</div>
        </section>

        <section class="reasoning-card">
          <div class="reasoning-card-head">
            <span class="reasoning-head-title">
              <Icon name="thought" :size="15" />
              <span>模型推理轨迹</span>
            </span>
            <span v-if="isLiveStreaming && streamText" class="answer-ready-hint" @click="goBack">
              已开始生成最终回答，点击返回查看 →
            </span>
          </div>
          <div class="reasoning-content" v-html="renderMd(thinkingText)" />
          <div v-if="isLiveStreaming" class="live-tail">
            <span class="spinner" />
            <span>正在继续推演…</span>
          </div>
        </section>

        <section v-if="answerPreview" class="answer-preview-card">
          <div class="answer-preview-head">
            <span>最终回答摘要</span>
            <button type="button" class="link-btn" @click="goBack">回到对话上下文</button>
          </div>
          <div class="answer-preview-body" v-html="renderMd(answerPreview)" />
        </section>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { useRoute, useRouter } from 'vue-router';
import Icon from '../components/Icon.vue';
import { useChatStore } from '../stores/chat';
import { formatThinkingLength, renderMd } from '../utils/chat-format';

defineOptions({ name: 'ThinkingView' });

const route = useRoute();
const router = useRouter();
const chat = useChatStore();
const { messages, streaming, streamThinking, streamText } = storeToRefs(chat);

const copied = ref(false);

const targetId = computed(() => String(route.params['id'] ?? ''));

const resolvedMessageIndex = computed(() => {
  if (targetId.value === 'live') {
    if (streaming.value) return -1;
    // Stream finished while user was viewing /thinking/live: bind to latest assistant message with thinking.
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i]?.role === 'assistant' && messages.value[i]?.thinking) {
        return i;
      }
    }
    return -1;
  }
  const idx = Number(targetId.value);
  return Number.isInteger(idx) && idx >= 0 && idx < messages.value.length ? idx : -1;
});

const isLiveStreaming = computed(() => targetId.value === 'live' && streaming.value);

const thinkingText = computed(() => {
  if (isLiveStreaming.value) {
    return streamThinking.value;
  }
  const idx = resolvedMessageIndex.value;
  if (idx < 0) return '';
  return messages.value[idx]?.thinking || '';
});

const questionPrompt = computed(() => {
  const startIdx = isLiveStreaming.value
    ? messages.value.length - 1
    : resolvedMessageIndex.value - 1;
  for (let i = startIdx; i >= 0; i--) {
    const m = messages.value[i];
    if (m?.role === 'user' && m.content) {
      return m.content;
    }
  }
  return '';
});

const answerPreview = computed(() => {
  if (isLiveStreaming.value) {
    return streamText.value || '';
  }
  const idx = resolvedMessageIndex.value;
  if (idx < 0) return '';
  return messages.value[idx]?.content || '';
});

function goBack() {
  router.push({ name: 'chat' });
}

async function copyThinking() {
  if (!thinkingText.value) return;
  try {
    await navigator.clipboard.writeText(thinkingText.value);
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    // Fallback ignored if clipboard permission denied
  }
}
</script>

<style scoped>
.thinking-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}

.thinking-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 24px;
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
}

.back-btn:hover {
  color: var(--text-primary);
}

.header-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-secondary, rgba(120, 120, 128, 0.1));
  border: 1px solid var(--border);
}

.status-badge.is-live {
  color: var(--accent);
  background: rgba(0, 113, 227, 0.08);
  border-color: rgba(0, 113, 227, 0.2);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.thinking-body {
  width: min(820px, 100%);
  margin: 0 auto;
  padding: 24px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-card {
  margin-top: 40px;
  padding: 40px 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.empty-icon {
  color: var(--text-tertiary, var(--text-secondary));
}

.empty-card h2 {
  margin: 4px 0 0;
  font-size: 16px;
  font-weight: 600;
}

.context-card {
  padding: 14px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.context-label {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
  letter-spacing: 0.02em;
}

.context-text {
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.reasoning-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 22px;
}

.reasoning-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.reasoning-head-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.answer-ready-hint {
  font-size: 12.5px;
  color: var(--accent);
  cursor: pointer;
}

.answer-ready-hint:hover {
  text-decoration: underline;
}

.reasoning-content {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-primary);
  word-break: break-word;
}

.reasoning-content :deep(.code-block) {
  background: var(--bg-secondary, #f5f5f7);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 13px;
}

.reasoning-content :deep(.inline-code) {
  background: var(--bg-secondary, rgba(120, 120, 128, 0.1));
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.9em;
}

.reasoning-content :deep(.md-quote) {
  margin: 6px 0;
  padding: 4px 10px;
  border-left: 3px solid var(--border-strong);
  color: var(--text-secondary);
}

.live-tail {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.answer-preview-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
}

.answer-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.link-btn {
  border: none;
  background: none;
  padding: 0;
  font-size: 12.5px;
  color: var(--accent);
  cursor: pointer;
}

.link-btn:hover {
  text-decoration: underline;
}

.answer-preview-body {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-secondary);
  max-height: 220px;
  overflow-y: auto;
}
</style>
