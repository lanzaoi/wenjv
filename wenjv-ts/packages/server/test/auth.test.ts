import fs from 'node:fs';
import path from 'node:path';
import * as jose from 'jose';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { loadConfig } from '../src/config.js';
import { verifyAccessToken } from '../src/auth/jwt.js';
import { clearAuthRateLimits } from '../src/routes/auth.js';
import { setupTestEnv, type TestEnv } from './helper.js';

describe('Auth & Users Service & Routes (S1)', () => {
  let env: TestEnv;

  beforeEach(() => {
    env = setupTestEnv();
  });

  afterEach(() => {
    env.cleanup();
  });

  it('registers a user and logs in with JWT', async () => {
    // 1. Register
    const regResp = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'alice@example.com',
        password: 'Password123!',
        username: 'alice',
      }),
    });
    expect(regResp.status).toBe(201);
    const regData = (await regResp.json()) as { id: number; email: string };
    expect(regData.email).toBe('alice@example.com');
    expect(regData.id).toBeGreaterThan(0);

    // Duplicate registration should fail
    const dupResp = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'alice@example.com',
        password: 'Password123!',
      }),
    });
    expect(dupResp.status).toBe(400);

    // 2. Login (application/x-www-form-urlencoded)
    const loginResp = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'username=alice%40example.com&password=Password123%21',
    });
    expect(loginResp.status).toBe(200);
    const loginData = (await loginResp.json()) as { access_token: string; token_type: string };
    expect(loginData.token_type).toBe('bearer');
    expect(loginData.access_token).toBeDefined();

    // 3. /auth/users/me with Bearer token
    const meResp = await env.app.request('/auth/users/me', {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${loginData.access_token}`,
      },
    });
    expect(meResp.status).toBe(200);
    const meData = (await meResp.json()) as { id: number; email: string; username: string };
    expect(meData.id).toBe(regData.id);
    expect(meData.email).toBe('alice@example.com');
    expect(meData.username).toBe('alice');

    // 4. Validate token endpoint
    const valResp = await env.app.request('/auth/validate-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: loginData.access_token }),
    });
    expect(valResp.status).toBe(200);
    const valData = (await valResp.json()) as { valid: boolean; user_id: number };
    expect(valData.valid).toBe(true);
    expect(valData.user_id).toBe(regData.id);

    // 5. Bad password login
    const badLogin = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'alice@example.com',
        password: 'wrong-password',
      }),
    });
    expect(badLogin.status).toBe(400);

    // 6. Lookup user by username
    const byUsername = await env.app.request('/auth/users/alice', {
      method: 'GET',
      headers: { Authorization: `Bearer ${loginData.access_token}` },
    });
    expect(byUsername.status).toBe(200);
    expect(((await byUsername.json()) as { email: string }).email).toBe('alice@example.com');

    // 7. Lookup user by ID
    const byId = await env.app.request(`/auth/users/${regData.id}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${loginData.access_token}` },
    });
    expect(byId.status).toBe(200);
    expect(((await byId.json()) as { username: string }).username).toBe('alice');

    // 8. Patch user by ID
    const patchUser = await env.app.request(`/auth/users/${regData.id}`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${loginData.access_token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username: 'alice_updated' }),
    });
    expect(patchUser.status).toBe(200);
    expect(((await patchUser.json()) as { username: string }).username).toBe('alice_updated');
  });

  it('honors Python SECRET_KEY from backend.env as JWT_SECRET fallback', () => {
    const prevSecret = process.env['SECRET_KEY'];
    const prevJwt = process.env['JWT_SECRET'];
    delete process.env['SECRET_KEY'];
    delete process.env['JWT_SECRET'];
    try {
      fs.writeFileSync(
        path.join(env.tmpDir, 'backend.env'),
        'SECRET_KEY=python-shared-secret-key\nCHAT_MODEL=spark-x2.6\n',
        'utf8'
      );
      const cfg = loadConfig({ BASE_DIR: env.tmpDir });
      expect(cfg.JWT_SECRET).toBe('python-shared-secret-key');
    } finally {
      if (prevSecret !== undefined) process.env['SECRET_KEY'] = prevSecret;
      if (prevJwt !== undefined) process.env['JWT_SECRET'] = prevJwt;
    }
  });

  it('handles duplicate email/username and malformed JSON with 400 in PATCH /auth/users/:id (M4)', async () => {
    const r1 = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'u1@example.com', password: 'Password123!', username: 'u1' }),
    });
    const r2 = await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'u2@example.com', password: 'Password123!', username: 'u2' }),
    });
    const u1 = (await r1.json()) as { id: number };
    const u2 = (await r2.json()) as { id: number };

    const login2 = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'u2@example.com', password: 'Password123!' }),
    });
    const { access_token } = (await login2.json()) as { access_token: string };

    // Duplicate email -> clean 400 instead of SQLite 500
    const dupEmailResp = await env.app.request(`/auth/users/${u2.id}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'u1@example.com' }),
    });
    expect(dupEmailResp.status).toBe(400);
    expect(((await dupEmailResp.json()) as { detail: string }).detail).toBe('EMAIL_ALREADY_EXISTS');

    // Duplicate username -> clean 400
    const dupUserResp = await env.app.request(`/auth/users/${u2.id}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'u1' }),
    });
    expect(dupUserResp.status).toBe(400);
    expect(((await dupUserResp.json()) as { detail: string }).detail).toBe('USERNAME_ALREADY_EXISTS');

    // Malformed JSON -> clean 400
    const badJsonResp = await env.app.request(`/auth/users/${u2.id}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' },
      body: '{invalid-json',
    });
    expect(badJsonResp.status).toBe(400);

    // Nonexistent user -> 404 (not u1 due to unrelated sub)
    expect(u1.id).not.toBe(u2.id);
  });

  it('rate-limits repeated failed logins (M10) and rejects non-numeric JWT sub (L10)', async () => {
    clearAuthRateLimits();
    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'lock@example.com', password: 'Password123!' }),
    });

    for (let i = 0; i < 5; i++) {
      const bad = await env.app.request('/auth/jwt/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-forwarded-for': '203.0.113.9' },
        body: JSON.stringify({ username: 'lock@example.com', password: 'wrong' }),
      });
      expect(bad.status).toBe(400);
    }

    const throttled = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-forwarded-for': '203.0.113.9' },
      body: JSON.stringify({ username: 'lock@example.com', password: 'Password123!' }),
    });
    expect(throttled.status).toBe(429);
    expect(throttled.headers.get('retry-after')).toBeTruthy();

    clearAuthRateLimits();

    // L10: non-digit sub like "12abc" must fail strict JWT subject check
    const cfg = loadConfig({ BASE_DIR: env.tmpDir });
    const badSubJwt = await new jose.SignJWT({ sub: '12abc' })
      .setProtectedHeader({ alg: 'HS256' })
      .setAudience(cfg.JWT_AUDIENCE)
      .setIssuedAt()
      .setExpirationTime('1h')
      .sign(new TextEncoder().encode(cfg.JWT_SECRET));
    await expect(verifyAccessToken(badSubJwt)).rejects.toThrow();
  });
});
