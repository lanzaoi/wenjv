import { describe, it, expect, beforeEach, afterEach } from 'vitest';
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
});
