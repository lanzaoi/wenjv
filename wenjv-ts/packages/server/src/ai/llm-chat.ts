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

export async function* streamChatCompletions(
  options: ChatCompletionOptions
): AsyncGenerator<string, void, unknown> {
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
    throw new Error(`Chat upstream error ${response.status}: ${errorText}`);
  }

  if (!response.body) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let inReasoning = false;

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
        if (dataStr === '[DONE]') return;

        try {
          const parsed = JSON.parse(dataStr);
          const delta = parsed.choices?.[0]?.delta as
            | { content?: string; reasoning_content?: string }
            | undefined;
          if (!delta) continue;

          if (delta.reasoning_content) {
            if (!inReasoning) {
              inReasoning = true;
              yield '> 💭 *思考过程*：\n> ';
            }
            yield delta.reasoning_content.replace(/\n/g, '\n> ');
          }

          if (delta.content) {
            if (inReasoning) {
              inReasoning = false;
              yield '\n\n';
            }
            yield delta.content;
          }
        } catch {
          // ignore incomplete json chunk
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
