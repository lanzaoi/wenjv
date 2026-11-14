import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import sharp from 'sharp';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { getDb } from '../db/index.js';
import type { ChunkResourceType } from '../db/chunks.js';
import { searchDocuments, type SearchHit } from '../services/search.js';
import { streamChatEvents, type ChatImagePart, type ChatMessage } from '../ai/llm-chat.js';
import { SigLIP2Engine } from '../ai/siglip2.js';
import { getVisualStore } from '../vector/visual-store.js';
import { registerAsset, getAssetsByIds, resolveAuthorizedAsset } from '../services/assets.js';
import { config } from '../config.js';

export const chatRouter = new Hono();

interface RawHistoryMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  images?: string[];
}

async function standardizeImagePart(rawBuffer: Buffer): Promise<ChatImagePart> {
  const stdBytes = await sharp(rawBuffer)
    .rotate()
    .resize(1280, 1280, { fit: 'inside', withoutEnlargement: true })
    .jpeg({ quality: 85 })
    .toBuffer();
  return {
    data: stdBytes.toString('base64'),
    mime_type: 'image/jpeg',
  };
}

async function resolveImageIdentifier(identifier: string, userId: number): Promise<ChatImagePart | null> {
  if (!identifier || typeof identifier !== 'string') return null;
  let candidate = identifier.trim();
  if (!candidate) return null;

  // Case 1: Data URI
  if (candidate.startsWith('data:image/') && candidate.includes(';base64,')) {
    const [, b64] = candidate.split(';base64,', 2);
    if (!b64) return null;
    try {
      return await standardizeImagePart(Buffer.from(b64, 'base64'));
    } catch {
      return null;
    }
  }

  // Case 2: Extract ?id= or ?path= query parameter from API URL
  let assetIdParam: string | undefined;
  if (candidate.includes('path=') || candidate.includes('id=')) {
    try {
      const parsedUrl = new URL(candidate, 'http://localhost');
      const idParam = parsedUrl.searchParams.get('id');
      const pathParam = parsedUrl.searchParams.get('path');
      if (idParam) assetIdParam = idParam;
      if (pathParam) candidate = pathParam;
    } catch {
      // keep candidate as-is
    }
  }

  // Case 3: Registered asset owned by current user only (prevents unregistered upload probing)
  const queries: Array<{ id?: string; path?: string }> = [];
  if (assetIdParam) {
    queries.push({ id: assetIdParam });
  }
  const cleaned = candidate.replace(/^\/+/, '');
  if (cleaned) {
    queries.push({ path: cleaned });
    queries.push({ path: `mm_assets/${cleaned}` });
  }

  for (const q of queries) {
    try {
      const authorized = resolveAuthorizedAsset(userId, q);
      if (authorized) {
        const raw = fs.readFileSync(authorized.absPath);
        return await standardizeImagePart(raw);
      }
    } catch {
      // ignore unauthorized or invalid asset paths
    }
  }

  return null;
}

async function resolveHistoryWithDecay(history: RawHistoryMessage[], userId: number): Promise<ChatMessage[]> {
  const trimmed = history.slice(-8);
  const out: ChatMessage[] = [];
  for (let idx = 0; idx < trimmed.length; idx++) {
    const item = trimmed[idx]!;
    const distFromLatest = trimmed.length - 1 - idx;
    const rawImgs = Array.isArray(item.images) ? item.images : [];
    const msg: ChatMessage = {
      role: item.role,
      content: String(item.content || ''),
    };
    if (rawImgs.length > 0) {
      if (distFromLatest < 2) {
        const resolved: ChatImagePart[] = [];
        for (const imgId of rawImgs) {
          const part = await resolveImageIdentifier(String(imgId), userId);
          if (part) resolved.push(part);
        }
        if (resolved.length > 0) {
          msg.images = resolved;
        }
      } else if (!msg.content.includes('[历史附图')) {
        msg.content = `${msg.content}\n[历史附图: ${rawImgs.length} 张 (已阅，已衰减)]`;
      }
    }
    out.push(msg);
  }
  return out;
}

