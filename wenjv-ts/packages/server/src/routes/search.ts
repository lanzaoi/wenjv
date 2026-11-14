import { Hono } from 'hono';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { getDb } from '../db/index.js';
import type { ChunkResourceType } from '../db/chunks.js';
import { searchDocuments } from '../services/search.js';
import { getAssetsByIds } from '../services/assets.js';
import { SigLIP2Engine } from '../ai/siglip2.js';
import { getVisualStore } from '../vector/visual-store.js';
import { config } from '../config.js';

export const searchRouter = new Hono();

function parseResourceType(raw: unknown): ChunkResourceType | undefined {
  if (raw === 'file' || raw === 'note' || raw === 'link' || raw === 'wiki') {
    return raw;
  }
  return undefined;
}

// POST /search
searchRouter.post('/', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();

  const prompt = String(json.prompt || json.query || json.question || '');
  const windowSize = json.window_size ? parseInt(String(json.window_size), 10) : 5;
  const sourceType = parseResourceType(json.type ?? json.source_type);
  const includeSources = Array.isArray(json.include_sources) ? json.include_sources.map(String) : undefined;
  const excludeSources = Array.isArray(json.exclude_sources) ? json.exclude_sources.map(String) : undefined;
  const tags = Array.isArray(json.tags) ? json.tags.map(String) : undefined;

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

// POST /search/by-image
searchRouter.post('/by-image', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const body = await c.req.parseBody();
  const file = body['file'];
  if (!file || !(file instanceof File)) {
    return c.json({ detail: 'Image file required' }, 400);
  }
  if (file.size > config.MAX_UPLOAD_BYTES) {
    return c.json({ detail: `Image size exceeds limit of ${config.MAX_UPLOAD_BYTES} bytes` }, 413);
  }

  const buffer = Buffer.from(await file.arrayBuffer());
  if (buffer.length > config.MAX_UPLOAD_BYTES) {
    return c.json({ detail: `Image size exceeds limit of ${config.MAX_UPLOAD_BYTES} bytes` }, 413);
  }
  const prompt = typeof body['prompt'] === 'string' ? body['prompt'] : undefined;
  const windowSize = body['window_size'] ? parseInt(String(body['window_size']), 10) : 5;
  const sourceType = parseResourceType(body['type'] ?? body['source_type']);

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
    });

    const db = getDb();
    const assetMap = getAssetsByIds(
      db,
      hits.map((h) => h.id),
      user.id
    );

    visResults = hits
      .map((h) => {
        const asset = assetMap.get(h.id);
        if (!asset) return null;
        return {
          page_content: asset.caption || asset.filename,
          metadata: {
            id: asset.id,
            image_path: asset.file_path,
            has_image: true,
            image_url: `/api/assets/image?id=${encodeURIComponent(asset.id)}`,
            title: asset.caption || asset.filename,
            filename: asset.filename,
            source_type: asset.owner_type,
            resource_id: asset.owner_id,
          },
          score: h.score || 0,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
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
});
