import { Hono } from 'hono';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { submitLink, listUserLinks, deleteUserLink } from '../services/links.js';

export const linksRouter = new Hono();

// POST /links/submit
linksRouter.post('/submit', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const url = String(json.url || '').trim();
  const tags = Array.isArray(json.tags) ? json.tags : [];

  if (!url) {
    return c.json({ detail: 'Missing url parameter' }, 400);
  }

  try {
    const record = await submitLink({
      userId: user.id,
      userEmail: user.email,
      url,
      tags,
    });
    return c.json(record, 202);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// POST /links/bulk
linksRouter.post('/bulk', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const urls: string[] = Array.isArray(json.urls) ? json.urls : [];
  const tags: string[] = Array.isArray(json.tags) ? json.tags : [];

  const results = [];
  for (const rawUrl of urls) {
    try {
      const rec = await submitLink({
        userId: user.id,
        userEmail: user.email,
        url: rawUrl,
        tags,
      });
      results.push(rec);
    } catch {
      // skip invalid urls in bulk
    }
  }

  return c.json({ links_added: results.length }, 202);
});

// GET /links/
linksRouter.get('/', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const links = listUserLinks(user.id);
  return c.json({
    links,
    total: links.length,
  });
});

// DELETE /links/:id
linksRouter.delete('/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const ok = await deleteUserLink(user.id, id);
  if (!ok) {
    return c.json({ detail: 'Link not found' }, 404);
  }
  return c.json({ status: 'deleted' });
});

// POST /links/crawl
linksRouter.post('/crawl', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const url = String(json.url || '').trim();
  if (!url) {
    return c.json({ detail: 'Missing url parameter' }, 400);
  }

  try {
    const record = await submitLink({
      userId: user.id,
      userEmail: user.email,
      url,
    });
    return c.json({ status: 'submitted', url: record.url }, 202);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});
