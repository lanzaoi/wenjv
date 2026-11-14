import { Hono, type Context } from 'hono';
import { getDb } from '../db/index.js';
import { verifyPassword, hashPassword } from '../auth/password.js';
import { createAccessToken, verifyAccessToken } from '../auth/jwt.js';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';

export const authRouter = new Hono();

const LOGIN_WINDOW_MS = 60_000;
const MAX_LOGIN_FAILURES = 5;
const REGISTER_WINDOW_MS = 600_000;
const MAX_REGISTERS_PER_WINDOW = 30;

const loginFailures = new Map<string, number[]>();
const registerAttempts = new Map<string, number[]>();

function getClientIp(c: Context): string {
  const xff = c.req.header('x-forwarded-for');
  if (xff) {
    return xff.split(',')[0]?.trim() || 'unknown';
  }
  return c.req.header('x-real-ip')?.trim() || 'local';
}

function pruneTimestamps(map: Map<string, number[]>, key: string, windowMs: number, now = Date.now()): number[] {
  const arr = map.get(key);
  if (!arr || arr.length === 0) return [];
  const valid = arr.filter((ts) => now - ts < windowMs);
  if (valid.length === 0) {
    map.delete(key);
  } else {
    map.set(key, valid);
  }
  return valid;
}

function recordAttempt(map: Map<string, number[]>, key: string, windowMs: number): void {
  const now = Date.now();
  if (map.size > 2000) {
    for (const k of map.keys()) {
      pruneTimestamps(map, k, windowMs, now);
    }
  }
  const valid = pruneTimestamps(map, key, windowMs, now);
  valid.push(now);
  map.set(key, valid);
}

/** Reset in-memory auth rate limit buckets (for unit test isolation). */
export function clearAuthRateLimits(): void {
  loginFailures.clear();
  registerAttempts.clear();
}

// POST /auth/jwt/login
authRouter.post('/jwt/login', async (c) => {
  let username = '';
  let password = '';

  const contentType = c.req.header('Content-Type') || '';
  if (contentType.includes('application/x-www-form-urlencoded')) {
    const body = await c.req.parseBody();
    username = String(body['username'] || '');
    password = String(body['password'] || '');
  } else {
    try {
      const json = await c.req.json();
      username = String(json.username || json.email || '');
      password = String(json.password || '');
    } catch {
      // ignore malformed JSON on login; returns 400 below
    }
  }

  if (!username || !password) {
    return c.json({ detail: 'LOGIN_BAD_CREDENTIALS' }, 400);
  }

  const clientIp = getClientIp(c);
  const bucketKey = `${clientIp}::${username.trim().toLowerCase()}`;
  if (pruneTimestamps(loginFailures, bucketKey, LOGIN_WINDOW_MS).length >= MAX_LOGIN_FAILURES) {
    c.header('Retry-After', String(Math.ceil(LOGIN_WINDOW_MS / 1000)));
    return c.json({ detail: 'TOO_MANY_LOGIN_ATTEMPTS' }, 429);
  }

  const db = getDb();
  const user = db
    .prepare('SELECT id, email, hashed_password, is_active FROM users WHERE email = ? OR username = ?')
    .get(username, username) as { id: number; email: string; hashed_password: string; is_active: number } | undefined;

  if (!user || !user.is_active) {
    recordAttempt(loginFailures, bucketKey, LOGIN_WINDOW_MS);
    return c.json({ detail: 'LOGIN_BAD_CREDENTIALS' }, 400);
  }

  const isValid = await verifyPassword(password, user.hashed_password);
  if (!isValid) {
    recordAttempt(loginFailures, bucketKey, LOGIN_WINDOW_MS);
    return c.json({ detail: 'LOGIN_BAD_CREDENTIALS' }, 400);
  }

  loginFailures.delete(bucketKey);
  const token = await createAccessToken(user.id);
  return c.json({
    access_token: token,
    token_type: 'bearer',
  });
});

// POST /auth/jwt/logout
authRouter.post('/jwt/logout', (c) => {
  return c.body(null, 204);
});

