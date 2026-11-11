import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';
import { setupTestEnv, type TestEnv } from './helper.js';
import { getVisualStore } from '../src/vector/visual-store.js';

describe('Multimodal & Visual Search (S8)', () => {
  let env: TestEnv;
  let token: string;
  let userId: number;

  beforeEach(async () => {
    env = setupTestEnv();

    const reg = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'visual@example.com',
        password: 'Password123!',
      }),
    });
    const regData = (await reg.json()) as { id: number };
    userId = regData.id;

    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'visual@example.com',
        password: 'Password123!',
      }),
    });
    const loginData = (await login.json()) as { access_token: string };
    token = loginData.access_token;
  });

  afterEach(() => {
    env.cleanup();
  });

  it('serves image assets securely and blocks unauthorized or path traversal access', async () => {
    // 1. Unauthenticated request should fail
    const unauthResp = await env.app.request('/documents/assets/image?path=sample.png');
    expect(unauthResp.status).toBe(401);

    // 2. Path traversal should fail with 403
    const traversalResp = await env.app.request('/documents/assets/image?path=../../etc/passwd', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(traversalResp.status).toBe(403);

    // 3. Create a valid test image in upload directory
    const testImgPath = path.join(env.tmpDir, 'uploads', 'test-chart.png');
    fs.mkdirSync(path.dirname(testImgPath), { recursive: true });
    const imgBuffer = await sharp({
      create: {
        width: 64,
        height: 64,
        channels: 3,
        background: { r: 255, g: 0, b: 0 },
      },
    })
      .png()
      .toBuffer();
    fs.writeFileSync(testImgPath, imgBuffer);

    // 4. Fetch valid image with query token
    const fetchResp = await env.app.request(`/documents/assets/image?path=test-chart.png&token=${token}`);
    expect(fetchResp.status).toBe(200);
    expect(fetchResp.headers.get('Content-Type')).toBe('image/png');
    const bytes = await fetchResp.arrayBuffer();
    expect(bytes.byteLength).toBe(imgBuffer.byteLength);
  });

  it('searches documents by image and merges visual store results', async () => {
    // Seed a visual store item
    const vStore = getVisualStore();
    await vStore.addDocuments([
      {
        id: 'vis_doc_1',
        vector: new Array(768).fill(0.01),
        page_content: '图表：深度学习模型架构图',
        image_path: 'test-chart.png',
        source: 'test-chart.png',
        page: '1',
        title: '架构图',
        filename: 'test-chart.png',
        belongs_to: 'visual@example.com',
        user_id: String(userId),
        file_id: '100',
        resource_id: '100',
        source_type: 'file',
      },
    ]);

    const imgBuffer = await sharp({
      create: {
        width: 32,
        height: 32,
        channels: 3,
        background: { r: 0, g: 128, b: 255 },
      },
    })
      .png()
      .toBuffer();

    const formData = new FormData();
    const blob = new Blob([imgBuffer], { type: 'image/png' });
    formData.append('file', blob, 'query.png');
    formData.append('window_size', '3');

    const resp = await env.app.request('/documents/search/by-image', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    });

    expect(resp.status).toBe(200);
    const data = (await resp.json()) as { documents: unknown[]; count: number };
    expect(data.documents).toBeDefined();
    expect(Array.isArray(data.documents)).toBe(true);
  });
});
