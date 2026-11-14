import fs from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { registerAsset } from '../src/services/assets.js';
import { computeRevisionDiff } from '../src/routes/wiki.js';
import { config } from '../src/config.js';
import { getDb } from '../src/db/index.js';

describe('Security & Robustness Hardening (M1, M2, M3, M6, M8, M9, L14-L16)', () => {
  let env: TestEnv;
  let token = '';
  let otherToken = '';
  let userId = 0;

  beforeEach(async () => {
    env = setupTestEnv();

    const r1 = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'sec1@example.com', password: 'Password123!' }),
    });
    userId = ((await r1.json()) as { id: number }).id;

    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'sec2@example.com', password: 'Password123!' }),
    });

    const l1 = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'sec1@example.com', password: 'Password123!' }),
    });
    token = ((await l1.json()) as { access_token: string }).access_token;

    const l2 = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'sec2@example.com', password: 'Password123!' }),
    });
    otherToken = ((await l2.json()) as { access_token: string }).access_token;
  });

  afterEach(() => {
    env.cleanup();
  });

  it('downgrades HTML uploads in /resources/:id/content while keeping PNG/PDF inline (M1)', async () => {
    const htmlFd = new FormData();
    htmlFd.append('file', new Blob(['<script>alert(1)</script>'], { type: 'text/html' }), 'xss.html');
    const htmlUp = await env.app.request('/resources/files', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: htmlFd,
    });
    expect(htmlUp.status).toBe(201);
    const htmlRes = (await htmlUp.json()) as { id: number };

    const htmlContentResp = await env.app.request(`/resources/${htmlRes.id}/content`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(htmlContentResp.status).toBe(200);
    expect(htmlContentResp.headers.get('content-type')).toContain('text/plain');
    expect(htmlContentResp.headers.get('content-disposition')).toContain('attachment;');
    expect(htmlContentResp.headers.get('x-content-type-options')).toBe('nosniff');

    const pngBytes = await sharp({
      create: { width: 8, height: 8, channels: 3, background: { r: 10, g: 20, b: 30 } },
    })
      .png()
      .toBuffer();
    const pngFd = new FormData();
    pngFd.append('file', new Blob([pngBytes], { type: 'image/png' }), 'safe.png');
    const pngUp = await env.app.request('/resources/files', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: pngFd,
    });
    const pngRes = (await pngUp.json()) as { id: number };

    const pngContentResp = await env.app.request(`/resources/${pngRes.id}/content`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(pngContentResp.status).toBe(200);
    expect(pngContentResp.headers.get('content-type')).toBe('image/png');
    expect(pngContentResp.headers.get('content-disposition')).toContain('inline;');

    // L14: Reject PATCH content on non-note file resources
    const patchFileContent = await env.app.request(`/resources/${pngRes.id}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: 'overwrite attempt' }),
    });
    expect(patchFileContent.status).toBe(400);
  });

  it('refuses unregistered upload files via /assets/image?path= and supports short-lived media tickets (M2, M6)', async () => {
    const unregPath = path.join(config.resolvedUploadDir, 'secret-unregistered.png');
    fs.mkdirSync(path.dirname(unregPath), { recursive: true });
    const pngBytes = await sharp({
      create: { width: 8, height: 8, channels: 3, background: { r: 200, g: 50, b: 50 } },
    })
      .png()
      .toBuffer();
    fs.writeFileSync(unregPath, pngBytes);

    const probeResp = await env.app.request('/assets/image?path=secret-unregistered.png', {
      headers: { Authorization: `Bearer ${otherToken}` },
    });
    expect(probeResp.status).toBe(404);

    // Register owned asset and verify short-lived ticket works without putting JWT in URL
    const ownedPath = path.join(config.resolvedUploadDir, 'owned.png');
    fs.writeFileSync(ownedPath, pngBytes);
    await registerAsset({
      id: 'sec_asset_1',
      userId,
      ownerType: 'wiki',
      ownerId: 1,
      filename: 'owned.png',
      relPath: 'owned.png',
      absPath: ownedPath,
      mimeType: 'image/png',
      size: pngBytes.byteLength,
    });

    const ticketResp = await env.app.request('/assets/ticket', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(ticketResp.status).toBe(200);
    const { ticket } = (await ticketResp.json()) as { ticket: string; expires_in: number };
    expect(ticket).toBeTruthy();

    const byTicket = await env.app.request(`/assets/image?path=owned.png&ticket=${encodeURIComponent(ticket)}`);
    expect(byTicket.status).toBe(200);

    const otherProbe = await env.app.request('/assets/image?path=owned.png', {
      headers: { Authorization: `Bearer ${otherToken}` },
    });
    expect(otherProbe.status).toBe(403);
  });

  it('enforces MAX_UPLOAD_BYTES (413) on /search/by-image and /chat/by-image (M3)', async () => {
    const oversized = Buffer.alloc(config.MAX_UPLOAD_BYTES + 128, 1);

    const searchFd = new FormData();
    searchFd.append('file', new Blob([oversized], { type: 'image/png' }), 'huge.png');
    const searchResp = await env.app.request('/search/by-image', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: searchFd,
    });
    expect(searchResp.status).toBe(413);

    const chatFd = new FormData();
    chatFd.append('file', new Blob([oversized], { type: 'image/png' }), 'huge.png');
    const chatResp = await env.app.request('/chat/by-image', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: chatFd,
    });
    expect(chatResp.status).toBe(413);
  });

  it('validates parent_id on wiki creation (M8), escapes LIKE in /wiki/search (L16), and bounds large diff (M9)', async () => {
    const missingParent = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Orphan Child', parent_id: 999999 }),
    });
    expect(missingParent.status).toBe(404);

    const invalidParent = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Bad Parent', parent_id: 'abc' }),
    });
    expect(invalidParent.status).toBe(400);

    // L16: '%' in query should not match unrelated page titles
    await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Normal Page Title', content: 'plain body' }),
    });
    const wildcardSearch = await env.app.request('/wiki/search?q=%25', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(wildcardSearch.status).toBe(200);
    const hits = (await wildcardSearch.json()) as Array<{ title: string }>;
    expect(hits).toHaveLength(0);

    // M9: Large rewrite safely falls back without O(m*n) OOM
    const bigA = Array.from({ length: 1600 }, (_, i) => `old-line-${i}`).join('\n');
    const bigB = Array.from({ length: 1600 }, (_, i) => `new-line-${i}`).join('\n');
    const diffRes = computeRevisionDiff(bigA, bigB);
    expect(diffRes.truncated).toBe(true);
    expect(diffRes.lines.length).toBeLessThanOrEqual(1000);

    // L6: schema user_version pragma recorded
    const dbVersion = Number(getDb().pragma('user_version', { simple: true }));
    expect(dbVersion).toBeGreaterThanOrEqual(2);
  });
});
