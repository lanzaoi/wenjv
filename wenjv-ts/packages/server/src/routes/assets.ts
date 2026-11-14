import fs from 'node:fs';
import { Hono } from 'hono';
import { authMiddleware, issueMediaTicket, resolveBearerOrQueryUser, type AuthUser } from '../auth/middleware.js';
import {
  AssetSecurityError,
  resolveAuthorizedAsset,
  deleteAssetById,
} from '../services/assets.js';

export const assetsRouter = new Hono();

// POST /assets/ticket - issue short-lived (60s) opaque ticket for <img> / media URLs
assetsRouter.post('/ticket', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const issued = issueMediaTicket(user.id);
  return c.json({ ticket: issued.ticket, expires_in: issued.expiresIn });
});

// GET /assets/image?id=... or ?path=...
assetsRouter.get('/image', async (c) => {
  const user = await resolveBearerOrQueryUser(c);
  if (!user) {
    return c.json({ detail: 'Authentication required to view asset' }, 401);
  }

  const id = c.req.query('id');
  const rawPath = c.req.query('path');
  if (!id && !rawPath) {
    return c.json({ detail: 'Asset id or path missing' }, 400);
  }

  try {
    const resolved = resolveAuthorizedAsset(user.id, { id, path: rawPath });
    if (!resolved) {
      return c.json({ detail: 'Image asset not found' }, 404);
    }
    const data = fs.readFileSync(resolved.absPath);
    return new Response(data, {
      headers: {
        'Content-Type': resolved.mimeType,
        'Cache-Control': 'private, max-age=3600',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch (err: unknown) {
    if (err instanceof AssetSecurityError) {
      return c.json({ detail: err.message }, 403);
    }
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// DELETE /assets/:id
assetsRouter.delete('/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const assetId = c.req.param('id') || '';
  const ok = await deleteAssetById(user.id, assetId);
  if (!ok) {
    return c.json({ detail: 'Asset not found' }, 404);
  }
  return c.json({ status: 'deleted' });
});
