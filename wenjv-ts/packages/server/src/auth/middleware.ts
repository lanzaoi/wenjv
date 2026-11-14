import type { Context, Next } from 'hono';
import { verifyAccessToken } from './jwt.js';
import { getDb } from '../db/index.js';

export interface AuthUser {
  id: number;
  email: string;
  username: string | null;
  is_active: number;
  is_superuser: number;
  is_verified: number;
}

declare module 'hono' {
  interface ContextVariableMap {
    user: AuthUser;
  }
}

export async function authMiddleware(c: Context, next: Next): Promise<Response | void> {
  const authHeader = c.req.header('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return c.json({ detail: 'Unauthorized' }, 401);
  }

  const token = authHeader.slice(7).trim();
  try {
    const { userId } = await verifyAccessToken(token);
    const db = getDb();
    const user = db.prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?').get(userId) as AuthUser | undefined;

    if (!user || !user.is_active) {
      return c.json({ detail: 'User inactive or not found' }, 401);
    }

    c.set('user', user);
    await next();
  } catch {
    return c.json({ detail: 'Invalid or expired token' }, 401);
  }
}

export async function resolveBearerOrQueryUser(c: Context): Promise<AuthUser | null> {
  const authHeader = c.req.header('Authorization');
  let token = c.req.query('token');
  if (authHeader && authHeader.startsWith('Bearer ')) {
    token = authHeader.slice(7).trim();
  }
  if (!token) return null;
  try {
    const { userId } = await verifyAccessToken(token);
    const db = getDb();
    const user = db
      .prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?')
      .get(userId) as AuthUser | undefined;
    if (!user || !user.is_active) return null;
    return user;
  } catch {
    return null;
  }
}

export async function optionalAuthMiddleware(c: Context, next: Next): Promise<Response | void> {
  const authHeader = c.req.header('Authorization');
  if (authHeader && authHeader.startsWith('Bearer ')) {
    const token = authHeader.slice(7).trim();
    try {
      const { userId } = await verifyAccessToken(token);
      const db = getDb();
      const user = db.prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?').get(userId) as AuthUser | undefined;
      if (user && user.is_active) {
        c.set('user', user);
      }
    } catch {
      // optional, continue
    }
  }
  await next();
}
