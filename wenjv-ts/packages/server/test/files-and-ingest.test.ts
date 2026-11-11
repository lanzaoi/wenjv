import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { claimNextJob, executeJob } from '../src/services/jobs.js';
import { getDb } from '../src/db/index.js';
import { matchFts5 } from '../src/db/fts5.js';

describe('Files, Notes and Ingestion Pipeline (S0 & S2)', () => {
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

  it('uploads a markdown file, processes the ingestion job, and updates search indexes', async () => {
    const formData = new FormData();
    const mdContent = '# 问据开发指南\n\n问据是一个基于 TypeScript 构建的知识库系统。\n\n## 向量模型\n\n本地使用 BGE-M3 进行向量嵌入。';
    const blob = new Blob([mdContent], { type: 'text/markdown' });
    formData.append('file', blob, 'guide.md');

    // 1. Upload file
    const uploadResp = await env.app.request('/file/upload', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    });
    expect(uploadResp.status).toBe(201);
    const fileRecord = (await uploadResp.json()) as { id: number; status: string; filename: string };
    expect(fileRecord.status).toBe('pending');
    expect(fileRecord.id).toBeGreaterThan(0);

    // 2. Claim and execute job
    const job = claimNextJob();
    expect(job).not.toBeNull();
    expect(job!.job_type).toBe('file');
    expect(job!.resource_id).toBe(fileRecord.id);

    await executeJob(job!);

    // Verify file is marked finished
    const db = getDb();
    const updatedFile = db.prepare('SELECT status FROM file_uploads WHERE id = ?').get(fileRecord.id) as { status: string };
    expect(updatedFile.status).toBe('finished');

    // Verify polling status by filename
    const pollResp = await env.app.request(`/file/status/${encodeURIComponent(fileRecord.filename)}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(pollResp.status).toBe(200);
    const pollJson = (await pollResp.json()) as { status: string };
    expect(pollJson.status).toBe('finished');

    // Verify job retry rejected on succeeded job with 409
    const retryResp = await env.app.request(`/jobs/${job!.id}/retry`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(retryResp.status).toBe(409);

    // Verify FTS index has chunks
    const hits = matchFts5(db, 'TypeScript 知识库', { userId });
    expect(hits.length).toBeGreaterThan(0);
    expect(hits[0]?.filename).toBe(fileRecord.filename);

    // Verify delete by filename
    const delFileResp = await env.app.request(`/file/${encodeURIComponent(fileRecord.filename)}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delFileResp.status).toBe(200);
    expect((await delFileResp.json()) as { status: string }).toEqual({ status: 'deleted' });
  });

  it('creates a note, processes ingestion, and retrieves by filename', async () => {
    const noteResp = await env.app.request('/file/note', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '会议随手记',
        content: '今天讨论了问据向全栈 TypeScript 迁移的执行方案。',
        tags: ['meeting', 'typescript'],
      }),
    });
    expect(noteResp.status).toBe(201);
    const noteRecord = (await noteResp.json()) as { id: number; filename: string };

    const job = claimNextJob();
    expect(job).not.toBeNull();
    await executeJob(job!);

    const getNote = await env.app.request(`/file/note/${encodeURIComponent(noteRecord.filename)}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(getNote.status).toBe(200);
    const noteData = (await getNote.json()) as { title: string; content: string };
    expect(noteData.title).toBe('会议随手记');
    expect(noteData.content).toContain('迁移的执行方案');

    // List notes
    const listNotesResp = await env.app.request('/file/note', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(listNotesResp.status).toBe(200);
    const notesList = (await listNotesResp.json()) as { notes: Array<{ id: number; title: string }>; total: number };
    expect(notesList.total).toBeGreaterThan(0);
    expect(notesList.notes.some((n) => n.id === noteRecord.id)).toBe(true);

    // Patch note
    const patchResp = await env.app.request(`/file/note/${encodeURIComponent(noteRecord.filename)}`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content: '更新后的会议随手记正文。' }),
    });
    expect(patchResp.status).toBe(200);
    const patchData = (await patchResp.json()) as { updated: boolean };
    expect(patchData.updated).toBe(true);

    // Sync notes
    const syncResp = await env.app.request('/file/note/sync', {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(syncResp.status).toBe(200);

    // Update tags format
    const updateTagsResp = await env.app.request(`/documents/note/${noteRecord.id}/tags`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ tags: ['urgent', 'review'] }),
    });
    expect(updateTagsResp.status).toBe(200);
    expect(await updateTagsResp.json()).toEqual({ tags: ['urgent', 'review'] });

    // Backfill tags format
    const backfillResp = await env.app.request('/documents/tags/backfill', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(backfillResp.status).toBe(200);
    expect(await backfillResp.json()).toEqual({ enqueued_count: 0 });

    // Delete note
    const delNoteResp = await env.app.request(`/file/note/${encodeURIComponent(noteRecord.filename)}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delNoteResp.status).toBe(200);
    expect((await delNoteResp.json()) as { status: string }).toEqual({ status: 'deleted' });
  });
});
