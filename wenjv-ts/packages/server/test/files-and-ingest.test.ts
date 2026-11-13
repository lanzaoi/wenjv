import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { claimNextJob, executeJob, enqueueJob } from '../src/services/jobs.js';
import { getDb } from '../src/db/index.js';
import { matchFts5 } from '../src/db/fts5.js';

describe('Unified Resources, Relational Tags & Ingestion Pipeline (Schema v2)', () => {
  let env: TestEnv;
  let token: string;
  let userId: number;

  beforeEach(async () => {
    env = setupTestEnv();

    const reg = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'bob@example.com',
        password: 'Password123!',
      }),
    });
    const regData = (await reg.json()) as { id: number };
    userId = regData.id;

    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'bob@example.com',
        password: 'Password123!',
      }),
    });
    const loginData = (await login.json()) as { access_token: string };
    token = loginData.access_token;
  });

  afterEach(() => {
    env.cleanup();
  });

  it('uploads a file via /resources/files, syncs chunks+FTS5 via triggers, and cascades delete', async () => {
    const formData = new FormData();
    const mdContent = '# 问据开发指南\n\n问据是一个基于 TypeScript 构建的知识库系统。\n\n## 向量模型\n\n本地使用 BGE-M3 进行向量嵌入。';
    const blob = new Blob([mdContent], { type: 'text/markdown' });
    formData.append('file', blob, 'guide.md');

    const uploadResp = await env.app.request('/resources/files', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    expect(uploadResp.status).toBe(201);
    const resRecord = (await uploadResp.json()) as { id: number; type: string; status: string; filename: string };
    expect(resRecord.type).toBe('file');
    expect(resRecord.status).toBe('pending');

    const job = claimNextJob();
    expect(job).not.toBeNull();
    expect(job!.entity_type).toBe('resource');
    expect(job!.entity_id).toBe(resRecord.id);

    await executeJob(job!);

    const db = getDb();
    const updated = db.prepare('SELECT status FROM resources WHERE id = ?').get(resRecord.id) as { status: string };
    expect(updated.status).toBe('finished');

    // Authoritative chunks table & FTS5 trigger sync verification
    const chunkCount = (
      db.prepare("SELECT COUNT(*) AS c FROM chunks WHERE entity_type = 'resource' AND entity_id = ?").get(resRecord.id) as { c: number }
    ).c;
    expect(chunkCount).toBeGreaterThan(0);

    const hits = matchFts5(db, 'TypeScript 知识库', { userId });
    expect(hits.length).toBeGreaterThan(0);
    expect(hits[0]?.source).toBe(resRecord.filename);

    // Retry on succeeded job rejected with 409
    const retryResp = await env.app.request(`/jobs/${job!.id}/retry`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(retryResp.status).toBe(409);

    // Delete via unified DELETE /resources/:id and verify chunks & FTS trigger purge
    const delResp = await env.app.request(`/resources/${resRecord.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delResp.status).toBe(200);
    expect(matchFts5(db, 'TypeScript 知识库', { userId }).length).toBe(0);
  });

  it('creates/updates notes and manages O(1) relational tags via /tags and /resources', async () => {
    const noteResp = await env.app.request('/resources/notes', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '会议随手记',
        content: '今天讨论了问据 Schema v2 精简方案。',
        tags: ['meeting', 'v2'],
      }),
    });
    expect(noteResp.status).toBe(201);
    const noteRecord = (await noteResp.json()) as { id: number; type: string; tags: string[] };
    expect(noteRecord.type).toBe('note');
    expect(noteRecord.tags).toEqual(['meeting', 'v2']);

    const job = claimNextJob();
    expect(job).not.toBeNull();
    await executeJob(job!);

    // Unified listing filtered by tag
    const listByTag = await env.app.request('/resources?tag=meeting', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(listByTag.status).toBe(200);
    const listData = (await listByTag.json()) as { resources: Array<{ id: number }>; total: number };
    expect(listData.total).toBe(1);
    expect(listData.resources[0]?.id).toBe(noteRecord.id);

    // Patch note content
    const patchResp = await env.app.request(`/resources/${noteRecord.id}`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content: '更新后的 Schema v2 正文。' }),
    });
    expect(patchResp.status).toBe(200);

    // O(1) Global Tag Rename via PUT /tags/:id
    const tagsListResp = await env.app.request('/tags', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(tagsListResp.status).toBe(200);
    const tagsData = (await tagsListResp.json()) as { tags: Array<{ id: number; name: string; count: number }> };
    const meetingTag = tagsData.tags.find((t) => t.name === 'meeting');
    expect(meetingTag).toBeDefined();

    const renameTagResp = await env.app.request(`/tags/${meetingTag!.id}`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name: 'weekly-sync', color: '#0ea5e9' }),
    });
    expect(renameTagResp.status).toBe(200);

    // Resource immediately reflects renamed tag without touching resources table
    const detailResp = await env.app.request(`/resources/${noteRecord.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const detailData = (await detailResp.json()) as { tags: string[] };
    expect(detailData.tags).toContain('weekly-sync');
    expect(detailData.tags).not.toContain('meeting');

    // Delete resource cleans entity_tags
    const delResp = await env.app.request(`/resources/${noteRecord.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delResp.status).toBe(200);

    const tagsAfterDel = (await (
      await env.app.request('/tags', { headers: { Authorization: `Bearer ${token}` } })
    ).json()) as { tags: Array<{ name: string; count: number }> };
    const syncTag = tagsAfterDel.tags.find((t) => t.name === 'weekly-sync');
    expect(syncTag?.count).toBe(0);
  });

  it('enforces partial unique index on pending ingestion_jobs (BUG-14)', () => {
    const db = getDb();

    const j1 = enqueueJob({ entity_type: 'resource', entity_id: 9001, user_id: userId, user_email: 'bob@example.com' });
    const j2 = enqueueJob({ entity_type: 'resource', entity_id: 9001, user_id: userId, user_email: 'bob@example.com' });
    expect(j2.id).toBe(j1.id);

    expect(() => {
      db.prepare(`
        INSERT INTO ingestion_jobs(entity_type, entity_id, user_id, user_email, payload, status, attempts, max_attempts)
        VALUES ('resource', 9001, ?, 'bob@example.com', '{}', 'pending', 0, 3)
      `).run(userId);
    }).toThrow(/UNIQUE constraint failed/i);

    db.prepare("UPDATE ingestion_jobs SET status = 'succeeded' WHERE id = ?").run(j1.id);
    const j3 = enqueueJob({ entity_type: 'resource', entity_id: 9001, user_id: userId, user_email: 'bob@example.com' });
    expect(j3.id).not.toBe(j1.id);
  });
});
