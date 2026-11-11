import fs from 'node:fs';
import path from 'node:path';
import { Hono, type Context } from 'hono';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { verifyAccessToken } from '../auth/jwt.js';
import { searchDocuments } from '../services/search.js';
import { getUserTags, updateResourceTags } from '../services/tags.js';
import { getVisualStore } from '../vector/visual-store.js';
import { SigLIP2Engine } from '../ai/siglip2.js';
import { config } from '../config.js';

export const documentsRouter = new Hono();

// POST /search
documentsRouter.post('/search', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();

  const prompt = String(json.prompt || json.query || json.question || '');
  const windowSize = json.window_size ? parseInt(json.window_size, 10) : 5;
  const sourceType = json.source_type ? String(json.source_type) : undefined;
  const includeSources = Array.isArray(json.include_sources) ? json.include_sources : undefined;
  const excludeSources = Array.isArray(json.exclude_sources) ? json.exclude_sources : undefined;
  const tags = Array.isArray(json.tags) ? json.tags : undefined;

  const hits = await searchDocuments({
    prompt,
    userId: user.id,
    userEmail: user.email,
    windowSize,
    sourceType,
    includeSources,
    excludeSources,
    tags,
  });

  return c.json({
    documents: hits,
    count: hits.length,
  });
});

// GET /tags
documentsRouter.get('/tags', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const tags = getUserTags(user.id);
  return c.json({ tags });
});

// PUT /:source_type/:resource_id/tags
documentsRouter.put('/:source_type/:resource_id/tags', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const sourceType = c.req.param('source_type') || '';
  const resourceId = c.req.param('resource_id') || '';
  const json = await c.req.json();
  const tags: string[] = Array.isArray(json.tags) ? json.tags : [];

  const ok = updateResourceTags(user.id, sourceType, resourceId, tags);
  if (!ok) {
    return c.json({ detail: 'Resource not found' }, 404);
  }
  return c.json({ tags });
});

// POST /tags/backfill
documentsRouter.post('/tags/backfill', authMiddleware, (c) => {
  return c.json({ enqueued_count: 0 });
});

// GET /assets/image
documentsRouter.get('/assets/image', async (c) => {
  let userId: number | null = null;
  const authHeader = c.req.header('Authorization');
  let token = c.req.query('token');

  if (authHeader && authHeader.startsWith('Bearer ')) {
    token = authHeader.slice(7).trim();
  }

  if (token) {
    try {
      const payload = await verifyAccessToken(token);
      userId = payload.userId;
    } catch {
      userId = null;
    }
  }

  if (!userId) {
    return c.json({ detail: 'Authentication required to view asset' }, 401);
  }

  const rawPath = c.req.query('path');
  const uploadRoot = path.resolve(config.resolvedUploadDir);

  if (rawPath) {
    const targetPath = path.isAbsolute(rawPath)
      ? path.resolve(rawPath)
      : path.resolve(uploadRoot, rawPath);

    if (!targetPath.startsWith(uploadRoot + path.sep) && targetPath !== uploadRoot) {
      return c.json({ detail: 'Access denied: asset path outside upload directory' }, 403);
    }

    // Tenant safety check
    const rel = path.relative(uploadRoot, targetPath);
    const parts = rel.split(path.sep);
    if (parts.length >= 3 && parts[0] === 'mm_assets' && parts[1] === 'sessions') {
      const ownerId = parts[2];
      if (ownerId && ownerId !== String(userId)) {
        return c.json({ detail: "Access denied: cannot access another user's session asset" }, 403);
      }
    }

    if (!fs.existsSync(targetPath) || !fs.statSync(targetPath).isFile()) {
      return c.json({ detail: 'Image asset not found' }, 404);
    }

    const ext = path.extname(targetPath).toLowerCase();
    const mimeTypes: Record<string, string> = {
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.webp': 'image/webp',
    };
    const mime = mimeTypes[ext];
    if (!mime) {
      return c.json({ detail: 'Invalid image asset extension' }, 400);
    }

    const data = fs.readFileSync(targetPath);
    return new Response(data, {
      headers: {
        'Content-Type': mime,
        'Cache-Control': 'private, max-age=3600',
      },
    });
  }

  return c.json({ detail: 'Asset path missing' }, 400);
});

async function handleSearchByImage(c: Context) {
  const user = c.get('user') as AuthUser;
  const body = await c.req.parseBody();
  const file = body['file'];
  if (!file || !(file instanceof File)) {
    return c.json({ detail: 'Image file required' }, 400);
  }

  const arrayBuffer = await file.arrayBuffer();
  const buffer = Buffer.from(arrayBuffer);

  const prompt = typeof body['prompt'] === 'string' ? body['prompt'] : undefined;
  const windowSize = body['window_size'] ? parseInt(String(body['window_size']), 10) : 5;
  const sourceType = typeof body['source_type'] === 'string' ? body['source_type'] : undefined;

  let visResults: Array<{
    page_content: string;
    metadata: Record<string, unknown>;
    score: number;
  }> = [];

  try {
    const siglip = new SigLIP2Engine();
    const queryVector = await siglip.embedImage(buffer);
    const vStore = getVisualStore();
    const hits = await vStore.search(queryVector, {
      limit: windowSize,
      userId: user.id,
      belongsTo: user.email,
      sourceType,
    });
    visResults = hits.map((h) => ({
      page_content: h.page_content,
      metadata: {
        id: h.id,
        image_path: h.image_path,
        has_image: Boolean(h.image_path),
        image_url: h.image_path ? `/api/documents/assets/image?path=${encodeURIComponent(h.image_path)}` : '',
        source: h.source,
        page: h.page,
        title: h.title,
        filename: h.filename,
        source_type: h.source_type,
        resource_id: h.resource_id,
      },
      score: h.score || 0,
    }));
  } catch {
    visResults = [];
  }

  let textResults: Array<{
    page_content: string;
    metadata: Record<string, unknown>;
    score: number;
  }> = [];

  if (prompt && prompt.trim()) {
    try {
      const textHits = await searchDocuments({
        prompt,
        userId: user.id,
        userEmail: user.email,
        windowSize,
        sourceType,
      });
      textResults = textHits.map((h) => ({
        page_content: h.page_content,
        metadata: h.metadata as Record<string, unknown>,
        score: h.score,
      }));
    } catch {
      textResults = [];
    }
  }

  const seenIds = new Set<string>();
  const merged: Array<{
    page_content: string;
    metadata: Record<string, unknown>;
    score: number;
  }> = [];

  for (const item of [...visResults, ...textResults]) {
    const id = String(item.metadata['id'] || '');
    if (id && seenIds.has(id)) continue;
    if (id) seenIds.add(id);
    merged.push(item);
  }

  const documents = merged.slice(0, windowSize);
  return c.json({
    documents,
    count: documents.length,
  });
}

// POST /search/by-image
documentsRouter.post('/search/by-image', authMiddleware, handleSearchByImage);

// POST /search-by-image
documentsRouter.post('/search-by-image', authMiddleware, handleSearchByImage);