// POST /auth/register
authRouter.post('/register', async (c) => {
  const clientIp = getClientIp(c);
  if (pruneTimestamps(registerAttempts, clientIp, REGISTER_WINDOW_MS).length >= MAX_REGISTERS_PER_WINDOW) {
    c.header('Retry-After', String(Math.ceil(REGISTER_WINDOW_MS / 1000)));
    return c.json({ detail: 'TOO_MANY_REGISTER_ATTEMPTS' }, 429);
  }

  let email = '';
  let password = '';
  let username: string | null = null;

  try {
    const json = await c.req.json();
    email = String(json.email || '').trim().toLowerCase();
    password = String(json.password || '');
    username = json.username ? String(json.username).trim() : null;
  } catch {
    return c.json({ detail: 'Invalid JSON' }, 400);
  }

  if (!email || !password) {
    return c.json({ detail: 'Missing email or password' }, 400);
  }

  const db = getDb();
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existing) {
    return c.json({ detail: 'REGISTER_USER_ALREADY_EXISTS' }, 400);
  }

  recordAttempt(registerAttempts, clientIp, REGISTER_WINDOW_MS);

  const hashedPassword = await hashPassword(password);
  try {
    const res = db
      .prepare(`
        INSERT INTO users(email, username, hashed_password, is_active, is_superuser, is_verified)
        VALUES (?, ?, ?, 1, 0, 0)
      `)
      .run(email, username, hashedPassword);

    const newId = Number(res.lastInsertRowid);
    return c.json(
      {
        id: newId,
        email,
        username,
        is_active: true,
        is_superuser: false,
        is_verified: false,
      },
      201
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/UNIQUE constraint/i.test(msg)) {
      return c.json({ detail: 'REGISTER_USER_ALREADY_EXISTS' }, 400);
    }
    throw err;
  }
});

// GET /auth/users/me
authRouter.get('/users/me', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  return c.json({
    id: user.id,
    email: user.email,
    username: user.username,
    is_active: Boolean(user.is_active),
    is_superuser: Boolean(user.is_superuser),
    is_verified: Boolean(user.is_verified),
  });
});

// PATCH /auth/users/me
authRouter.patch('/users/me', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const db = getDb();
  try {
    const json = await c.req.json();
    if (json.password) {
      const hashed = await hashPassword(String(json.password));
      db.prepare('UPDATE users SET hashed_password = ? WHERE id = ?').run(hashed, user.id);
    }
    if (json.username !== undefined) {
      db.prepare('UPDATE users SET username = ? WHERE id = ?').run(json.username, user.id);
    }
  } catch {
    // ignore
  }

  const updated = db.prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?').get(user.id) as AuthUser;
  return c.json({
    id: updated.id,
    email: updated.email,
    username: updated.username,
    is_active: Boolean(updated.is_active),
    is_superuser: Boolean(updated.is_superuser),
    is_verified: Boolean(updated.is_verified),
  });
});

// POST /auth/validate-token
authRouter.post('/validate-token', async (c) => {
  try {
    const json = await c.req.json();
    const token = String(json.token || '');
    const { userId } = await verifyAccessToken(token);
    const db = getDb();
    const user = db
      .prepare('SELECT id, email, is_active, is_superuser FROM users WHERE id = ?')
      .get(userId) as { id: number; email: string; is_active: number; is_superuser: number } | undefined;
    if (user && user.is_active) {
      return c.json({
        valid: true,
        user_id: user.id,
        email: user.email,
        is_superuser: Boolean(user.is_superuser),
      });
    }
  } catch {
    // ignore
  }
  return c.json({ valid: false }, 401);
});

// GET /auth/users/:identifier
authRouter.get('/users/:identifier', authMiddleware, (c) => {
  const param = c.req.param('identifier') || '';
  const db = getDb();
  let user: AuthUser | undefined;

  if (/^\d+$/.test(param)) {
    const id = parseInt(param, 10);
    user = db
      .prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?')
      .get(id) as AuthUser | undefined;
  } else {
    user = db
      .prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE username = ? OR email = ?')
      .get(param, param) as AuthUser | undefined;
  }

  if (!user) {
    return c.json({ detail: 'User not found' }, 404);
  }
  return c.json({
    id: user.id,
    email: user.email,
    username: user.username,
    is_active: Boolean(user.is_active),
    is_superuser: Boolean(user.is_superuser),
    is_verified: Boolean(user.is_verified),
  });
});

