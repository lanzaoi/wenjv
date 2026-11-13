import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';
import { setupTestEnv, type TestEnv } from './helper.js';
import { getVisualStore } from '../src/vector/visual-store.js';
import { registerAsset } from '../src/services/assets.js';

describe('Multimodal Assets & Visual Search (Schema v2)', () => {
  let env: TestEnv;
  let token: string;
  let otherToken: string;
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
    token = ((await login.json()) as { access_token: string }).access_token;

    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'intruder@example.com',
        password: 'Password123!',
      }),
    });
    const login2 = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'intruder@example.com',
        password: 'Password123!',
      }),
    });
    otherToken = ((await login2.json()) as { access_token: string }).access_token;
  });

  afterEach(() => {
    env.cleanup();
  });

  it('serves registered assets via /assets/image with strict traversal & multi-tenant checks', async () => {
    const unauthResp = await env.app.request('/assets/image?path=sample.png');
    expect(unauthResp.status).toBe(401);

    const traversalResp = await env.app.request('/assets/image?path=../../etc/passwd', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(traversalResp.status).toBe(403);

    const testImgPath = path.join(env.tmpDir, 'uploads', 'test-chart.png');
    fs.mkdirSync(path.dirname(testImgPath), { recursive: true });
    const imgBuffer = await sharp({
      create: { width: 64, height: 64, channels: 3, background: { r: 255, g: 0, b: 0 } },
    })
      .png()
      .toBuffer();
    fs.writeFileSync(testImgPath, imgBuffer);

    const asset = await registerAsset({
      id: 'asset_chart_1',
      userId,
      ownerType: 'resource',
      ownerId: 100,
      filename: 'test-chart.png',
      relPath: 'test-chart.png',
      absPath: testImgPath,
      mimeType: 'image/png',
      size: imgBuffer.byteLength,
      caption: '架构图',
    });

    const fetchResp = await env.app.request(`/assets/image?id=${asset.id}&token=${token}`);
    expect(fetchResp.status).toBe(200);
    expect(fetchResp.headers.get('Content-Type')).toBe('image/png');
    const bytes = await fetchResp.arrayBuffer();
    expect(bytes.byteLength).toBe(imgBuffer.byteLength);

    // Cross-tenant access to asset must be blocked with 403
    const crossTenantResp = await env.app.request(`/assets/image?id=${asset.id}`, {
      headers: { Authorization: `Bearer ${otherToken}` },
    });
    expect(crossTenantResp.status).toBe(403);
  });

  it('searches by image via slim visual_vectors and hydrates from SQLite assets', async () => {
    const testImgPath = path.join(env.tmpDir, 'uploads', 'vec-chart.png');
    fs.mkdirSync(path.dirname(testImgPath), { recursive: true });
    const imgBuffer = await sharp({
      create: { width: 32, height: 32, channels: 3, background: { r: 0, g: 128, b: 255 } },
    })
      .png()
      .toBuffer();
    fs.writeFileSync(testImgPath, imgBuffer);

    await registerAsset({
      id: 'vis_doc_1',
      userId,
      ownerType: 'resource',
      ownerId: 100,
      filename: 'vec-chart.png',
      relPath: 'vec-chart.png',
      absPath: testImgPath,
      mimeType: 'image/png',
      size: imgBuffer.byteLength,
      caption: '图表：深度学习模型架构图',
    });

    const vStore = getVisualStore();
    await vStore.addVectors([
      {
        id: 'vis_doc_1',
        vector: new Array(768).fill(0.01),
        user_id: String(userId),
        owner_type: 'resource',
        owner_id: '100',
      },
    ]);

    const formData = new FormData();
    formData.append('file', new Blob([imgBuffer], { type: 'image/png' }), 'query.png');
    formData.append('window_size', '3');

    const resp = await env.app.request('/search/by-image', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });

    expect(resp.status).toBe(200);
    const data = (await resp.json()) as {
      documents: Array<{ page_content: string; metadata: { image_url: string } }>;
      count: number;
    };
    expect(data.documents).toBeDefined();
    expect(Array.isArray(data.documents)).toBe(true);
    if (data.count > 0) {
      expect(data.documents[0]?.page_content).toContain('架构图');
      expect(data.documents[0]?.metadata.image_url).toContain('/api/assets/image?id=vis_doc_1');
    }
  });
});
