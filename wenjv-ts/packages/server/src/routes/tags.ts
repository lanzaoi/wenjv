import { Hono } from 'hono';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import {
  getUserTags,
  updateEntityTags,
  updateUserTag,
  deleteUserTag,
} from '../services/tags.js';

export const tagsRouter = new Hono();

// GET /tags
tagsRouter.get('/', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const limit = Math.min(500, Math.max(1, parseInt(c.req.query('limit') || '100', 10) || 100));
  return c.json({ tags: getUserTags(user.id, limit) });
});

// PUT /tags/:id (O(1) rename / color update)
tagsRouter.put('/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const tagId = parseInt(c.req.param('id') || '0', 10);
  const json = await c.req.json();

  try {
    const updated = updateUserTag(user.id, tagId, {
      name: typeof json.name === 'string' ? json.name : undefined,
      color: typeof json.color === 'string' ? json.color : undefined,
    });
    if (!updated) {
      return c.json({ detail: 'Tag not found' }, 404);
    }
    return c.json(updated);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// DELETE /tags/:id
tagsRouter.delete('/:id', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const tagId = parseInt(c.req.param('id') || '0', 10);
  const ok = deleteUserTag(user.id, tagId);
  if (!ok) {
    return c.json({ detail: 'Tag not found' }, 404);
  }
  return c.json({ status: 'deleted' });
});

// PUT /tags/entities/:entity_type/:entity_id (resource | wiki)
tagsRouter.put('/entities/:entity_type/:entity_id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const rawType = c.req.param('entity_type') || '';
  const entityType = rawType === 'wiki' ? 'wiki' : rawType === 'resource' ? 'resource' : null;
  if (!entityType) {
    return c.json({ detail: 'Invalid entity_type (expected resource or wiki)' }, 400);
  }

  const entityId = parseInt(c.req.param('entity_id') || '0', 10);
  const json = await c.req.json();
  const tags: string[] = Array.isArray(json.tags) ? json.tags.map(String) : [];

  const updated = updateEntityTags(user.id, entityType, entityId, tags);
  if (updated === null) {
    return c.json({ detail: 'Entity not found' }, 404);
  }
  return c.json({ tags: updated });
});
