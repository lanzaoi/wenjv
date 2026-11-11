import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { claimNextJob, executeJob } from '../src/services/jobs.js';

describe('Search Service & Routes (S3)', () => {
  let env: TestEnv;
  let token: string;

  beforeEach(async () => {
    env = setupTestEnv();

    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'carol@example.com',
        password: 'Password123!',
      }),
    });

    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'carol@example.com',
        password: 'Password123!',
      }),
    });
    const loginData = (await login.json()) as { access_token: string };
    token = loginData.access_token;

    // Create and index two notes
    await env.app.request('/file/note', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '向量检索原理',
        content: '密集向量检索使用深度神经网络模型提取文本特征，并通过余弦相似度或L2距离进行高维向量空间邻近搜索。',
      }),
    });
    let j = claimNextJob();
    if (j) await executeJob(j);

    await env.app.request('/file/note', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '全栈架构演进',
        content: '从FastAPI和Python技术栈平滑过渡到Hono与Node.js全栈TypeScript架构。',
      }),
    });
    j = claimNextJob();
    if (j) await executeJob(j);
  });

  afterEach(() => {
    env.cleanup();
  });

  it('performs hybrid search with query ranking and returns top hits', async () => {
    const searchResp = await env.app.request('/documents/search', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: '向量检索 余弦相似度',
        window_size: 5,
      }),
    });

    expect(searchResp.status).toBe(200);
    const body = (await searchResp.json()) as {
      documents: Array<{ id: string; page_content: string; score: number }>;
      count: number;
    };
    expect(body.count).toBeGreaterThan(0);
    expect(body.documents.length).toBeGreaterThan(0);
    expect(body.documents[0]?.page_content).toContain('余弦相似度');
    expect(body.documents[0]?.score).toBeGreaterThan(0);
    expect((body.documents[0] as any)?.metadata?.id).toBeDefined();
  });
});
