import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { isPrivateIp, validateSafeUrl } from '../src/services/ssrf.js';
import { getDb } from '../src/db/index.js';

describe('Unified Links, SSRF, Admin & Health Routes (Schema v2)', () => {
  let env: TestEnv;
  let token: string;
  let adminToken: string;

  beforeEach(async () => {
    env = setupTestEnv();

    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'frank@example.com',
        password: 'Password123!',
      }),
    });
    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'frank@example.com',
        password: 'Password123!',
      }),
    });
    token = ((await login.json()) as { access_token: string }).access_token;

    const db = getDb();
    db.prepare(`
      INSERT OR REPLACE INTO users(email, username, hashed_password, is_active, is_superuser, is_verified)
      VALUES ('admin@example.com', 'admin', 'dummy', 1, 1, 1)
    `).run();
    const adminUser = db.prepare('SELECT id FROM users WHERE email = ?').get('admin@example.com') as { id: number };

    const { createAccessToken } = await import('../src/auth/jwt.js');
    adminToken = await createAccessToken(adminUser.id);
  });

  afterEach(() => {
    env.cleanup();
  });

  it('verifies SSRF blocking on private and loopback addresses', async () => {
    expect(isPrivateIp('127.0.0.1')).toBe(true);
    expect(isPrivateIp('10.0.0.1')).toBe(true);
    expect(isPrivateIp('192.168.1.100')).toBe(true);
    expect(isPrivateIp('172.16.5.1')).toBe(true);
    expect(isPrivateIp('169.254.169.254')).toBe(true);
    expect(isPrivateIp('100.64.0.1')).toBe(true);
    expect(isPrivateIp('198.18.0.1')).toBe(true);
    expect(isPrivateIp('::ffff:127.0.0.1')).toBe(true);
    expect(isPrivateIp('::ffff:169.254.169.254')).toBe(true);
    expect(isPrivateIp('8.8.8.8')).toBe(false);

    await expect(validateSafeUrl('http://127.0.0.1:8000')).rejects.toThrow();
    await expect(validateSafeUrl('http://localhost:3000')).rejects.toThrow();
    await expect(validateSafeUrl('http://metadata.google.internal')).rejects.toThrow();
  });

  it('submits, bulk-submits, lists, and deletes link resources via /resources', async () => {
    const submitResp = await env.app.request('/resources/links', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        url: 'https://example.com/article',
        tags: ['web'],
      }),
    });
    expect(submitResp.status).toBe(202);
    const linkData = (await submitResp.json()) as { id: number; type: string; source_url: string; tags: string[] };
    expect(linkData.id).toBeGreaterThan(0);
    expect(linkData.type).toBe('link');
    expect(linkData.tags).toEqual(['web']);

    const listResp = await env.app.request('/resources/?type=link&skip=0', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(listResp.status).toBe(200);
    const listData = (await listResp.json()) as { resources: Array<{ id: number; source_url: string }>; total: number };
    expect(listData.total).toBeGreaterThan(0);
    expect(listData.resources.some((l) => l.id === linkData.id)).toBe(true);

    const bulkResp = await env.app.request('/resources/links/bulk', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        urls: ['https://example.com/page1', 'https://example.com/page2'],
      }),
    });
    expect(bulkResp.status).toBe(202);
    const bulkJson = (await bulkResp.json()) as { links_added: number };
    expect(bulkJson.links_added).toBe(2);

    const delResp = await env.app.request(`/resources/${linkData.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delResp.status).toBe(200);
    expect((await delResp.json()) as { status: string }).toEqual({ status: 'deleted' });
  });

  it('handles root, ping, health, and admin stats endpoints with v2 counts', async () => {
    const ping = await env.app.request('/ping');
    expect(ping.status).toBe(200);
    expect(await ping.json()).toEqual({ message: 'pong' });

    const health = await env.app.request('/health');
    expect(health.status).toBe(200);
    const healthJson = (await health.json()) as { status: string; db: string; vector_store: string };
    expect(healthJson.status).toBe('ok');
    expect(healthJson.db).toBe('connected');
    expect(healthJson.vector_store).toBe('ready');

    const root = await env.app.request('/');
    expect(root.status).toBe(200);
    expect(await root.json()).toEqual({ message: 'wenjv API 运行中' });

    const failStats = await env.app.request('/admin/stats', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(failStats.status).toBe(403);

    const okStats = await env.app.request('/admin/stats', {
      method: 'GET',
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(okStats.status).toBe(200);
    const statsData = (await okStats.json()) as {
      counts: { users: number; resources: number; chunks: number; assets: number; tags: number };
    };
    expect(statsData.counts.users).toBeGreaterThanOrEqual(2);
    expect(statsData.counts.resources).toBeDefined();
    expect(statsData.counts.chunks).toBeDefined();
    expect(statsData.counts.assets).toBeDefined();
    expect(statsData.counts.tags).toBeDefined();
  });
});