// GET /models
chatRouter.get('/models', authMiddleware, (c) => {
  return c.json({
    models: Array.from(new Set([config.CHAT_MODEL, 'spark-x2.6'].filter(Boolean))),
  });
});

// POST /attachments
chatRouter.post('/attachments', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const body = await c.req.parseBody();
  const file = body['file'];
  const sessionId = typeof body['session_id'] === 'string' ? body['session_id'] : '';

  if (!file || !(file instanceof File)) {
    return c.json({ detail: 'Missing image file' }, 400);
  }

  const origName = file.name || 'image.jpg';
  const ext = path.extname(origName).toLowerCase();
  const allowed = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'];
  if (!allowed.includes(ext)) {
    return c.json({ detail: `Unsupported image extension ${ext}` }, 400);
  }

  const arrayBuf = await file.arrayBuffer();
  const rawBytes = Buffer.from(arrayBuf);
  if (rawBytes.length === 0) {
    return c.json({ detail: 'Empty file content' }, 400);
  }

  if (rawBytes.length > config.MAX_UPLOAD_BYTES) {
    return c.json({ detail: 'Attachment size exceeds maximum limit' }, 413);
  }

  // Standardize with sharp
  let stdBytes: Buffer;
  try {
    stdBytes = await sharp(rawBytes)
      .rotate()
      .resize(1568, 1568, { fit: 'inside', withoutEnlargement: true })
      .jpeg({ quality: 90 })
      .toBuffer();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: `File is not a valid image: ${msg}` }, 400);
  }

  const safeSession = (sessionId || crypto.randomUUID().slice(0, 12)).replace(/[^a-zA-Z0-9_\-]/g, '') || 'common';
  const uidStr = String(user.id);
  const targetDir = path.join(config.resolvedUploadDir, 'mm_assets', 'sessions', uidStr, safeSession);
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  const stem = path.basename(origName, ext).slice(0, 30).replace(/[^a-zA-Z0-9_\-]/g, '_');
  const mediaId = `${crypto.randomUUID().slice(0, 8)}_${stem}.jpg`;
  const targetPath = path.join(targetDir, mediaId);
  fs.writeFileSync(targetPath, stdBytes);

  const relPath = `mm_assets/sessions/${uidStr}/${safeSession}/${mediaId}`;
  const asset = await registerAsset({
    userId: user.id,
    ownerType: 'chat',
    ownerId: safeSession,
    filename: origName,
    relPath,
    absPath: targetPath,
    mimeType: 'image/jpeg',
    size: stdBytes.length,
    caption: origName,
  });

  const mediaUrl = `/api/assets/image?path=${encodeURIComponent(relPath)}`;

  return c.json({
    asset_id: asset.id,
    media_url: mediaUrl,
    media_id: mediaId,
    filename: origName,
    content_type: 'image/jpeg',
    size: stdBytes.length,
  });
});

