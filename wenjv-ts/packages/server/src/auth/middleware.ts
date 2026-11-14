import crypto from 'node:crypto';
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

const MEDIA_TICKET_TTL_MS = 60 * 1000;
const mediaTickets = new Map<string, { userId: number; expiresAt: number }>();

function pruneExpiredTickets(now = Date.now()): void {
  for (const [ticket, entry] of mediaTickets) {
    if (entry.expiresAt <= now) {
      mediaTickets.delete(ticket);
    }
  }
}

/** Issue a short-lived opaque ticket (60s) for browser image/file tag requests without exposing raw JWTs in URLs. */
export function issueMediaTicket(userId: number): { ticket: string; expiresIn: number } {
  const now = Date.now();
  if (mediaTickets.size > 500) {
    pruneExpiredTickets(now);
  }
  const ticket = crypto.randomBytes(24).toString('base64url');
  mediaTickets.set(ticket, { userId, expiresAt: now + MEDIA_TICKET_TTL_MS });
  return { ticket, expiresIn: Math.floor(MEDIA_TICKET_TTL_MS / 1000) };
}

function fetchActiveUserById(userId: number): AuthUser | null {
  const db = getDb();
  const user = db
    .prepare('SELECT id, email, username, is_active, is_superuser, is_verified FROM users WHERE id = ?')
    .get(userId) as AuthUser | undefined;
  if (!user || !user.is_active) return null;
  return user;
}

export async function authenticateToken(token: string): Promise<AuthUser | null> {
  if (!token) return null;
  try {
    const { userId } = await verifyAccessToken(token);
    return fetchActiveUserById(userId);
  } catch {
    return null;
  }
}

export function authenticateMediaTicket(ticket: string): AuthUser | null {
  if (!ticket) return null;
  const now = Date.now();
  const entry = mediaTickets.get(ticket);
  if (!entry) return null;
  if (entry.expiresAt <= now) {
    mediaTickets.delete(ticket);
    return null;
  }
  return fetchActiveUserById(entry.userId);
}

export async function authMiddleware(c: Context, next: Next): Promise<Response | void> {
  const authHeader = c.req.header('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return c.json({ detail: 'Unauthorized' }, 401);
  }

  const token = authHeader.slice(7).trim();
  const user = await authenticateToken(token);
  if (!user) {
    return c.json({ detail: 'Invalid or expired token' }, 401);
  }

  c.set('user', user);
  await next();
}

/** Resolve user from Authorization Bearer header, short-lived ?ticket=, or legacy ?token= on media endpoints. */
export async function resolveBearerOrQueryUser(c: Context): Promise<AuthUser | null> {
  const authHeader = c.req.header('Authorization');
  if (authHeader && authHeader.startsWith('Bearer ')) {
    return authenticateToken(authHeader.slice(7).trim());
  }

  const ticket = c.req.query('ticket');
  if (ticket) {
    return authenticateMediaTicket(ticket);
  }

  const token = c.req.query('token');
  if (token) {
    return authenticateToken(token);
  }
  return null;
}
