import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { claimNextJob, executeJob } from '../src/services/jobs.js';
import { getDb } from '../src/db/index.js';

describe('Golden Master Integration (G2 & Walking Skeleton)', () => {
  let env: TestEnv;
  let token: string;
  let userId: number;

  beforeEach(async () => {
    env = setupTestEnv();

    // 1. Register & Login
    const regResp = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'golden-user@example.com',
        password: 'Password123!',
      }),
    });
    expect(regResp.status).toBe(201);
    const regData = (await regResp.json()) as { id: number };
    userId = regData.id;

    const loginResp = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'golden-user@example.com',
        password: 'Password123!',
      }),
    });
    expect(loginResp.status).toBe(200);
    const loginData = (await loginResp.json()) as { access_token: string };
    token = loginData.access_token;
  });

  afterEach(() => {
    env.cleanup();
  });

  it('ingests golden corpus and executes end-to-end hybrid retrieval verification', async () => {
    const corpusDir = path.resolve(process.cwd(), '../../tools/golden/corpus');
    if (!fs.existsSync(corpusDir)) {
      return;
    }

    const filesToTest = [
      'arch.md',
      'ts-guide.md',
      'wiki-concept.md',
      'db-design.md',
      'notes.txt',
      'article1.html',
      'doc_1.docx',
      'presentation_1.pptx',
    ];

    const uploadedIds: number[] = [];

    for (const filename of filesToTest) {
      const filePath = path.join(corpusDir, filename);
      if (!fs.existsSync(filePath)) continue;

      const fileBuffer = fs.readFileSync(filePath);
      const fd = new FormData();
      fd.append('file', new Blob([fileBuffer]), filename);

      const upResp = await env.app.request('/file/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });

      expect(upResp.status).toBe(201);
      const upData = (await upResp.json()) as { id: number };
      uploadedIds.push(upData.id);
    }

    expect(uploadedIds.length).toBe(filesToTest.length);

    // Process all ingestion jobs until queue is empty
    let job = claimNextJob();
    let processedCount = 0;
    while (job) {
      await executeJob(job);
      processedCount++;
      job = claimNextJob();
    }

    expect(processedCount).toBeGreaterThanOrEqual(filesToTest.length);

    // Verify all uploaded files reached 'finished' status
    const db = getDb();
    for (const fileId of uploadedIds) {
      const row = db.prepare('SELECT status FROM file_uploads WHERE id = ?').get(fileId) as { status: string };
      expect(row.status).toBe('finished');
    }

    // Verify hybrid search queries return top-ranked hits with content match
    const testQueries = [
      { q: 'TypeScript 强类型', expectedSnippet: 'TypeScript' },
      { q: '知识图谱 双向链接', expectedSnippet: '知识图谱' },
      { q: 'WAL 模式 关系型数据库', expectedSnippet: 'WAL' },
      { q: 'Readability 算法 网页', expectedSnippet: 'Readability' },
      { q: '演示文稿 向量索引', expectedSnippet: '演示文稿' },
    ];

    for (const tq of testQueries) {
      const sResp = await env.app.request('/documents/search', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          prompt: tq.q,
          window_size: 3,
        }),
      });

      expect(sResp.status).toBe(200);
      const sData = (await sResp.json()) as {
        documents: Array<{ page_content: string; score: number }>;
        count: number;
      };
      expect(sData.count).toBeGreaterThan(0);
      const hitFound = sData.documents.some((d) => d.page_content.includes(tq.expectedSnippet));
      expect(hitFound).toBe(true);
    }
  });
});
