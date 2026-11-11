import { config } from '../config.js';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
  images?: Array<string | { data: string; mime_type?: string }>;
}

export interface ChatCompletionOptions {
  model?: string;
  messages: ChatMessage[];
  signal?: AbortSignal;
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

  const formattedMessages = options.messages.map((m) => ({
    role: m.role,
    content: m.content,
  }));

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
          const delta = parsed.choices?.[0]?.delta;
          if (delta?.content) {
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
