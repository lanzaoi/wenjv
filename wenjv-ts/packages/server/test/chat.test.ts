import http from 'node:http';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { loadConfig } from '../src/config.js';
import { setupTestEnv, type TestEnv } from './helper.js';

interface RecordedLlmRequest {
  url: string | undefined;
  authorization: string | undefined;
  body: {
    model?: string;
    stream?: boolean;
    messages?: Array<{
      role: string;
      content: string | Array<{ type: string; text?: string; image_url?: { url: string } }>;
    }>;
  };
}

function parseSseBody(raw: string): Array<Record<string, unknown>> {
  const events: Array<Record<string, unknown>> = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) continue;
    const payload = trimmed.slice(5).trim();
    if (!payload) continue;
    events.push(JSON.parse(payload) as Record<string, unknown>);
  }
  return events;
}

async function startTestLlmServer(): Promise<{
  baseUrl: string;
  requests: RecordedLlmRequest[];
  close: () => Promise<void>;
}> {
  const requests: RecordedLlmRequest[] = [];
  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const rawBody = Buffer.concat(chunks).toString('utf8');
      requests.push({
        url: req.url,
        authorization: req.headers['authorization'],
        body: JSON.parse(rawBody) as RecordedLlmRequest['body'],
      });
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      });
      res.write(`data: ${JSON.stringify({ choices: [{ delta: { reasoning_content: '分析中' } }] })}\n\n`);
      res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: '测试' } }] })}\n\n`);
      res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: '回答' } }] })}\n\n`);
      res.write('data: [DONE]\n\n');
      res.end();
    });
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()));
  const addr = server.address();
  const port = typeof addr === 'object' && addr ? addr.port : 0;

  return {
    baseUrl: `http://127.0.0.1:${port}/v2`,
    requests,
    close: () => new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve()))),
  };
}

describe('Chat Routes (S5)', () => {
  let env: TestEnv;
  let token: string;
  let llmServer: Awaited<ReturnType<typeof startTestLlmServer>>;

  beforeEach(async () => {
    env = setupTestEnv();
    llmServer = await startTestLlmServer();
    loadConfig({
      BASE_DIR: env.tmpDir,
      DB_PATH: `${env.tmpDir}/test.db`,
      LANCE_DIR: `${env.tmpDir}/lance_db`,
      UPLOAD_DIR: `${env.tmpDir}/uploads`,
      VAULT_DIR: `${env.tmpDir}/wiki_vault`,
      CHAT_API_BASE: llmServer.baseUrl,
      CHAT_API_KEY: 'test-spark-key',
      CHAT_MODEL: 'spark-x2.6',
    });

    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'eva@example.com',
        password: 'Password123!',
      }),
    });

    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'eva@example.com',
        password: 'Password123!',
      }),
    });
    const loginData = (await login.json()) as { access_token: string };
    token = loginData.access_token;
  });

  afterEach(async () => {
    await llmServer.close();
    env.cleanup();
  });

  it('lists chat models', async () => {
    const resp = await env.app.request('/chat/models', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status).toBe(200);
    const data = (await resp.json()) as { models: string[] };
    expect(Array.isArray(data.models)).toBe(true);
    expect(data.models.length).toBeGreaterThan(0);
    expect(data.models).toContain('spark-x2.6');
  });

  it('streams SSE events on POST /chat with reasoning tokens and resolved multimodal attachment images', async () => {
    const sharp = (await import('sharp')).default;
    const pngBuffer = await sharp({
      create: { width: 40, height: 40, channels: 3, background: { r: 20, g: 180, b: 90 } },
    })
      .png()
      .toBuffer();

    const fd = new FormData();
    fd.append('file', new Blob([pngBuffer], { type: 'image/png' }), 'diagram.png');
    fd.append('session_id', 'sess-mm');
    const attachResp = await env.app.request('/chat/attachments', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    expect(attachResp.status).toBe(200);
    const attachData = (await attachResp.json()) as { asset_id: string; media_url: string; media_id: string };
    expect(attachData.asset_id).toBeTruthy();
    expect(attachData.media_url).toContain('/api/assets/image');
    expect(attachData.media_id).toContain('.jpg');

    const chatResp = await env.app.request('/chat', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question: '请描述附图颜色',
        use_rag: false,
        images: [attachData.media_url],
        history: [
          { role: 'user', content: '远期附图消息', images: [attachData.media_url] },
          { role: 'assistant', content: '好的' },
          { role: 'user', content: '最近消息' },
        ],
      }),
    });
    expect(chatResp.status).toBe(200);
    expect(chatResp.headers.get('content-type')).toContain('text/event-stream');

    const rawSse = await chatResp.text();
    const events = parseSseBody(rawSse);
    expect(events[0]?.['type']).toBe('citations');
    expect(events[events.length - 1]?.['type']).toBe('done');

    const tokenText = events
      .filter((e) => e['type'] === 'token')
      .map((e) => String(e['content'] ?? ''))
      .join('');
    expect(tokenText).toContain('思考过程');
    expect(tokenText).toContain('分析中');
    expect(tokenText).toContain('测试回答');

    // Verify upstream OpenAI request received multipart image_url on current turn
    // and decayed the distant history turn (>= 2 turns before latest history item)
    expect(llmServer.requests.length).toBe(1);
    const sent = llmServer.requests[0]!;
    expect(sent.authorization).toBe('Bearer test-spark-key');
    const sentMsgs = sent.body.messages || [];
    const oldTurn = sentMsgs.find((m) => typeof m.content === 'string' && m.content.includes('远期附图消息'));
    expect(oldTurn).toBeDefined();
    expect(String(oldTurn?.content)).toContain('历史附图');

    const lastMsg = sentMsgs[sentMsgs.length - 1]!;
    expect(lastMsg.role).toBe('user');
    expect(Array.isArray(lastMsg.content)).toBe(true);
    const parts = lastMsg.content as Array<{ type: string; image_url?: { url: string }; text?: string }>;
    expect(parts.some((p) => p.type === 'image_url' && p.image_url?.url.startsWith('data:image/jpeg;base64,'))).toBe(true);
  });

  it('forwards uploaded image as image_url in POST /chat/by-image even when use_rag=false', async () => {
    const sharp = (await import('sharp')).default;
    const pngBuffer = await sharp({
      create: { width: 60, height: 60, channels: 3, background: { r: 255, g: 0, b: 0 } },
    })
      .png()
      .toBuffer();

    const imgFd = new FormData();
    imgFd.append('file', new Blob([pngBuffer], { type: 'image/png' }), 'query-img.png');
    imgFd.append('prompt', '图片里有什么？');
    imgFd.append('use_rag', 'false');

    const chatResp = await env.app.request('/chat/by-image', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: imgFd,
    });
    expect(chatResp.status).toBe(200);
    expect(chatResp.headers.get('content-type')).toContain('text/event-stream');

    const events = parseSseBody(await chatResp.text());
    expect(events[0]?.['type']).toBe('citations');
    expect(events[events.length - 1]?.['type']).toBe('done');
    const tokenText = events
      .filter((e) => e['type'] === 'token')
      .map((e) => String(e['content'] ?? ''))
      .join('');
    expect(tokenText).toContain('测试回答');

    expect(llmServer.requests.length).toBe(1);
    const lastMsg = llmServer.requests[0]!.body.messages!.at(-1)!;
    expect(Array.isArray(lastMsg.content)).toBe(true);
    const parts = lastMsg.content as Array<{ type: string; image_url?: { url: string } }>;
    expect(parts.some((p) => p.type === 'image_url' && p.image_url?.url.startsWith('data:image/'))).toBe(true);
  });
});
