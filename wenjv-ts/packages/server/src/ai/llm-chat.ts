import { config } from '../config.js';

export interface ChatImagePart {
  data: string;
  mime_type?: string;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
  images?: Array<string | ChatImagePart>;
}

export interface ChatCompletionOptions {
  model?: string;
  messages: ChatMessage[];
  signal?: AbortSignal;
}

export interface ChatStreamEvent {
  kind: 'thinking' | 'token';
  text: string;
}

type OpenAIMessageContent =
  | string
  | Array<
      | { type: 'text'; text: string }
      | { type: 'image_url'; image_url: { url: string } }
    >;

function toDataUrl(img: string | ChatImagePart): string | null {
  if (typeof img === 'string') {
    const trimmed = img.trim();
    if (!trimmed) return null;
    if (trimmed.startsWith('data:image/')) return trimmed;
    return `data:image/jpeg;base64,${trimmed}`;
  }
  if (!img.data) return null;
  const mime = img.mime_type || 'image/jpeg';
  return img.data.startsWith('data:image/') ? img.data : `data:${mime};base64,${img.data}`;
}

const THINK_OPEN = '<think>';
const THINK_CLOSE = '</think>';

function trailingPrefixLen(text: string, target: string): number {
  const maxCheck = Math.min(text.length, target.length - 1);
  for (let len = maxCheck; len > 0; len--) {
    if (text.endsWith(target.slice(0, len))) {
      return len;
    }
  }
  return 0;
}

/** Stream chat completion chunks split into structured thinking vs answer tokens. */
export async function* streamChatEvents(
  options: ChatCompletionOptions
): AsyncGenerator<ChatStreamEvent, void, unknown> {
  const apiKey = config.CHAT_API_KEY;
  const apiBase = config.CHAT_API_BASE.replace(/\/+$/, '');
  const model = options.model || config.CHAT_MODEL;

  const url = apiBase.endsWith('/chat/completions')
    ? apiBase
    : `${apiBase}/chat/completions`;

  const formattedMessages: Array<{ role: string; content: OpenAIMessageContent }> = options.messages.map((m) => {
    if (m.role === 'user' && m.images && m.images.length > 0) {
      const parts: Array<
        | { type: 'text'; text: string }
        | { type: 'image_url'; image_url: { url: string } }
      > = [];
      for (const img of m.images) {
        const dataUrl = toDataUrl(img);
        if (dataUrl) {
          parts.push({ type: 'image_url', image_url: { url: dataUrl } });
        }
      }
      if (parts.length > 0) {
        parts.push({ type: 'text', text: m.content });
        return { role: m.role, content: parts };
      }
    }
    return { role: m.role, content: m.content };
  });

  const payload = {
    model,
    messages: formattedMessages,
    stream: true,
  };

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }

  const reqInit: RequestInit = {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  };
  if (options.signal) {
    reqInit.signal = options.signal;
  }

  const response = await fetch(url, reqInit);

  if (!response.ok) {
    const errorText = await response.text();
    const snippet = errorText.slice(0, 200) + (errorText.length > 200 ? '…' : '');
    throw new Error(`Chat upstream error ${response.status}: ${snippet}`);
  }

  if (!response.body) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let inThinkTag = false;
  let tagCarry = '';
  let emittedAnswerToken = false;

  const processContentChunk = function* (chunk: string): Generator<ChatStreamEvent> {
    let working = tagCarry + chunk;
    tagCarry = '';

    while (working.length > 0) {
      const target = inThinkTag ? THINK_CLOSE : THINK_OPEN;
      const idx = working.indexOf(target);
      if (idx !== -1) {
        const before = working.slice(0, idx);
        if (before) {
          if (inThinkTag) {
            yield { kind: 'thinking', text: before };
          } else {
            emittedAnswerToken = true;
            yield { kind: 'token', text: before };
          }
        }
        working = working.slice(idx + target.length);
        inThinkTag = !inThinkTag;
        if (!inThinkTag && !emittedAnswerToken) {
          working = working.replace(/^\n+/, '');
        }
        continue;
      }

      const hold = trailingPrefixLen(working, target);
      const emitPart = hold > 0 ? working.slice(0, working.length - hold) : working;
      tagCarry = hold > 0 ? working.slice(working.length - hold) : '';
      if (emitPart) {
        if (inThinkTag) {
          yield { kind: 'thinking', text: emitPart };
        } else {
          emittedAnswerToken = true;
          yield { kind: 'token', text: emitPart };
        }
      }
      break;
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line || !line.startsWith('data: ')) continue;
        const dataStr = line.slice(6).trim();
        if (dataStr === '[DONE]') {
          if (tagCarry) {
            yield { kind: inThinkTag ? 'thinking' : 'token', text: tagCarry };
            tagCarry = '';
          }
          return;
        }

        try {
          const parsed = JSON.parse(dataStr);
          const delta = parsed.choices?.[0]?.delta as
            | { content?: string; reasoning_content?: string }
            | undefined;
          if (!delta) continue;

          if (delta.reasoning_content) {
            yield { kind: 'thinking', text: delta.reasoning_content };
          }

          if (delta.content) {
            yield* processContentChunk(delta.content);
          }
        } catch {
          // ignore incomplete json chunk
        }
      }
    }
    if (tagCarry) {
      yield { kind: inThinkTag ? 'thinking' : 'token', text: tagCarry };
      tagCarry = '';
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* streamChatCompletions(
  options: ChatCompletionOptions
): AsyncGenerator<string, void, unknown> {
  for await (const ev of streamChatEvents(options)) {
    if (ev.kind === 'token') {
      yield ev.text;
    }
  }
}