// PATCH /auth/users/:id
authRouter.patch('/users/:id', authMiddleware, async (c) => {
  const currentUser = c.get('user') as AuthUser;
  const targetId = Number.parseInt(c.req.param('id') || '0', 10);
  if (!Number.isSafeInteger(targetId) || targetId <= 0) {
    return c.json({ detail: 'User not found' }, 404);
  }
  if (!currentUser.is_superuser && currentUser.id !== targetId) {
    return c.json({ detail: 'Forbidden' }, 403);
  }

  let json: Record<string, unknown>;
  try {
    const parsed = await c.req.json();
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return c.json({ detail: 'Invalid request body' }, 400);
    }
    json = parsed as Record<string, unknown>;
  } catch {
    return c.json({ detail: 'Invalid request body' }, 400);
  }

  const db = getDb();
  const targetExists = db.prepare('SELECT id FROM users WHERE id = ?').get(targetId) as { id: number } | undefined;
  if (!targetExists) {
    return c.json({ detail: 'User not found' }, 404);
  }

  try {
    if (json['email'] !== undefined) {
      const email = String(json['email'] || '').trim().toLowerCase();
      if (!email) {
        return c.json({ detail: 'Invalid email' }, 400);
      }
      const dupEmail = db.prepare('SELECT id FROM users WHERE email = ? AND id != ?').get(email, targetId);
      if (dupEmail) {
        return c.json({ detail: 'EMAIL_ALREADY_EXISTS' }, 400);
      }
      db.prepare('UPDATE users SET email = ? WHERE id = ?').run(email, targetId);
    }

    if (json['username'] !== undefined) {
      const username = json['username'] === null ? null : String(json['username']).trim() || null;
      if (username) {
        const dupUser = db.prepare('SELECT id FROM users WHERE username = ? AND id != ?').get(username, targetId);
        if (dupUser) {
          return c.json({ detail: 'USERNAME_ALREADY_EXISTS' }, 400);
        }
      }
      db.prepare('UPDATE users SET username = ? WHERE id = ?').run(username, targetId);
    }

    if (json['password']) {
      const hashed = await hashPassword(String(json['password']));
      db.prepare('UPDATE users SET hashed_password = ? WHERE id = ?').run(hashed, targetId);
    }

    if (currentUser.is_superuser) {
      if (json['is_active'] !== undefined) {
        db.prepare('UPDATE users SET is_active = ? WHERE id = ?').run(json['is_active'] ? 1 : 0, targetId);
      }
      if (json['is_superuser'] !== undefined) {
        db.prepare('UPDATE users SET is_superuser = ? WHERE id = ?').run(json['is_superuser'] ? 1 : 0, targetId);
      }
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/UNIQUE constraint/i.test(msg)) {
      return c.json({ detail: 'EMAIL_OR_USERNAME_ALREADY_EXISTS' }, 400);
    }
    return c.json({ detail: 'Failed to update user' }, 400);
  }

  const updated = db
    .prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?')
    .get(targetId) as AuthUser;

  return c.json({
    id: updated.id,
    email: updated.email,
    username: updated.username,
    is_active: Boolean(updated.is_active),
    is_superuser: Boolean(updated.is_superuser),
    is_verified: Boolean(updated.is_verified),
  });
});

// DELETE /auth/users/:id
authRouter.delete('/users/:id', authMiddleware, (c) => {
  const currentUser = c.get('user') as AuthUser;
  const targetId = parseInt(c.req.param('id') || '0', 10);
  if (!currentUser.is_superuser && currentUser.id !== targetId) {
    return c.json({ detail: 'Forbidden' }, 403);
  }

  const db = getDb();
  const res = db.prepare('DELETE FROM users WHERE id = ?').run(targetId);
  if (res.changes === 0) {
    return c.json({ detail: 'User not found' }, 404);
  }
  return c.body(null, 204);
});
