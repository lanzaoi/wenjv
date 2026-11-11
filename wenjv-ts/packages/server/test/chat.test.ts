import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';

describe('Chat Routes (S5)', () => {
  let env: TestEnv;
  let token: string;

  beforeEach(async () => {
    env = setupTestEnv();

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

  afterEach(() => {
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

  it('uploads chat attachment and performs chat by image', async () => {
    const sharp = (await import('sharp')).default;
    const pngBuffer = await sharp({
      create: {
        width: 100,
        height: 100,
        channels: 3,
        background: { r: 255, g: 0, b: 0 },
      },
    })
      .png()
      .toBuffer();

    // 1. Upload attachment
    const fd = new FormData();
    fd.append('file', new Blob([pngBuffer], { type: 'image/png' }), 'test-chat.png');
    fd.append('session_id', 'sess-123');

    const attachResp = await env.app.request('/chat/attachments', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    expect(attachResp.status).toBe(200);
    const attachData = (await attachResp.json()) as { media_url: string; media_id: string };
    expect(attachData.media_url).toContain('/api/documents/assets/image');
    expect(attachData.media_id).toContain('.jpg');

    // 2. Chat by image
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
  });
});
