import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import http from 'node:http';
import sharp from 'sharp';
import { setupTestEnv, type TestEnv } from './helper.js';
import { loadConfig } from '../src/config.js';
import { OcrSidecarClient } from '../src/ai/ocr-client.js';
import { claimNextJob, executeJob } from '../src/services/jobs.js';
import { getDb } from '../src/db/index.js';
import { getVisualStore } from '../src/vector/visual-store.js';

interface MockServerHandle {
  url: string;
  requests: Array<{ path: string; bodyText: string }>;
  close: () => Promise<void>;
}

async function startMockOcrServer(): Promise<MockServerHandle> {
  const requests: Array<{ path: string; bodyText: string }> = [];
  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const bodyText = Buffer.concat(chunks).toString('utf8');
      requests.push({ path: req.url || '/', bodyText });

      if (req.url === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', engines: { rapidocr: true, pix2text: true } }));
        return;
      }

      if (req.url === '/ocr/image') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(
          JSON.stringify({
            text: '总相位差公式 $$\\Delta\\varphi = 121\\pi$$ 满足干涉相消条件',
            engine: 'pix2text+ppocrv5',
            mode: 'auto',
            elapsed_ms: 42,
          })
        );
        return;
      }

      if (req.url === '/ocr/pdf') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(
          JSON.stringify({
            text: '扫描件第1页：波动光学光程差实验讲义',
            engine: 'ppocrv5-mobile',
            mode: 'general',
            elapsed_ms: 55,
            pages: 1,
          })
        );
        return;
      }

      res.writeHead(404);
      res.end();
    });
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()));
  const addr = server.address();
  const port = typeof addr === 'object' && addr ? addr.port : 0;
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}

