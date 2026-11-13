import fs from 'node:fs';
import path from 'node:path';
import { Hono } from 'hono';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { config } from '../config.js';
import {
  saveUploadFile,
  saveUserNote,
  submitLink,
  listUserResources,
  getResource,
  updateResource,
  syncUserNotes,
  deleteUserResource,
  type ResourceType,
} from '../services/resources.js';

export const resourcesRouter = new Hono();

function parseTagsField(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map(String);
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.map(String);
    } catch {
      return raw
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    }
  }
  return [];
}

// GET /resources?type=file|note|link&tag=...&skip=0&limit=100
resourcesRouter.get('/', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const rawType = c.req.query('type');
  const type: ResourceType | undefined =
    rawType === 'file' || rawType === 'note' || rawType === 'link' ? rawType : undefined;
  const tag = c.req.query('tag') || undefined;
  const skip = parseInt(c.req.query('skip') || '0', 10) || 0;
  const limit = parseInt(c.req.query('limit') || '100', 10) || 100;

  return c.json(listUserResources(user.id, { type, tag, skip, limit }));
});

// POST /resources/files
resourcesRouter.post('/files', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const body = await c.req.parseBody();
  const tags = parseTagsField(body['tags']);

  const fileEntries: File[] = [];
  for (const val of Object.values(body)) {
    if (val instanceof File) {
      fileEntries.push(val);
    }
  }

  if (fileEntries.length === 0) {
    return c.json({ detail: 'No file uploaded' }, 400);
  }

  const results = [];
  for (const f of fileEntries) {
    const ext = path.extname(f.name).toLowerCase().replace('.', '');
    if (!config.ALLOWED_UPLOAD_EXTENSIONS.includes(ext)) {
      return c.json({ detail: `File type .${ext} not allowed` }, 400);
    }

    const buffer = Buffer.from(await f.arrayBuffer());
    if (buffer.length > config.MAX_UPLOAD_BYTES) {
      return c.json({ detail: `File size exceeds limit of ${config.MAX_UPLOAD_BYTES} bytes` }, 400);
    }

    results.push(
      saveUploadFile({
        userId: user.id,
        userEmail: user.email,
        originalFilename: f.name,
        content: buffer,
        contentType: f.type,
        tags,
      })
    );
  }

  return c.json(results.length === 1 ? results[0] : results, 201);
});

// POST /resources/notes
resourcesRouter.post('/notes', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const title = String(json.title || 'Untitled Note');
  const content = String(json.content || '');
  const tags = parseTagsField(json.tags);

  const record = saveUserNote({
    userId: user.id,
    userEmail: user.email,
    title,
    content,
    tags,
  });

  return c.json(record, 201);
});

// POST /resources/notes/sync
resourcesRouter.post('/notes/sync', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const count = syncUserNotes(user.id, user.email);
  return c.json({ count, updated: true });
});

// POST /resources/links
resourcesRouter.post('/links', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const url = String(json.url || '').trim();
  const tags = parseTagsField(json.tags);

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

// POST /resources/links/bulk
resourcesRouter.post('/links/bulk', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const urls: string[] = Array.isArray(json.urls) ? json.urls.map(String) : [];
  const tags = parseTagsField(json.tags);

  const results = [];
  for (const rawUrl of urls) {
    try {
      results.push(
        await submitLink({
          userId: user.id,
          userEmail: user.email,
          url: rawUrl,
          tags,
        })
      );
    } catch {
      // skip invalid URLs in bulk submission
    }
  }

  return c.json({ links_added: results.length, resources: results }, 202);
});

// GET /resources/:id
resourcesRouter.get('/:id', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const idOrName = c.req.param('id') || '';
  const resource = getResource(user.id, idOrName);
  if (!resource) {
    return c.json({ detail: 'Resource not found' }, 404);
  }

  let content = resource.content_text ?? undefined;
  if (resource.type === 'note' && resource.file_path && fs.existsSync(resource.file_path)) {
    content = fs.readFileSync(resource.file_path, 'utf8');
  }

  return c.json({
    ...resource,
    ...(content !== undefined ? { content } : {}),
  });
});

// PATCH /resources/:id
resourcesRouter.patch('/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const idOrName = c.req.param('id') || '';
  const json = await c.req.json();

  const updated = updateResource(user.id, user.email, idOrName, {
    title: typeof json.title === 'string' ? json.title : undefined,
    content: typeof json.content === 'string' ? json.content : undefined,
    tags: Array.isArray(json.tags) ? json.tags.map(String) : undefined,
  });

  if (!updated) {
    return c.json({ detail: 'Resource not found' }, 404);
  }
  return c.json(updated);
});

// PUT /resources/:id/tags
resourcesRouter.put('/:id/tags', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const idOrName = c.req.param('id') || '';
  const json = await c.req.json();
  const tags = parseTagsField(json.tags);

  const updated = updateResource(user.id, user.email, idOrName, { tags });
  if (!updated) {
    return c.json({ detail: 'Resource not found' }, 404);
  }
  return c.json({ tags: updated.tags });
});

// GET /resources/:id/content
resourcesRouter.get('/:id/content', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const idOrName = c.req.param('id') || '';
  const resource = getResource(user.id, idOrName);
  if (!resource) {
    return c.json({ detail: 'Resource not found' }, 404);
  }

  if (!resource.file_path || !fs.existsSync(resource.file_path)) {
    return c.json({ detail: 'Resource content not found on disk' }, 404);
  }

  const buffer = fs.readFileSync(resource.file_path);
  const displayName = resource.original_filename || resource.filename || `${resource.title}.md`;
  return c.body(buffer, 200, {
    'Content-Type': resource.content_type || 'application/octet-stream',
    'Content-Disposition': `inline; filename="${encodeURIComponent(displayName)}"`,
  });
});

// DELETE /resources/:id
resourcesRouter.delete('/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const idOrName = c.req.param('id') || '';
  const ok = await deleteUserResource(user.id, idOrName);
  if (!ok) {
    return c.json({ detail: 'Resource not found' }, 404);
  }
  return c.json({ status: 'deleted' });
});
