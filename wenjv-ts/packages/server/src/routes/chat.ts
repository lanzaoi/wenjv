import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import sharp from 'sharp';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { searchDocuments, type SearchHit } from '../services/search.js';
import { streamChatCompletions, type ChatMessage } from '../ai/llm-chat.js';
import { SigLIP2Engine } from '../ai/siglip2.js';
import { getVisualStore } from '../vector/visual-store.js';
import { config } from '../config.js';

export const chatRouter = new Hono();

// GET /models
chatRouter.get('/models', authMiddleware, (c) => {
  return c.json({
    models: [config.CHAT_MODEL, 'spark-x2.6'].filter(Boolean),
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
  const mediaUrl = `/api/documents/assets/image?path=${encodeURIComponent(relPath)}`;

  return c.json({
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

  const prompt = typeof body['prompt'] === 'string' ? body['prompt'].trim() : '';
  const model = typeof body['model'] === 'string' ? body['model'] : config.CHAT_MODEL;
  const windowSize = body['window_size'] ? parseInt(String(body['window_size']), 10) : 5;
  const sourceType = typeof body['source_type'] === 'string' ? body['source_type'] : undefined;
  const useRag = String(body['use_rag'] ?? 'true') !== 'false';

  let history: Array<{ role: 'user' | 'assistant' | 'system'; content: string }> = [];
  if (typeof body['history'] === 'string') {
    try {
      history = JSON.parse(body['history']);
    } catch {
      history = [];
    }
  }

  const arrayBuf = await file.arrayBuffer();
  const imgBuffer = Buffer.from(arrayBuf);
  const question = prompt || '请详细分析并说明这张图片的内容与关键信息。';

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
          belongsTo: user.email,
          sourceType,
        });

        citations = visHits.map((hit, idx) => ({
          index: idx + 1,
          source: hit.source || hit.filename || 'visual',
          page: hit.page || '1',
          title: hit.title || hit.filename || 'Visual Document',
          filename: hit.filename || '',
          source_type: hit.source_type || 'visual',
          score: hit.score || 0,
          snippet: hit.page_content.slice(0, 400),
          page_content: hit.page_content,
          has_image: Boolean(hit.image_path),
          image_path: hit.image_path || null,
          image_url: hit.image_path ? `/documents/assets/image?path=${encodeURIComponent(hit.image_path)}` : null,
        }));

        const contextParts = visHits.map((h, i) => {
          const title = h.title || h.filename || `Visual ${i + 1}`;
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
    if (contextBlock.trim()) {
      messages.push({
        role: 'system',
        content:
          'You are a multimodal document assistant. Answer using the provided visual context and user query.',
      });
      messages.push(...history.slice(-8));
      messages.push({
        role: 'user',
        content: `Visual Context:\n${contextBlock}\n\nQuestion: ${question}\n\nAnswer:`,
      });
    } else {
      messages.push({
        role: 'system',
        content: 'You are a helpful multimodal assistant.',
      });
      messages.push(...history.slice(-8));
      messages.push({
        role: 'user',
        content: question,
      });
    }

    try {
      for await (const token of streamChatCompletions({ model, messages, signal: c.req.raw.signal })) {
        await stream.writeSSE({
          data: JSON.stringify({ type: 'token', content: token }),
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
  const sourceType = json.source_type ? String(json.source_type) : undefined;
  const includeSources = Array.isArray(json.include_sources) ? json.include_sources : undefined;
  const excludeSources = Array.isArray(json.exclude_sources) ? json.exclude_sources : undefined;
  const tags = Array.isArray(json.tags) ? json.tags : undefined;
  const history: Array<{ role: 'user' | 'assistant' | 'system'; content: string }> = Array.isArray(json.history)
    ? json.history
    : [];

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
          score: hit.score,
          snippet: hit.page_content.slice(0, 400),
          page_content: hit.page_content,
          tag_matched: Boolean(hit.metadata.tag_matched),
          tag_fallback: Boolean(hit.metadata.tag_fallback),
          has_image: Boolean(hit.metadata.image_path),
          image_path: hit.metadata.image_path || null,
          image_url: hit.metadata.image_path ? `/documents/assets/image?path=${encodeURIComponent(hit.metadata.image_path)}` : null,
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
    if (contextBlock.trim()) {
      messages.push({
        role: 'system',
        content:
          'You are a document Q&A assistant. Answer using ONLY the provided context. If the answer is not in the context, say you cannot answer based on the provided context. Cite sources like [1], [2] when useful.',
      });
      messages.push(...history.slice(-8));
      messages.push({
        role: 'user',
        content: `Context:\n${contextBlock}\n\nQuestion: ${question}\n\nAnswer:`,
      });
    } else {
      messages.push({
        role: 'system',
        content: 'You are a helpful Q&A assistant.',
      });
      messages.push(...history.slice(-8));
      messages.push({
        role: 'user',
        content: question,
      });
    }

    try {
      for await (const token of streamChatCompletions({ model, messages, signal: c.req.raw.signal })) {
        await stream.writeSSE({
          data: JSON.stringify({ type: 'token', content: token }),
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