describe('Local OCR Sidecar & Multimodal Ingestion', () => {
  let env: TestEnv;
  let token: string;
  let userId: number;
  let mockOcr: MockServerHandle;

  beforeEach(async () => {
    env = setupTestEnv();
    mockOcr = await startMockOcrServer();

    const reg = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'ocr@example.com',
        password: 'Password123!',
      }),
    });
    const regData = (await reg.json()) as { id: number };
    userId = regData.id;

    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'ocr@example.com',
        password: 'Password123!',
      }),
    });
    token = ((await login.json()) as { access_token: string }).access_token;
  });

  afterEach(async () => {
    await mockOcr.close();
    env.cleanup();
  });

  it('OcrSidecarClient handles health, image/pdf calls, disabled state, and unreachable fail-open', async () => {
    const disabled = new OcrSidecarClient({ enabled: false, baseUrl: mockOcr.url });
    expect(await disabled.health()).toEqual({ ok: false, status: 'disabled' });
    expect(await disabled.recognizeImage(Buffer.from('img'), 'a.png')).toBeNull();

    const unreachable = new OcrSidecarClient({ enabled: true, baseUrl: 'http://127.0.0.1:19997', timeoutMs: 1000 });
    expect((await unreachable.health()).ok).toBe(false);
    expect(await unreachable.recognizeImage(Buffer.from('img'), 'a.png')).toBeNull();

    const client = new OcrSidecarClient({ enabled: true, baseUrl: mockOcr.url });
    const h = await client.health();
    expect(h.ok).toBe(true);
    const imgRes = await client.recognizeImage(Buffer.from('pngbytes'), 'note.png', 'formula');
    expect(imgRes?.text).toContain('干涉相消条件');
    expect(imgRes?.engine).toBe('pix2text+ppocrv5');

    const pdfRes = await client.recognizePdf(Buffer.from('%PDF-1.4'), 'scan.pdf', 'general');
    expect(pdfRes?.text).toContain('光程差');
    expect(pdfRes?.pages).toBe(1);
  });

  it('indexes OCR text + SigLIP2 vector for uploaded images and supports /resources/:id/reingest', async () => {
    loadConfig({
      BASE_DIR: env.tmpDir,
      DB_PATH: `${env.tmpDir}/test.db`,
      LANCE_DIR: `${env.tmpDir}/lance_db`,
      UPLOAD_DIR: `${env.tmpDir}/uploads`,
      VAULT_DIR: `${env.tmpDir}/wiki_vault`,
      OCR_ENABLED: true,
      OCR_SIDECAR_URL: mockOcr.url,
      OCR_IMAGE_MODE: 'auto',
    });

    const imgBuf = await sharp({
      create: { width: 120, height: 80, channels: 4, background: { r: 245, g: 245, b: 245, alpha: 1 } },
    })
      .png()
      .toBuffer();

    const form = new FormData();
    form.append('file', new Blob([Uint8Array.from(imgBuf)], { type: 'image/png' }), 'physics-note.png');
    const uploadResp = await env.app.request('/resources/files', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    expect(uploadResp.status).toBe(201);
    const uploaded = (await uploadResp.json()) as { id: number };

    const job = claimNextJob();
    expect(job).not.toBeNull();
    await executeJob(job!);

    // Verify OCR text is persisted on resources.content_text and searchable in FTS5
    const detailResp = await env.app.request(`/resources/${uploaded.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(detailResp.status).toBe(200);
    const detail = (await detailResp.json()) as { content?: string; status: string };
    expect(detail.status).toBe('finished');
    expect(detail.content).toContain('干涉相消条件');

    const searchResp = await env.app.request('/search', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: '干涉相消', window_size: 5 }),
    });
    expect(searchResp.status).toBe(200);
    const searchData = (await searchResp.json()) as {
      documents: Array<{ page_content: string }>;
      count: number;
    };
    expect(searchData.count).toBeGreaterThan(0);
    expect(searchData.documents[0]?.page_content).toContain('121\\pi');

    // Verify visual vector exists and is non-zero
    const db = getDb();
    const assetRow = db
      .prepare("SELECT id, caption FROM assets WHERE owner_type = 'resource' AND owner_id = ?")
      .get(String(uploaded.id)) as { id: string; caption: string } | undefined;
    expect(assetRow).toBeDefined();
    expect(assetRow?.caption).toContain('干涉相消');
    const visHits = await getVisualStore().search(new Array(768).fill(0.03), { limit: 5, userId });
    expect(visHits.some((h) => h.id === assetRow?.id)).toBe(true);

    // Trigger manual re-ingest with formula mode
    const reResp = await env.app.request(`/resources/${uploaded.id}/reingest`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ ocr_mode: 'formula' }),
    });
    expect(reResp.status).toBe(202);
    const reJob = claimNextJob();
    expect(reJob).not.toBeNull();
    await executeJob(reJob!);

    const ocrCalls = mockOcr.requests.filter((r) => r.path === '/ocr/image');
    expect(ocrCalls.length).toBe(2);
    expect(ocrCalls[1]?.bodyText).toContain('formula');

    // Verify stale asset rows aren't duplicated on re-ingest
    const assetRows = db
      .prepare("SELECT id FROM assets WHERE owner_type = 'resource' AND owner_id = ?")
      .all(String(uploaded.id));
    expect(assetRows.length).toBe(1);
  });

  it('falls back to /ocr/pdf when embedded PDF text is shorter than OCR_MIN_CHARS', async () => {
    loadConfig({
      BASE_DIR: env.tmpDir,
      DB_PATH: `${env.tmpDir}/test.db`,
      LANCE_DIR: `${env.tmpDir}/lance_db`,
      UPLOAD_DIR: `${env.tmpDir}/uploads`,
      VAULT_DIR: `${env.tmpDir}/wiki_vault`,
      OCR_ENABLED: true,
      OCR_SIDECAR_URL: mockOcr.url,
      OCR_MIN_CHARS: 40,
    });

    // Minimal 1-page blank PDF (valid header/xref so unpdf extracts 0 chars)
    const minimalPdf = Buffer.from(
      '%PDF-1.4\n' +
        '1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
        '2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n' +
        '3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj\n' +
        'xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n' +
        'trailer<</Size 4/Root 1 0 R>>\nstartxref\n167\n%%EOF\n',
      'utf8'
    );

    const form = new FormData();
    form.append('file', new Blob([Uint8Array.from(minimalPdf)], { type: 'application/pdf' }), 'scanned.pdf');
    const uploadResp = await env.app.request('/resources/files', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    expect(uploadResp.status).toBe(201);
    const uploaded = (await uploadResp.json()) as { id: number };

    const job = claimNextJob();
    expect(job).not.toBeNull();
    await executeJob(job!);

    const pdfCalls = mockOcr.requests.filter((r) => r.path === '/ocr/pdf');
    expect(pdfCalls.length).toBe(1);

    const detailResp = await env.app.request(`/resources/${uploaded.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const detail = (await detailResp.json()) as { content?: string; status: string };
    expect(detail.status).toBe('finished');
    expect(detail.content).toContain('光程差实验讲义');
  });
});
