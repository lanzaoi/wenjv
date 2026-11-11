import { Hono } from 'hono';
import { getDb } from '../db/index.js';
import { verifyPassword, hashPassword } from '../auth/password.js';
import { createAccessToken, verifyAccessToken } from '../auth/jwt.js';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';

export const authRouter = new Hono();

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
      // ignore
    }
  }

  if (!username || !password) {
    return c.json({ detail: 'LOGIN_BAD_CREDENTIALS' }, 400);
  }

  const db = getDb();
  const user = db
    .prepare('SELECT id, email, hashed_password, is_active FROM users WHERE email = ? OR username = ?')
    .get(username, username) as { id: number; email: string; hashed_password: string; is_active: number } | undefined;

  if (!user || !user.is_active) {
    return c.json({ detail: 'LOGIN_BAD_CREDENTIALS' }, 400);
  }

  const isValid = await verifyPassword(password, user.hashed_password);
  if (!isValid) {
    return c.json({ detail: 'LOGIN_BAD_CREDENTIALS' }, 400);
  }

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

  const hashedPassword = await hashPassword(password);
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
    const user = db.prepare('SELECT id, email, is_active FROM users WHERE id = ?').get(userId) as { id: number; email: string; is_active: number } | undefined;
    if (user && user.is_active) {
      return c.json({ valid: true, user_id: user.id, email: user.email });
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
  const targetId = parseInt(c.req.param('id') || '0', 10);
  if (!currentUser.is_superuser && currentUser.id !== targetId) {
    return c.json({ detail: 'Forbidden' }, 403);
  }

  const db = getDb();
  const json = await c.req.json();
  if (json.password) {
    const hashed = await hashPassword(String(json.password));
    db.prepare('UPDATE users SET hashed_password = ? WHERE id = ?').run(hashed, targetId);
  }
  if (json.email !== undefined) {
    db.prepare('UPDATE users SET email = ? WHERE id = ?').run(json.email, targetId);
  }
  if (json.username !== undefined) {
    db.prepare('UPDATE users SET username = ? WHERE id = ?').run(json.username, targetId);
  }
  if (currentUser.is_superuser) {
    if (json.is_active !== undefined) {
      db.prepare('UPDATE users SET is_active = ? WHERE id = ?').run(json.is_active ? 1 : 0, targetId);
    }
    if (json.is_superuser !== undefined) {
      db.prepare('UPDATE users SET is_superuser = ? WHERE id = ?').run(json.is_superuser ? 1 : 0, targetId);
    }
  }

  const updated = db
    .prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?')
    .get(targetId) as AuthUser | undefined;

  if (!updated) {
    return c.json({ detail: 'User not found' }, 404);
  }

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
