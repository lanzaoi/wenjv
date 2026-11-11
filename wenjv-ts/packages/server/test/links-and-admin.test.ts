import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { isPrivateIp, validateSafeUrl } from '../src/services/ssrf.js';
import { getDb } from '../src/db/index.js';

describe('Links, Admin, and Health Routes (S6 & S9)', () => {
  let env: TestEnv;
  let token: string;
  let adminToken: string;

  beforeEach(async () => {
    env = setupTestEnv();

    // Normal user
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

    // Superuser
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
    expect(isPrivateIp('100.64.0.1')).toBe(true); // CGNAT
    expect(isPrivateIp('198.18.0.1')).toBe(true); // Benchmark
    expect(isPrivateIp('::ffff:127.0.0.1')).toBe(true); // IPv4-mapped IPv6
    expect(isPrivateIp('::ffff:169.254.169.254')).toBe(true);
    expect(isPrivateIp('8.8.8.8')).toBe(false);

    await expect(validateSafeUrl('http://127.0.0.1:8000')).rejects.toThrow();
    await expect(validateSafeUrl('http://localhost:3000')).rejects.toThrow();
    await expect(validateSafeUrl('http://metadata.google.internal')).rejects.toThrow();
  });

  it('submits, lists, crawls, and deletes links with trailing slash compatibility', async () => {
    // 1. Submit link (status 202)
    const submitResp = await env.app.request('/links/submit', {
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
    const linkData = (await submitResp.json()) as { id: number; url: string };
    expect(linkData.id).toBeGreaterThan(0);

    // 2. List links with trailing slash (tests trailing slash URL rewrite)
    const listResp = await env.app.request('/links/?skip=0', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(listResp.status).toBe(200);
    const listData = (await listResp.json()) as { links: Array<{ id: number; url: string }>; total: number };
    expect(listData.total).toBeGreaterThan(0);
    expect(listData.links.some((l) => l.id === linkData.id)).toBe(true);

    // 3. Crawl endpoint
    const crawlResp = await env.app.request('/links/crawl', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ url: 'https://example.com/blog' }),
    });
    expect(crawlResp.status).toBe(202);
    expect(((await crawlResp.json()) as { status: string }).status).toBe('submitted');

    // 4. Bulk links endpoint
    const bulkResp = await env.app.request('/links/bulk', {
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

    // 5. Delete link
    const delResp = await env.app.request(`/links/${linkData.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delResp.status).toBe(200);
    expect(((await delResp.json()) as { status: string }).status).toBe('deleted');
  });

  it('handles root, ping, health, and admin stats endpoints', async () => {
    // 1. Root & Health
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

    // 2. Admin stats with normal user (should fail with 403)
    const failStats = await env.app.request('/admin/stats', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(failStats.status).toBe(403);

    // 3. Admin stats with superuser
    const okStats = await env.app.request('/admin/stats', {
      method: 'GET',
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(okStats.status).toBe(200);
    const statsData = (await okStats.json()) as {
      total_queries: number;
      avg_latency_ms: number;
      v_hit_rate: number;
      fts5_hit_rate: number;
      counts: { users: number };
    };
    expect(statsData.counts.users).toBeGreaterThanOrEqual(2);
    expect(statsData.total_queries).toBeDefined();
    expect(statsData.avg_latency_ms).toBeDefined();
  });
});