// POST /by-image
chatRouter.post('/by-image', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const body = await c.req.parseBody();
  const file = body['file'];

  if (!file || !(file instanceof File)) {
    return c.json({ detail: 'Missing image file' }, 400);
  }
  if (file.size > config.MAX_UPLOAD_BYTES) {
    return c.json({ detail: `Image size exceeds limit of ${config.MAX_UPLOAD_BYTES} bytes` }, 413);
  }

  const prompt = typeof body['prompt'] === 'string' ? body['prompt'].trim() : '';
  const model = typeof body['model'] === 'string' ? body['model'] : config.CHAT_MODEL;
  const windowSize = body['window_size'] ? parseInt(String(body['window_size']), 10) : 5;
  const useRag = String(body['use_rag'] ?? 'true') !== 'false';

  let history: RawHistoryMessage[] = [];
  if (typeof body['history'] === 'string') {
    try {
      const parsedHist = JSON.parse(body['history']);
      if (Array.isArray(parsedHist)) history = parsedHist as RawHistoryMessage[];
    } catch {
      history = [];
    }
  }

  const arrayBuf = await file.arrayBuffer();
  const imgBuffer = Buffer.from(arrayBuf);
  if (imgBuffer.length > config.MAX_UPLOAD_BYTES) {
    return c.json({ detail: `Image size exceeds limit of ${config.MAX_UPLOAD_BYTES} bytes` }, 413);
  }
  const question = prompt || '请详细分析并说明这张图片的内容与关键信息。';

  let uploadedImagePart: ChatImagePart | null = null;
  try {
    uploadedImagePart = await standardizeImagePart(imgBuffer);
  } catch {
    uploadedImagePart = null;
  }

  return streamSSE(c, async (stream) => {
    let citations: Array<Record<string, unknown>> = [];
    let contextBlock = '';

    if (useRag) {
      try {
        const siglip = new SigLIP2Engine();
        const queryVector = await siglip.embedImage(imgBuffer);
        const vStore = getVisualStore();
        const visHits = await vStore.search(queryVector, {
          limit: windowSize,
          userId: user.id,
        });

        const db = getDb();
        const assetMap = getAssetsByIds(
          db,
          visHits.map((h) => h.id),
          user.id
        );

        const hydrated = visHits
          .map((hit) => {
            const asset = assetMap.get(hit.id);
            return asset ? { hit, asset } : null;
          })
          .filter((x): x is NonNullable<typeof x> => x !== null);

        citations = hydrated.map(({ hit, asset }, idx) => ({
          index: idx + 1,
          source: asset.filename,
          page: '1',
          title: asset.caption || asset.filename,
          filename: asset.filename,
          source_type: asset.owner_type,
          resource_id: asset.owner_id,
          score: hit.score,
          snippet: (asset.caption || asset.filename).slice(0, 400),
          page_content: asset.caption || asset.filename,
          has_image: true,
          image_path: asset.file_path,
          image_url: `/api/assets/image?id=${encodeURIComponent(asset.id)}`,
        }));

        const contextParts = hydrated.map(({ asset }, i) => {
          const title = asset.caption || asset.filename || `Visual ${i + 1}`;
          return `[${i + 1}] ${title}\n${asset.caption || asset.filename}`;
        });
        contextBlock = contextParts.join('\n\n---\n\n');
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        await stream.writeSSE({
          data: JSON.stringify({ type: 'error', message: errMsg }),
        });
      }
    }

    await stream.writeSSE({
      data: JSON.stringify({ type: 'citations', citations }),
    });

    const messages: ChatMessage[] = [];
    const resolvedHistory = await resolveHistoryWithDecay(history, user.id);
    if (contextBlock.trim()) {
      messages.push({
        role: 'system',
        content:
          'You are a multimodal document assistant. Answer using the provided visual context and user query.',
      });
      messages.push(...resolvedHistory);
      messages.push({
        role: 'user',
        content: `Visual Context:\n${contextBlock}\n\nQuestion: ${question}\n\nAnswer:`,
        ...(uploadedImagePart ? { images: [uploadedImagePart] } : {}),
      });
    } else {
      messages.push({
        role: 'system',
        content: 'You are a helpful multimodal assistant.',
      });
      messages.push(...resolvedHistory);
      messages.push({
        role: 'user',
        content: question,
        ...(uploadedImagePart ? { images: [uploadedImagePart] } : {}),
      });
    }

    try {
      for await (const ev of streamChatEvents({ model, messages, signal: c.req.raw.signal })) {
        await stream.writeSSE({
          data: JSON.stringify({ type: ev.kind, content: ev.text }),
        });
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      await stream.writeSSE({
        data: JSON.stringify({ type: 'error', message: errMsg }),
      });
    }

    await stream.writeSSE({
      data: JSON.stringify({ type: 'done' }),
    });
  });
});

// POST /
chatRouter.post('/', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();

  const question = String(json.question || '').trim();
  if (!question) {
    return c.json({ detail: 'Missing question' }, 400);
  }

  const model = json.model ? String(json.model) : config.CHAT_MODEL;
  const windowSize = json.window_size ? parseInt(json.window_size, 10) : 5;
  const useRag = json.use_rag !== false;
  const rawSt = json.type ?? json.source_type;
  const sourceType: ChunkResourceType | undefined =
    rawSt === 'file' || rawSt === 'note' || rawSt === 'link' || rawSt === 'wiki' ? rawSt : undefined;
  const includeSources = Array.isArray(json.include_sources) ? json.include_sources : undefined;
  const excludeSources = Array.isArray(json.exclude_sources) ? json.exclude_sources : undefined;
  const tags = Array.isArray(json.tags) ? json.tags : undefined;
  const history: RawHistoryMessage[] = Array.isArray(json.history) ? json.history : [];
  const rawImages: string[] = Array.isArray(json.images) ? json.images.map(String) : [];

  const currentImages: ChatImagePart[] = [];
  for (const imgId of rawImages) {
    const resolved = await resolveImageIdentifier(imgId, user.id);
    if (resolved) currentImages.push(resolved);
  }

  return streamSSE(c, async (stream) => {
    let citations: Array<Record<string, unknown>> = [];
    let contextBlock = '';

    if (useRag) {
      try {
        const hits = await searchDocuments({
          prompt: question,
          userId: user.id,
          userEmail: user.email,
          windowSize,
          sourceType,
          includeSources,
          excludeSources,
          tags,
        });

        citations = hits.map((hit: SearchHit, idx: number) => ({
          index: idx + 1,
          source: hit.metadata.source || hit.metadata.filename || 'unknown',
          page: hit.metadata.page || '1',
          title: hit.metadata.title || hit.metadata.filename || 'Document',
          filename: hit.metadata.filename || '',
          source_type: hit.metadata.source_type || 'file',
          resource_id: hit.metadata.resource_id || undefined,
          score: hit.score,
          snippet: hit.page_content.slice(0, 400),
          page_content: hit.page_content,
          tag_matched: Boolean(hit.metadata.tag_matched),
          has_image: Boolean(hit.metadata.image_path),
          image_path: hit.metadata.image_path || null,
          image_url: hit.metadata.image_path ? `/api/assets/image?path=${encodeURIComponent(hit.metadata.image_path)}` : null,
        }));

        const contextParts = hits.map((h, i) => {
          const title = h.metadata.title || h.metadata.filename || `Doc ${i + 1}`;
          return `[${i + 1}] ${title}\n${h.page_content}`;
        });
        contextBlock = contextParts.join('\n\n---\n\n');
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        await stream.writeSSE({
          data: JSON.stringify({ type: 'error', message: errMsg }),
        });
      }
    }

    await stream.writeSSE({
      data: JSON.stringify({ type: 'citations', citations }),
    });

    const messages: ChatMessage[] = [];
    const resolvedHistory = await resolveHistoryWithDecay(history, user.id);
    if (contextBlock.trim()) {
      messages.push({
        role: 'system',
        content:
          'You are a document Q&A assistant. Answer using ONLY the provided context. If the answer is not in the context, say you cannot answer based on the provided context. Cite sources like [1], [2] when useful.',
      });
      messages.push(...resolvedHistory);
      messages.push({
        role: 'user',
        content: `Context:\n${contextBlock}\n\nQuestion: ${question}\n\nAnswer:`,
        ...(currentImages.length > 0 ? { images: currentImages } : {}),
      });
    } else {
      messages.push({
        role: 'system',
        content: 'You are a helpful Q&A assistant.',
      });
      messages.push(...resolvedHistory);
      messages.push({
        role: 'user',
        content: question,
        ...(currentImages.length > 0 ? { images: currentImages } : {}),
      });
    }

    try {
      for await (const ev of streamChatEvents({ model, messages, signal: c.req.raw.signal })) {
        await stream.writeSSE({
          data: JSON.stringify({ type: ev.kind, content: ev.text }),
        });
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      await stream.writeSSE({
        data: JSON.stringify({ type: 'error', message: errMsg }),
      });
    }

    await stream.writeSSE({
      data: JSON.stringify({ type: 'done' }),
    });
  });
});
